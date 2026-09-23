"""Isolated API and notes-grounding regression tests; no speech models or Ollama."""
from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import sys
from unittest.mock import Mock
import uuid

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT
sys.path.insert(0, str(APP))


@pytest.fixture(scope="module")
def api():
    # Choose the isolated directory before the server module resolves DATA_DIR.
    data = Path(__file__).parent / ("server-state-" + uuid.uuid4().hex)
    prior = os.environ.get("MEETING_STUDIO_DATA")
    os.environ["MEETING_STUDIO_DATA"] = str(data)
    spec = importlib.util.spec_from_file_location("meeting_studio_server_review", APP / "server.py")
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    real_executor = server.executor
    real_executor.shutdown(wait=False, cancel_futures=True)
    server.executor = Mock()
    server.speech_models_status = lambda: {"ready": True}
    server.ollama_status = lambda: {"available": True, "models": ["qwen3.5:9b"]}
    try:
        with TestClient(server.app, base_url="http://127.0.0.1:8765",
                        raise_server_exceptions=False) as client:
            yield server, client
    finally:
        if prior is None:
            os.environ.pop("MEETING_STUDIO_DATA", None)
        else:
            os.environ["MEETING_STUDIO_DATA"] = prior


@pytest.fixture
def ready_job(api):
    server, client = api
    server.executor.reset_mock()
    job_id = uuid.uuid4().hex
    job = {
        "id": job_id, "title": "Test meeting", "filename": "fixture.wav",
        "audio_file": "source.wav", "created_at": "2026-09-22T12:00:00+00:00",
        "status": "complete", "stage": "Ready", "duration": 20, "language": "en",
        "requested_language": "en", "num_speakers": 0,
        "speakers": [{"id": "SPEAKER_00", "name": "Speaker 1"}],
        "segments": [{"id": 0, "start": 0, "end": 15, "speaker": "SPEAKER_00", "text": "We will review the draft."}],
        "notes": {"overview": "A draft review was discussed.", "decisions": [], "actions": [], "open_questions": []},
        "notes_status": "complete", "notes_stale": False, "transcript_revision": 1,
        "warnings": [],
    }
    server.jobs[job_id] = deepcopy(job)
    server.save_job(job)
    (server.JOBS_DIR / job_id / "source.wav").write_bytes(b"fixture audio bytes")
    return server, client, job


@pytest.mark.parametrize("modify,expected", [
    (lambda j: {"speakers": j["speakers"] * 2}, 400),
    (lambda j: {"segments": j["segments"] * 2}, 400),
    (lambda j: {"segments": [{**j["segments"][0], "speaker": "missing"}]}, 400),
    (lambda j: {"segments": [{**j["segments"][0], "start": 18, "end": 15}]}, 400),
    (lambda j: {"segments": [{**j["segments"][0], "end": 99}]}, 400),
    (lambda j: {"segments": [{**j["segments"][0], "start": -1}]}, 422),
])
def test_invalid_edits_leave_saved_transcript_unchanged(ready_job, modify, expected):
    server, client, job = ready_job
    response = client.patch(f"/api/jobs/{job['id']}", json=modify(deepcopy(job)))
    assert response.status_code == expected
    assert server.get_job(job["id"])["segments"] == job["segments"]
    assert server.get_job(job["id"])["transcript_revision"] == 1


def test_name_edit_increments_revision_and_marks_notes_stale(ready_job):
    _, client, job = ready_job
    response = client.patch(f"/api/jobs/{job['id']}", json={
        "speakers": [{"id": "SPEAKER_00", "name": "Alex"}]})
    assert response.status_code == 200
    assert response.json()["transcript_revision"] == 2
    assert response.json()["notes_stale"] is True
    assert "audio_file" not in response.json()


def test_one_speaker_upload_passes_explicit_count_to_worker(api):
    server, client = api
    server.executor.reset_mock()
    response = client.post("/api/jobs", data={"language": "en", "num_speakers": "1"},
                           files=[("files", ("one-person.wav", b"test audio", "audio/wav"))])
    assert response.status_code == 200
    value = response.json()
    uploaded = value[0] if isinstance(value, list) else value["jobs"][0]
    assert uploaded["num_speakers"] == 1
    assert server.get_job(uploaded["id"])["num_speakers"] == 1
    server.executor.submit.assert_called_once_with(server.transcribe_worker, uploaded["id"])


def test_consolidating_speakers_preserves_text_times_and_marks_notes_stale(ready_job):
    server, client, job = ready_job
    original = [{"id": 0, "start": 0, "end": 3, "speaker": "SPEAKER_00", "text": "A thought."},
                {"id": 1, "start": 4, "end": 7, "speaker": "SPEAKER_01", "text": "Still my voice."},
                {"id": 2, "start": 8, "end": 9, "speaker": "UNKNOWN", "text": "A final word."}]
    server.update_job(job["id"], segments=original, speakers=[
        {"id": "SPEAKER_00", "name": "Alex"}, {"id": "SPEAKER_01", "name": "Speaker 2"},
        {"id": "UNKNOWN", "name": "Unassigned"}])
    expected = [{**segment, "speaker": "SPEAKER_00"} for segment in original]
    response = client.patch(f"/api/jobs/{job['id']}", json={
        "speakers": [{"id": "SPEAKER_00", "name": "Alex"}], "segments": expected})
    assert response.status_code == 200
    saved = client.get(f"/api/jobs/{job['id']}").json()
    assert saved["segments"] == expected
    assert saved["speakers"] == [{"id": "SPEAKER_00", "name": "Alex"}]
    assert saved["notes_stale"] is True


