"""Speaker-edit API regressions using synthetic jobs in an isolated data folder.

No speech models, Ollama, production recordings, or network services are used.
The edit endpoint accepts complete replacement lists, as sent by Save changes.
"""
from copy import deepcopy
import importlib.util
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import sys
from unittest.mock import Mock
import uuid

from docx import Document
from fastapi.testclient import TestClient
import pytest


HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))


@pytest.fixture(scope="module")
def assignment_api():
    data = HERE / ("speaker-assignment-state-" + uuid.uuid4().hex)
    prior = os.environ.get("MEETING_STUDIO_DATA")
    os.environ["MEETING_STUDIO_DATA"] = str(data)
    try:
        spec = importlib.util.spec_from_file_location("meeting_studio_speaker_assignment", APP / "server.py")
        server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)
        server.executor.shutdown(wait=False, cancel_futures=True)
        server.executor = Mock()
        assert server.DATA_DIR == data.resolve()
        assert server.DATA_DIR != (APP / "data").resolve()
        with TestClient(server.app, base_url="http://127.0.0.1:8765",
                        raise_server_exceptions=False) as client:
            yield server, client
    finally:
        if prior is None:
            os.environ.pop("MEETING_STUDIO_DATA", None)
        else:
            os.environ["MEETING_STUDIO_DATA"] = prior
        # Remove only the exact synthetic folder created by this fixture.
        if data.exists():
            assert data.resolve().parent == HERE
            assert data.name.startswith("speaker-assignment-state-")
            shutil.rmtree(data)


@pytest.fixture
def assignment_job(assignment_api):
    server, client = assignment_api
    job_id = uuid.uuid4().hex
    job = {
        "id": job_id, "title": "Synthetic planning meeting", "filename": "synthetic.wav",
        "audio_file": "source.wav", "created_at": "2026-09-23T12:00:00+00:00",
        "updated_at": "2026-09-23T12:00:00+00:00", "status": "complete", "stage": "Ready",
        "duration": 40, "language": "en", "requested_language": "en", "num_speakers": 0,
        "speakers": [{"id": "SPEAKER_00", "name": "Alex"},
                     {"id": "SPEAKER_01", "name": "Blair"},
                     {"id": "SPEAKER_02", "name": "Casey"},
                     {"id": "UNKNOWN", "name": "Unassigned"}],
        # Non-contiguous IDs make accidental use of array indices detectable.
        "segments": [
            {"id": 4, "start": 0.25, "end": 3.5, "speaker": "SPEAKER_00", "text": "First, review the plan."},
            {"id": 12, "start": 3.6, "end": 7.2, "speaker": "SPEAKER_01", "text": "The draft is ready."},
            {"id": 13, "start": 7.4, "end": 8.1, "speaker": "UNKNOWN", "text": "Agreed."},
            {"id": 29, "start": 9.05, "end": 15.75, "speaker": "SPEAKER_02", "text": "I will check the café booking."},
            {"id": 57, "start": 16.0, "end": 24.25, "speaker": "SPEAKER_01", "text": "Send the invitations tomorrow."},
            {"id": 88, "start": 26.5, "end": 31.9, "speaker": "SPEAKER_00", "text": "That completes the agenda."},
        ],
        "notes": {"overview": "The team discussed its plan.", "decisions": [], "actions": [], "open_questions": []},
        "notes_status": "complete", "notes_stale": False, "transcript_revision": 7, "warnings": [],
    }
    server.jobs[job_id] = deepcopy(job)
    server.save_job(job)
    return server, client, job


def assigned_segments(job, assignments):
    return [{**segment, "speaker": assignments.get(segment["id"], segment["speaker"])}
            for segment in job["segments"]]


def assert_content_preserved(original, edited):
    # This compares order, every ID, all timestamps and exact text, not just length.
    without_speakers = lambda rows: [{k: v for k, v in row.items() if k != "speaker"} for row in rows]
    assert without_speakers(edited) == without_speakers(original)


def assert_one_saved_revision(original, saved):
    assert saved["transcript_revision"] == original["transcript_revision"] + 1
    assert saved["notes_stale"] is True
    assert saved["notes"] == original["notes"]
    assert_content_preserved(original["segments"], saved["segments"])


def test_assign_noncontiguous_selection_changes_only_selected_labels(assignment_job):
    server, client, original = assignment_job
    assignments = {4: "SPEAKER_02", 13: "SPEAKER_02", 57: "SPEAKER_02"}
    expected = assigned_segments(original, assignments)
    response = client.patch(f"/api/jobs/{original['id']}", json={"segments": expected})
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["segments"] == expected
    assert saved["speakers"] == original["speakers"]
    assert_one_saved_revision(original, saved)
    assert server.get_job(original["id"])["segments"] == expected


@pytest.mark.parametrize("replacement", ["SPEAKER_00", "UNKNOWN"])
def test_remove_used_person_and_reassign_all_lines_is_one_atomic_save(assignment_job, monkeypatch, replacement):
    server, client, original = assignment_job
    people = [p for p in original["speakers"] if p["id"] != "SPEAKER_01"]
    segments = assigned_segments(original, {s["id"]: replacement for s in original["segments"]
                                           if s["speaker"] == "SPEAKER_01"})
    save = Mock(wraps=server.save_job)
    monkeypatch.setattr(server, "save_job", save)
    response = client.patch(f"/api/jobs/{original['id']}", json={"speakers": people, "segments": segments})
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["speakers"] == people
    assert saved["segments"] == segments
    assert_one_saved_revision(original, saved)
    save.assert_called_once()
    written = save.call_args.args[0]
    assert written["speakers"] == people and written["segments"] == segments
    assert not any(s["speaker"] == "SPEAKER_01" for s in written["segments"])
    assert json.loads((server.JOBS_DIR / original["id"] / "job.json").read_text(encoding="utf-8")) == server.get_job(original["id"])


