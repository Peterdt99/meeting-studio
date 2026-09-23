"""Recoverable deletion tests using only isolated synthetic recording data."""
from copy import deepcopy
import json
import uuid

import pytest

# These fixtures import the app with a unique MEETING_STUDIO_DATA directory and
# replace all background processing and Ollama access with inert test doubles.
from test_server import api, ready_job


def test_delete_restore_preserves_recording_and_review_work(ready_job):
    server, client, original = ready_job
    job_id = original["id"]
    directory = server.JOBS_DIR / job_id
    original_files = set(directory.iterdir())
    audio_bytes = (directory / "source.wav").read_bytes()

    response = client.delete(f"/api/jobs/{job_id}")
    assert response.status_code == 200
    assert response.json() == {"id": job_id, "deleted": True}
    assert job_id not in {job["id"] for job in client.get("/api/jobs").json()}
    trashed = next(job for job in client.get("/api/trash").json() if job["id"] == job_id)
    assert set(trashed) == {"id", "title", "filename", "created_at", "deleted_at", "duration"}
    assert trashed["deleted_at"]
    assert set(directory.iterdir()) == original_files
    assert (directory / "source.wav").read_bytes() == audio_bytes

    persisted = json.loads((directory / "job.json").read_text(encoding="utf-8"))
    for key in ("audio_file", "segments", "speakers", "notes", "transcript_revision", "notes_stale"):
        assert persisted[key] == original[key]
    assert persisted["deleted_at"] == trashed["deleted_at"]

    response = client.post(f"/api/trash/{job_id}/restore")
    assert response.status_code == 200
    restored = response.json()
    assert "audio_file" not in restored
    assert not restored.get("deleted_at")
    for key in ("segments", "speakers", "notes", "transcript_revision", "notes_stale"):
        assert restored[key] == original[key]
    assert job_id in {job["id"] for job in client.get("/api/jobs").json()}
    assert job_id not in {job["id"] for job in client.get("/api/trash").json()}
    assert client.get(f"/api/jobs/{job_id}/audio").content == audio_bytes
    assert not json.loads((directory / "job.json").read_text(encoding="utf-8")).get("deleted_at")
    server.executor.submit.assert_not_called()


def test_trash_survives_reload_and_remains_recoverable(ready_job):
    server, client, original = ready_job
    job_id = original["id"]
    assert client.delete(f"/api/jobs/{job_id}").status_code == 200
    deletion_time = server.get_job(job_id, include_deleted=True)["deleted_at"]
    with server.lock:
        server.jobs.clear()
    server.load_jobs()
    assert client.get(f"/api/jobs/{job_id}").status_code == 404
    assert server.get_job(job_id, include_deleted=True)["deleted_at"] == deletion_time
    assert job_id not in {job["id"] for job in client.get("/api/jobs").json()}
    assert job_id in {job["id"] for job in client.get("/api/trash").json()}
    response = client.post(f"/api/trash/{job_id}/restore")
    assert response.status_code == 200
    assert response.json()["segments"] == original["segments"]
    assert response.json()["speakers"] == original["speakers"]
    assert response.json()["notes"] == original["notes"]


def test_delete_and_restore_are_idempotent(ready_job):
    server, client, original = ready_job
    job_id = original["id"]
    assert client.delete(f"/api/jobs/{job_id}").status_code == 200
    first_deleted = server.get_job(job_id, include_deleted=True)
    assert client.delete(f"/api/jobs/{job_id}").status_code == 200
    assert server.get_job(job_id, include_deleted=True) == first_deleted
    first_restore = client.post(f"/api/trash/{job_id}/restore")
    second_restore = client.post(f"/api/trash/{job_id}/restore")
    assert first_restore.status_code == second_restore.status_code == 200
    assert first_restore.json() == second_restore.json()


@pytest.mark.parametrize("field,state", [
    ("status", "queued"), ("status", "processing"),
    ("notes_status", "queued"), ("notes_status", "processing"),
])
def test_active_work_cannot_be_deleted(ready_job, field, state):
    server, client, original = ready_job
    job_id = original["id"]
    server.update_job(job_id, **{field: state})
    before = deepcopy(server.jobs[job_id])
    metadata = server.JOBS_DIR / job_id / "job.json"
    before_disk = metadata.read_bytes()
    response = client.delete(f"/api/jobs/{job_id}")
    assert response.status_code == 409
    assert server.jobs[job_id] == before
    assert metadata.read_bytes() == before_disk
    assert job_id in {job["id"] for job in client.get("/api/jobs").json()}
    assert job_id not in {job["id"] for job in client.get("/api/trash").json()}


def test_trashed_recording_is_hidden_from_content_and_edit_routes(ready_job):
    server, client, original = ready_job
    job_id = original["id"]
    assert client.delete(f"/api/jobs/{job_id}").status_code == 200
    before = deepcopy(server.get_job(job_id, include_deleted=True))
    requests = [
        ("GET", f"/api/jobs/{job_id}", {}),
        ("GET", f"/api/jobs/{job_id}/audio", {}),
        ("GET", f"/api/jobs/{job_id}/export?format=md", {}),
        ("GET", f"/api/jobs/{job_id}/export?format=json", {}),
        ("PATCH", f"/api/jobs/{job_id}", {"json": {"title": "Changed"}}),
        ("POST", f"/api/jobs/{job_id}/notes", {"json": {"model": "mock-model"}}),
        ("POST", f"/api/jobs/{job_id}/retry", {}),
    ]
    for method, path, kwargs in requests:
        assert client.request(method, path, **kwargs).status_code == 404, (method, path)
    assert server.get_job(job_id, include_deleted=True) == before
    server.executor.submit.assert_not_called()


@pytest.mark.parametrize("job_id", ["not-an-id", "a" * 31, "g" * 32, uuid.uuid4().hex])
def test_unknown_or_malformed_id_cannot_delete_or_restore(api, job_id):
    server, client = api
    before = deepcopy(server.jobs)
    assert client.delete(f"/api/jobs/{job_id}").status_code == 404
    assert client.post(f"/api/trash/{job_id}/restore").status_code == 404
    assert server.jobs == before


@pytest.mark.parametrize("operation", ["delete", "restore"])
def test_failed_metadata_save_does_not_change_in_memory_visibility(ready_job, monkeypatch, operation):
    server, client, original = ready_job
    job_id = original["id"]
    if operation == "restore":
        assert client.delete(f"/api/jobs/{job_id}").status_code == 200
    before = deepcopy(server.jobs[job_id])
    metadata = server.JOBS_DIR / job_id / "job.json"
    before_disk = metadata.read_bytes()
    def fail_save(job):
        raise OSError("Synthetic storage failure")
    monkeypatch.setattr(server, "save_job", fail_save)
    response = (client.delete(f"/api/jobs/{job_id}") if operation == "delete"
                else client.post(f"/api/trash/{job_id}/restore"))
    assert response.status_code >= 500
    assert server.jobs[job_id] == before
    assert metadata.read_bytes() == before_disk
    active_ids = {job["id"] for job in client.get("/api/jobs").json()}
    trash_ids = {job["id"] for job in client.get("/api/trash").json()}
    assert (job_id in active_ids) == (operation == "delete")
    assert (job_id in trash_ids) == (operation == "restore")

