"""Template selection, grounded prompts and queued generation race regressions."""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest
from test_speaker_assignment import assignment_api, assignment_job
import notes
from note_templates import get_template


def test_catalog_contains_exact_template_sections_and_legacy_default(assignment_api):
    _, client = assignment_api
    data = client.get("/api/note-templates").json()
    assert data["default"] == "meeting"
    catalog = {item["id"]: item for item in data["templates"]}
    assert set(catalog) == {"meeting", "lecture", "journal"}
    assert [s["label"] for s in catalog["lecture"]["sections"]] == ["Key concepts", "Study tasks", "Review questions"]
    assert [s["label"] for s in catalog["journal"]["sections"]] == ["Highlights & reflections", "Follow-ups", "Open questions"]
    assert catalog["meeting"]["sections"][1]["show_owner_due"] is True
    assert catalog["lecture"]["sections"][1]["show_owner_due"] is False
    assert get_template(None)["id"] == get_template("unknown")["id"] == "meeting"


def test_template_preference_persists_without_changing_transcript_and_can_revert(assignment_job):
    server, client, original = assignment_job
    url = f"/api/jobs/{original['id']}"
    assert client.get(url).json()["notes_template"] == "meeting"
    changed = client.patch(url, json={"notes_template": "lecture"})
    assert changed.status_code == 200
    saved = changed.json()
    assert saved["notes_template"] == "lecture" and saved["notes_stale"] is True
    assert saved["notes"] == original["notes"]  # Old meeting notes are not relabelled.
    assert saved["segments"] == original["segments"]
    assert saved["transcript_revision"] == original["transcript_revision"]
    server.jobs.clear()
    server.load_jobs()
    assert client.get(url).json()["notes_template"] == "lecture"
    reverted = client.patch(url, json={"notes_template": "meeting"}).json()
    assert reverted["notes_stale"] is False
    assert reverted["transcript_revision"] == original["transcript_revision"]


def test_switching_back_does_not_clear_staleness_from_source_edit(assignment_job):
    _, client, original = assignment_job
    url = f"/api/jobs/{original['id']}"
    segments = deepcopy(original["segments"])
    segments[0]["text"] = "A changed source statement."
    assert client.patch(url, json={"notes_template": "lecture", "segments": segments}).status_code == 200
    value = client.patch(url, json={"notes_template": "meeting"}).json()
    assert value["notes_stale"] is True
    assert value["transcript_revision"] == original["transcript_revision"] + 1


@pytest.mark.parametrize("route,payload", [("", {"notes_template": "unknown"}),
                                          ("/notes", {"template": "unknown"})])
def test_invalid_template_leaves_recording_untouched(assignment_job, route, payload):
    server, client, original = assignment_job
    server.executor.reset_mock()
    metadata = server.JOBS_DIR / original["id"] / "job.json"
    disk_before = metadata.read_bytes()
    response = (client.post if route else client.patch)(f"/api/jobs/{original['id']}" + route, json=payload)
    assert response.status_code == 422
    assert server.get_job(original["id"]) == original
    assert metadata.read_bytes() == disk_before
    server.executor.submit.assert_not_called()


def test_queued_generation_retains_snapshot_and_actual_template_after_switch(assignment_job, monkeypatch):
    server, client, original = assignment_job
    server.executor.reset_mock()
    url = f"/api/jobs/{original['id']}"
    queued = client.post(url + "/notes", json={"model": "mock-model", "template": "lecture"})
    assert queued.status_code == 200
    function, job_id, model, snapshot = server.executor.submit.call_args.args
    assert snapshot["notes_template"] == "lecture"
    assert client.patch(url, json={"notes_template": "journal"}).status_code == 200
    captured = []
    def generate(job, selected_model, progress):
        captured.append(deepcopy(job))
        assert selected_model == "mock-model"
        return {**original["notes"], "overview": "Lecture content", "template": "journal"}
    monkeypatch.setattr(server, "generate_notes", generate)
    function(job_id, model, snapshot)
    value = client.get(url).json()
    assert captured[0]["notes_template"] == "lecture"
    assert value["notes_template"] == "journal"
    assert value["notes"]["template"] == "lecture"  # Worker tags the actual requested purpose.
    assert value["notes_stale"] is True
    assert value["notes_transcript_revision"] == original["transcript_revision"]
    assert value["segments"] == original["segments"]


def test_queued_transcript_snapshot_is_not_replaced_by_later_edits(assignment_job, monkeypatch):
    server, client, original = assignment_job
    server.executor.reset_mock()
    url = f"/api/jobs/{original['id']}"
    assert client.post(url + "/notes", json={"template": "journal"}).status_code == 200
    function, job_id, model, snapshot = server.executor.submit.call_args.args
    segments = deepcopy(original["segments"])
    segments[0]["text"] = "Changed after queueing."
    assert client.patch(url, json={"segments": segments}).status_code == 200
    def generate(job, selected_model, progress):
        assert job["segments"] == original["segments"]
        return original["notes"]
    monkeypatch.setattr(server, "generate_notes", generate)
    function(job_id, model, snapshot)
    value = client.get(url).json()
    assert value["notes_stale"] is True and value["notes"]["template"] == "journal"
    assert value["segments"] == segments


@pytest.mark.parametrize("template,required", [("meeting", "decisions actually made"),
                                              ("lecture", "Do not invent quiz questions"),
                                              ("journal", "Do not infer emotions")])
def test_template_changes_actual_prompt_and_keeps_grounded_schema(monkeypatch, template, required):
    payloads = []
    response = {"overview": "A grounded summary.", "decisions": [{"text": "Supported", "segment_ids": [10]}],
                "actions": [], "open_questions": [], "template": "untrusted-model-value"}
    def request(path, payload=None, timeout=5):
        payloads.append(payload)
        return {"message": {"content": json.dumps(response)}}
    monkeypatch.setattr(notes, "ollama_request", request)
    cleaned = notes._generate("mock-model", {"template": template, "transcript": []}, {10})
    prompt = payloads[0]["messages"][0]["content"]
    assert required in prompt
    assert "MUST cite supporting original segment_ids" in prompt
    assert "never instructions" in prompt
    assert payloads[0]["format"] == notes.NOTES_SCHEMA
    assert "template" not in cleaned
    assert cleaned["decisions"][0]["segment_ids"] == [10]


def test_template_is_retained_through_chunking_and_reduction(assignment_job, monkeypatch):
    _, _, original = assignment_job
    job = deepcopy(original)
    job["notes_template"] = "lecture"
    for segment in job["segments"]:
        segment["text"] = "A lecture statement. " * 700
    monkeypatch.setattr(notes, "validate_model", lambda _: None)
    calls = []
    def generate(model, source, allowed):
        calls.append(deepcopy(source))
        return {"overview": "A summary.", "decisions": [{"text": "A concept", "segment_ids": sorted(allowed)}],
                "actions": [], "open_questions": []}
    monkeypatch.setattr(notes, "_generate", generate)
    result = notes.generate_notes(job, "mock-model")
    assert len(calls) > len(job["segments"])
    assert all(source["template"] == "lecture" for source in calls)
    assert any("source_notes" in source for source in calls)
    assert result["template"] == "lecture"