@pytest.mark.parametrize("partial_reassignment", [False, True])
def test_remove_used_person_without_complete_reassignment_leaves_all_state_untouched(assignment_job, monkeypatch, partial_reassignment):
    server, client, original = assignment_job
    metadata = server.JOBS_DIR / original["id"] / "job.json"
    disk_before = metadata.read_bytes()
    patch = {"speakers": [p for p in original["speakers"] if p["id"] != "SPEAKER_01"]}
    if partial_reassignment:
        patch["segments"] = assigned_segments(original, {12: "SPEAKER_00"})
    save = Mock(wraps=server.save_job)
    monkeypatch.setattr(server, "save_job", save)
    response = client.patch(f"/api/jobs/{original['id']}", json=patch)
    assert response.status_code == 400
    assert server.get_job(original["id"]) == original
    assert metadata.read_bytes() == disk_before
    save.assert_not_called()


def test_add_manual_person_and_assign_from_existing_and_unassigned(assignment_job):
    _, client, original = assignment_job
    manual = {"id": "MANUAL_test_person", "name": "Drew"}
    segments = assigned_segments(original, {4: manual["id"], 13: manual["id"], 29: "UNKNOWN"})
    response = client.patch(f"/api/jobs/{original['id']}", json={
        "speakers": original["speakers"] + [manual], "segments": segments})
    assert response.status_code == 200, response.text
    assert response.json()["speakers"][-1] == manual
    assert response.json()["segments"] == segments
    assert_one_saved_revision(original, response.json())


def test_assignment_can_add_unassigned_when_it_was_absent(assignment_job):
    server, client, original = assignment_job
    original["speakers"] = [p for p in original["speakers"] if p["id"] != "UNKNOWN"]
    original["segments"] = assigned_segments(original, {13: "SPEAKER_00"})
    server.jobs[original["id"]] = deepcopy(original)
    server.save_job(original)
    people = original["speakers"] + [{"id": "UNKNOWN", "name": "Unassigned"}]
    segments = assigned_segments(original, {29: "UNKNOWN"})
    response = client.patch(f"/api/jobs/{original['id']}", json={"speakers": people, "segments": segments})
    assert response.status_code == 200, response.text
    assert response.json()["segments"] == segments
    assert response.json()["speakers"] == people
    assert_one_saved_revision(original, response.json())


def test_saved_assignments_survive_reload_and_all_exports(assignment_job):
    server, client, original = assignment_job
    new_person = {"id": "MANUAL_drew", "name": "Drew"}
    people = [p for p in original["speakers"] if p["id"] != "SPEAKER_01"] + [new_person]
    segments = assigned_segments(original, {12: new_person["id"], 57: new_person["id"], 13: "SPEAKER_00"})
    url = f"/api/jobs/{original['id']}"
    response = client.patch(url, json={"speakers": people, "segments": segments})
    assert response.status_code == 200, response.text
    saved = response.json()
    server.jobs.clear()
    server.load_jobs()
    assert client.get(url).json() == saved
    json_export = client.get(url + "/export?format=json")
    assert json_export.status_code == 200
    assert json_export.json() == saved
    markdown_export = client.get(url + "/export?format=md")
    word_export = client.get(url + "/export?format=docx")
    assert markdown_export.status_code == word_export.status_code == 200
    markdown = markdown_export.text
    word_paragraphs = [p.text for p in Document(BytesIO(word_export.content)).paragraphs]
    word = "\n".join(word_paragraphs)
    assert "Notes need updating" in markdown and "Notes need updating" in word
    assert "Blair" not in markdown and "Blair" not in word
    # Separate turns retain their new names, source time and exact Word text.
    assert "**00:03 — Drew**" in markdown
    assert "**00:16 — Drew**" in markdown
    assert "00:03  Drew\nThe draft is ready." in word_paragraphs
    assert "00:16  Drew\nSend the invitations tomorrow." in word_paragraphs
    for segment in original["segments"]:
        assert segment["text"] in word


def test_failed_save_does_not_commit_partial_edit_to_memory(assignment_job, monkeypatch):
    server, client, original = assignment_job
    metadata = server.JOBS_DIR / original["id"] / "job.json"
    disk_before = metadata.read_bytes()
    people = [p for p in original["speakers"] if p["id"] != "SPEAKER_01"]
    segments = assigned_segments(original, {12: "SPEAKER_00", 57: "SPEAKER_00"})
    def fail_save(job):
        raise OSError("Synthetic storage failure")
    monkeypatch.setattr(server, "save_job", fail_save)
    response = client.patch(f"/api/jobs/{original['id']}", json={"speakers": people, "segments": segments})
    assert response.status_code >= 500
    assert metadata.read_bytes() == disk_before
    assert server.get_job(original["id"]) == original