def test_note_generation_preserves_revision_race_warning(ready_job, monkeypatch):
    server, _, job = ready_job
    def generate(snapshot, model, progress):
        assert snapshot["transcript_revision"] == 1
        server.update_job(job["id"], transcript_revision=2)
        return job["notes"]
    monkeypatch.setattr(server, "generate_notes", generate)
    server.notes_worker(job["id"], "mock-model")
    current = server.get_job(job["id"])
    assert current["notes_status"] == "complete"
    assert current["notes_stale"] is True


def test_duplicate_notes_requests_only_queue_once(ready_job):
    server, client, job = ready_job
    url = f"/api/jobs/{job['id']}/notes"
    assert client.post(url, json={"model": "mock-model"}).status_code == 200
    assert client.post(url, json={"model": "mock-model"}).status_code == 200
    server.executor.submit.assert_called_once()
    function, job_id, model, snapshot = server.executor.submit.call_args.args
    assert (function, job_id, model) == (server.notes_worker, job["id"], "mock-model")
    assert snapshot["notes_template"] == "meeting"
    assert snapshot["segments"] == job["segments"]


@pytest.mark.parametrize("second_name,second_data", [("wrong.exe", b"wrong"), ("empty.wav", b"")])
def test_bad_batch_does_not_publish_any_recordings(api, second_name, second_data):
    server, client = api
    server.executor.reset_mock()
    before_jobs = set(server.jobs)
    before_dirs = set(server.JOBS_DIR.iterdir())
    response = client.post("/api/jobs", data={"language": "en", "num_speakers": "0"}, files=[
        ("files", ("valid.wav", b"some audio", "audio/wav")),
        ("files", (second_name, second_data, "application/octet-stream")),
    ])
    assert response.status_code == 400
    assert set(server.jobs) == before_jobs
    assert set(server.JOBS_DIR.iterdir()) == before_dirs
    server.executor.submit.assert_not_called()


def test_upload_strips_path_and_metadata_hides_internal_audio_file(api):
    server, client = api
    server.executor.reset_mock()
    response = client.post("/api/jobs", files=[
        ("files", (r"..\..\recording.wav", b"some audio", "audio/wav"))])
    assert response.status_code == 200
    job = response.json()["jobs"][0]
    assert job["filename"] == "recording.wav"
    assert "audio_file" not in job
    assert (server.JOBS_DIR / job["id"] / "source.wav").is_file()
    server.executor.submit.assert_called_once()


def test_audio_path_cannot_escape_recording_directory(ready_job):
    server, client, job = ready_job
    (server.DATA_DIR / "outside-secret.txt").write_text("private sentinel", encoding="utf-8")
    server.jobs[job["id"]]["audio_file"] = "../../outside-secret.txt"
    response = client.get(f"/api/jobs/{job['id']}/audio")
    assert response.status_code == 404
    assert "private sentinel" not in response.text
    assert client.get("/api/jobs/not-a-valid-id").status_code == 404


@pytest.mark.parametrize("headers", [
    {"Origin": "https://evil.example"},
    {"Origin": "http://127.0.0.1:9999"},
    {"Origin": "null"},
    {"Sec-Fetch-Site": "cross-site"},
    {"Host": "evil.example"},
])
def test_foreign_origin_or_host_cannot_read_recordings(api, headers):
    _, client = api
    assert client.get("/api/jobs", headers=headers).status_code == 403


def test_same_origin_works_and_api_has_privacy_headers(api):
    _, client = api
    response = client.get("/api/jobs", headers={"Origin": "http://127.0.0.1:8765"})
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_invalid_note_citations_and_missing_evidence_are_discarded():
    from notes import clean_notes
    result = clean_notes({"overview": "Example", "decisions": [
        {"text": "Unsupported", "segment_ids": [999]},
        {"text": "No evidence", "segment_ids": []},
        {"text": "Cited", "segment_ids": [0, 0, True, "0", 999]},
    ], "actions": [{"text": "Task", "segment_ids": [0], "owner": "", "due": None}],
        "open_questions": []}, {0})
    assert result["decisions"] == [{"text": "Cited", "segment_ids": [0]}]
    assert result["actions"][0]["owner"] == "Not specified"
    assert result["actions"][0]["due"] == "Not specified"


@pytest.mark.parametrize("stage", ["transcript", "reduction"])
def test_notes_can_only_cite_sources_present_in_each_prompt(monkeypatch, stage):
    import notes
    calls = []
    def generated(model, source, allowed_ids):
        if "transcript" in source:
            source_ids = {row["segment_id"] for row in source["transcript"]}
            calls.append(("transcript", set(allowed_ids), source_ids))
            return {"overview": "A test summary.", "decisions": [
                {"text": "A test decision.", "segment_ids": sorted(source_ids)}],
                "actions": [], "open_questions": []}
        source_ids = {sid for doc in source["source_notes"] for category in
                      ("decisions", "actions", "open_questions")
                      for row in doc[category] for sid in row["segment_ids"]}
        calls.append(("reduction", set(allowed_ids), source_ids))
        return {"overview": "A combined summary.", "decisions": [
            {"text": "A combined decision.", "segment_ids": sorted(source_ids)}],
            "actions": [], "open_questions": []}
    monkeypatch.setattr(notes, "validate_model", lambda model: None)
    monkeypatch.setattr(notes, "_generate", generated)
    job = {"title": "Synthetic note grounding", "speakers": [], "segments": [
        {"id": i, "start": i * 30, "speaker": "SPEAKER_00", "text": "x" * 9000}
        for i in range(5)]}
    notes.generate_notes(job, "mock-model")
    relevant = [call for call in calls if call[0] == stage]
    assert relevant
    for _, allowed, present in relevant:
        assert allowed <= present, f"Allowed citations {allowed - present} were absent from the supplied source"

