"""Passage text/formatting regressions using isolated synthetic API fixtures."""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from test_speaker_assignment import assignment_api, assignment_job
import notes


def run(text, **styles):
    return {"text": text, "bold": False, "italic": False, "underline": False, **styles}


def rich_segments(original):
    segments = deepcopy(original["segments"])
    fragments = [
        [run("  Привет 👋", bold=True), run("\n")],
        [run("新しい予定：", italic=True, underline=True), run("\n")],
        [run("Meet at 10:00.  ", bold=True, italic=True, underline=True)],
    ]
    for segment, runs in zip(segments, fragments):
        segment.update(text="".join(r["text"] for r in runs), runs=runs, text_join_before="")
    return segments


def test_passage_edit_preserves_unicode_newlines_reference_ids_and_formatting(assignment_job):
    server, client, original = assignment_job
    segments = rich_segments(original)
    response = client.patch(f"/api/jobs/{original['id']}", json={"segments": segments})
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["segments"] == segments
    identity = lambda rows: [(s["id"], s["start"], s["end"], s["speaker"]) for s in rows]
    assert identity(saved["segments"]) == identity(original["segments"])
    assert saved["segments"][3:] == original["segments"][3:]
    assert saved["transcript_revision"] == original["transcript_revision"] + 1
    assert saved["notes_stale"] is True
    assert saved["notes"] == original["notes"]
    assert saved["speakers"] == original["speakers"]
    server.jobs.clear()
    server.load_jobs()
    assert client.get(f"/api/jobs/{original['id']}").json() == saved
    exported = client.get(f"/api/jobs/{original['id']}/export?format=json")
    assert exported.status_code == 200
    assert exported.json() == saved


@pytest.mark.parametrize("metadata", [{}, {"runs": None, "text_join_before": None}])
def test_absent_or_null_formatting_remains_backward_compatible(assignment_job, metadata):
    _, client, original = assignment_job
    segments = [{**s, **metadata} for s in original["segments"]]
    response = client.patch(f"/api/jobs/{original['id']}", json={"segments": segments})
    assert response.status_code == 200
    assert response.json()["segments"] == original["segments"]


def test_plain_text_replacement_can_remove_previous_formatting(assignment_job):
    _, client, original = assignment_job
    url = f"/api/jobs/{original['id']}"
    assert client.patch(url, json={"segments": rich_segments(original)}).status_code == 200
    response = client.patch(url, json={"segments": original["segments"]})
    assert response.status_code == 200
    assert response.json()["segments"] == original["segments"]
    assert response.json()["transcript_revision"] == original["transcript_revision"] + 2


@pytest.mark.parametrize("modify", [
    lambda s: s.update(runs=[run("Different content")]),
    lambda s: s.update(runs=[run(s["text"] + " ")]),
    lambda s: s.update(runs=[run(s["text"], html="<b>unsafe metadata</b>")]),
    lambda s: s.update(runs=[run(s["text"], link="javascript:alert(1)")]),
    lambda s: s.update(runs=[run(s["text"], bold="true")]),
    lambda s: s.update(text_join_before="\n"),
    lambda s: s.update(text_join_before="<br>"),
    lambda s: s.update(text_join_before=1),
    lambda s: s.update(runs=[run(42)]),
    lambda s: s.update(runs=[]),
])
def test_invalid_formatting_is_rejected_without_any_mutation(assignment_job, modify):
    server, client, original = assignment_job
    metadata = server.JOBS_DIR / original["id"] / "job.json"
    before = metadata.read_bytes()
    segments = deepcopy(original["segments"])
    modify(segments[1])
    response = client.patch(f"/api/jobs/{original['id']}", json={"segments": segments})
    assert response.status_code == 422
    assert server.get_job(original["id"]) == original
    assert metadata.read_bytes() == before


@pytest.mark.parametrize("oversized", ["run_list", "one_run", "combined_runs"])
def test_formatting_limits_reject_excessive_payloads(assignment_job, oversized):
    server, client, original = assignment_job
    segments = deepcopy(original["segments"])
    if oversized == "run_list":
        segments[0].update(text="", runs=[run("")] * 2001)
    elif oversized == "one_run":
        segments[0]["runs"] = [run("x" * 20001)]
    else:
        segments[0]["runs"] = [run("x" * 10001), run("y" * 10000)]
    response = client.patch(f"/api/jobs/{original['id']}", json={"segments": segments})
    assert response.status_code == 422
    assert server.get_job(original["id"]) == original


def test_valid_formatting_defaults_and_explicit_space_join_are_preserved(assignment_job):
    _, client, original = assignment_job
    segments = deepcopy(original["segments"])
    segments[0].update(text="<b>literal</b>\n café", runs=[{"text": "<b>literal</b>\n café"}], text_join_before=" ")
    response = client.patch(f"/api/jobs/{original['id']}", json={"segments": segments})
    assert response.status_code == 200
    saved = response.json()["segments"][0]
    assert saved["text"] == "<b>literal</b>\n café"
    assert saved["runs"] == [run(saved["text"])]
    assert saved["text_join_before"] == " "


@pytest.mark.parametrize("empty_text", ["", " \n\t "])
def test_clearing_passage_preserves_segments_but_blocks_note_generation(assignment_job, empty_text):
    server, client, original = assignment_job
    server.executor.reset_mock()
    segments = [{**s, "text": empty_text, "runs": [] if not empty_text else [run(empty_text)],
                 "text_join_before": ""} for s in original["segments"]]
    url = f"/api/jobs/{original['id']}"
    edited = client.patch(url, json={"segments": segments})
    assert edited.status_code == 200
    assert edited.json()["segments"] == segments
    assert edited.json()["notes_stale"] is True
    before_notes = deepcopy(server.get_job(original["id"]))
    metadata = server.JOBS_DIR / original["id"] / "job.json"
    disk_before = metadata.read_bytes()
    response = client.post(url + "/notes", json={"model": "unused-model"})
    assert response.status_code == 409
    assert server.get_job(original["id"]) == before_notes
    assert metadata.read_bytes() == disk_before
    server.executor.submit.assert_not_called()


def test_notes_use_canonical_text_and_original_ids_without_formatting(assignment_job, monkeypatch):
    _, _, original = assignment_job
    job = deepcopy(original)
    job["segments"] = rich_segments(original)
    monkeypatch.setattr(notes, "validate_model", lambda _: None)
    generated = Mock(return_value=original["notes"])
    monkeypatch.setattr(notes, "_generate", generated)
    assert notes.generate_notes(job, "unused-model") == original["notes"]
    generated.assert_called_once()
    _, source, allowed_ids = generated.call_args.args
    assert allowed_ids == {s["id"] for s in original["segments"]}
    assert [row["segment_id"] for row in source["transcript"]] == [s["id"] for s in original["segments"]]
    assert [row["text"] for row in source["transcript"]] == [s["text"] for s in job["segments"]]
    assert all("runs" not in row for row in source["transcript"])
    assert "\\n" in json.dumps(source, ensure_ascii=False)


def test_empty_direct_notes_request_never_contacts_ollama(assignment_job, monkeypatch):
    _, _, original = assignment_job
    job = deepcopy(original)
    for segment in job["segments"]:
        segment["text"] = " \n\t"
    validate = Mock(side_effect=AssertionError("Must not contact Ollama"))
    monkeypatch.setattr(notes, "validate_model", validate)
    with pytest.raises(ValueError, match="no speech transcript"):
        notes.generate_notes(job, "unused-model")
    validate.assert_not_called()
