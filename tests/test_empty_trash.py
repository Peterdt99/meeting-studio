"""Permanent deletion checks against isolated synthetic recordings only."""
from copy import deepcopy
import json
from pathlib import Path
import stat
from types import SimpleNamespace
import uuid

import pytest

from test_server import api, ready_job


def _clone(server, source):
    job = deepcopy(source)
    job["id"] = uuid.uuid4().hex
    job.pop("deleted_at", None)
    job.pop("purge_started", None)
    server.jobs[job["id"]] = job
    server.save_job(job)
    (server.JOBS_DIR / job["id"] / "source.wav").write_bytes(b"independent synthetic audio")
    return job


def _trash(client, job_id):
    assert client.delete(f"/api/jobs/{job_id}").status_code == 200


def _empty(client, ids):
    response = client.post("/api/trash/empty", json={"ids": ids})
    assert response.status_code == 200, response.text
    assert set(response.json()) == {"deleted_ids", "failed_ids"}
    return response.json()


@pytest.mark.parametrize("payload", [None, {}, {"ids": []}, {"ids": "all"},
                                    {"ids": ["../recordings"]}, {"ids": ["g" * 32]}])
def test_empty_trash_requires_explicit_valid_id_list(ready_job, payload):
    server, client, original = ready_job
    job_id = original["id"]
    _trash(client, job_id)
    before = deepcopy(server.jobs[job_id])
    audio = server.JOBS_DIR / job_id / "source.wav"
    response = (client.post("/api/trash/empty") if payload is None
                else client.post("/api/trash/empty", json=payload))
    assert response.status_code in {400, 422}
    assert server.jobs[job_id] == before
    assert audio.read_bytes() == b"fixture audio bytes"


@pytest.mark.parametrize("invalid_tail", [["not-an-id"], ["b" * 32] * 10000])
def test_entire_list_is_validated_before_deleting_any_item(ready_job, invalid_tail):
    server, client, original = ready_job
    job_id = original["id"]
    _trash(client, job_id)
    before = deepcopy(server.jobs[job_id])
    metadata = server.JOBS_DIR / job_id / "job.json"
    original_bytes = metadata.read_bytes()
    response = client.post("/api/trash/empty", json={"ids": [job_id, *invalid_tail]})
    assert response.status_code in {400, 422}
    assert server.jobs[job_id] == before
    assert metadata.read_bytes() == original_bytes
    assert (metadata.parent / "source.wav").is_file()


def test_permanent_removal_deduplicates_and_cannot_resurrect_after_reload(ready_job):
    server, client, original = ready_job
    job_id = original["id"]
    directory = server.JOBS_DIR / job_id
    (directory / "review.txt").write_text("synthetic review text", encoding="utf-8")
    _trash(client, job_id)
    gone_id = uuid.uuid4().hex
    result = _empty(client, [job_id, job_id, gone_id, gone_id])
    assert result == {"deleted_ids": [job_id, gone_id], "failed_ids": []}
    assert not directory.exists()
    assert job_id not in server.jobs
    assert client.post(f"/api/trash/{job_id}/restore").status_code == 404
    server.jobs.clear()
    server.load_jobs()
    assert job_id not in server.jobs
    assert job_id not in {job["id"] for job in client.get("/api/trash").json()}
    assert job_id not in {job["id"] for job in client.get("/api/jobs").json()}
    assert _empty(client, [job_id]) == {"deleted_ids": [job_id], "failed_ids": []}


def test_only_requested_snapshot_ids_are_removed(ready_job):
    server, client, original = ready_job
    requested = original["id"]
    later = _clone(server, original)
    active = _clone(server, original)
    _trash(client, requested)
    snapshot = [requested]
    _trash(client, later["id"])
    model = server.MODELS_DIR / "synthetic-model-sentinel.bin"
    external = server.DATA_DIR / "synthetic-unrelated-sentinel.txt"
    model.write_bytes(b"model data")
    external.write_bytes(b"unrelated data")
    assert _empty(client, snapshot) == {"deleted_ids": snapshot, "failed_ids": []}
    assert (server.JOBS_DIR / later["id"] / "source.wav").read_bytes() == b"independent synthetic audio"
    assert (server.JOBS_DIR / active["id"] / "source.wav").read_bytes() == b"independent synthetic audio"
    assert server.get_job(later["id"], include_deleted=True)["deleted_at"]
    assert not server.get_job(active["id"]).get("deleted_at")
    assert model.read_bytes() == b"model data"
    assert external.read_bytes() == b"unrelated data"


def test_unknown_id_never_authorizes_deleting_an_untracked_directory(api):
    server, client = api
    unknown = uuid.uuid4().hex
    directory = server.JOBS_DIR / unknown
    directory.mkdir()
    sentinel = directory / "untracked.txt"
    sentinel.write_bytes(b"untracked data")
    assert unknown not in server.jobs
    assert _empty(client, [unknown]) == {"deleted_ids": [unknown], "failed_ids": []}
    assert sentinel.read_bytes() == b"untracked data"


@pytest.mark.parametrize("field,state", [("status", "queued"), ("status", "processing"),
                                         ("notes_status", "queued"), ("notes_status", "processing")])
def test_processing_items_fail_without_preventing_other_requested_deletions(ready_job, field, state):
    server, client, original = ready_job
    protected_id = original["id"]
    removable = _clone(server, original)
    _trash(client, protected_id)
    _trash(client, removable["id"])
    server.update_job(protected_id, **{field: state})
    before = deepcopy(server.jobs[protected_id])
    result = _empty(client, [protected_id, removable["id"]])
    assert result == {"deleted_ids": [removable["id"]], "failed_ids": [protected_id]}
    assert server.jobs[protected_id] == before
    assert (server.JOBS_DIR / protected_id / "source.wav").is_file()
    assert not (server.JOBS_DIR / removable["id"]).exists()


def test_item_restored_after_snapshot_is_not_permanently_removed(ready_job):
    server, client, original = ready_job
    job_id = original["id"]
    _trash(client, job_id)
    snapshot = [job_id]
    assert client.post(f"/api/trash/{job_id}/restore").status_code == 200
    before = deepcopy(server.jobs[job_id])
    assert _empty(client, snapshot) == {"deleted_ids": [], "failed_ids": [job_id]}
    assert server.jobs[job_id] == before
    assert (server.JOBS_DIR / job_id / "source.wav").is_file()


def test_partial_filesystem_failure_survives_reload_blocks_restore_and_allows_retry(ready_job, monkeypatch):
    server, client, original = ready_job
    job_id = original["id"]
    directory = server.JOBS_DIR / job_id
    metadata = directory / "job.json"
    _trash(client, job_id)
    real_unlink = Path.unlink
    def fail_metadata(path, *args, **kwargs):
        if path == metadata:
            raise PermissionError("Synthetic locked metadata")
        return real_unlink(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", fail_metadata)
        assert _empty(client, [job_id]) == {"deleted_ids": [], "failed_ids": [job_id]}
    assert not (directory / "source.wav").exists(), "Metadata must be removed after recording files"
    assert server.get_job(job_id, include_deleted=True)["purge_started"] is True
    assert json.loads(metadata.read_text(encoding="utf-8"))["purge_started"] is True
    assert client.post(f"/api/trash/{job_id}/restore").status_code == 409
    trash_item = next(job for job in client.get("/api/trash").json() if job["id"] == job_id)
    assert trash_item["purge_started"] is True
    assert "segments" not in trash_item and "speakers" not in trash_item
    server.jobs.clear()
    server.load_jobs()
    assert server.get_job(job_id, include_deleted=True)["purge_started"] is True
    assert client.post(f"/api/trash/{job_id}/restore").status_code == 409
    assert _empty(client, [job_id]) == {"deleted_ids": [job_id], "failed_ids": []}
    assert not directory.exists()


def test_empty_directory_remove_failure_does_not_resurrect_deleted_content(ready_job, monkeypatch):
    server, client, original = ready_job
    job_id = original["id"]
    directory = server.JOBS_DIR / job_id
    _trash(client, job_id)
    real_rmdir = Path.rmdir
    def fail_directory(path, *args, **kwargs):
        if path == directory:
            raise PermissionError("Synthetic locked empty recording directory")
        return real_rmdir(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "rmdir", fail_directory)
        assert _empty(client, [job_id]) == {"deleted_ids": [job_id], "failed_ids": []}
    assert directory.is_dir()
    assert list(directory.iterdir()) == []
    assert job_id not in server.jobs
    assert client.post(f"/api/trash/{job_id}/restore").status_code == 404
    server.jobs.clear()
    server.load_jobs()
    assert job_id not in server.jobs
    assert _empty(client, [job_id]) == {"deleted_ids": [job_id], "failed_ids": []}


def test_marker_save_failure_does_not_remove_any_files(ready_job, monkeypatch):
    server, client, original = ready_job
    job_id = original["id"]
    _trash(client, job_id)
    before = deepcopy(server.jobs[job_id])
    directory = server.JOBS_DIR / job_id
    metadata_bytes = (directory / "job.json").read_bytes()
    def fail_save(job):
        raise OSError("Synthetic failed purge marker save")
    with monkeypatch.context() as patch:
        patch.setattr(server, "save_job", fail_save)
        assert _empty(client, [job_id]) == {"deleted_ids": [], "failed_ids": [job_id]}
    assert server.jobs[job_id] == before
    assert (directory / "source.wav").read_bytes() == b"fixture audio bytes"
    assert (directory / "job.json").read_bytes() == metadata_bytes
    assert client.post(f"/api/trash/{job_id}/restore").status_code == 200


def test_nested_directory_is_rejected_before_deleting_files(ready_job):
    server, client, original = ready_job
    job_id = original["id"]
    _trash(client, job_id)
    directory = server.JOBS_DIR / job_id
    nested = directory / "unexpected-folder"
    nested.mkdir()
    sentinel = nested / "keep.txt"
    sentinel.write_bytes(b"nested unrelated data")
    before = deepcopy(server.jobs[job_id])
    assert _empty(client, [job_id]) == {"deleted_ids": [], "failed_ids": [job_id]}
    assert server.jobs[job_id] == before
    assert sentinel.read_bytes() == b"nested unrelated data"
    assert (directory / "source.wav").read_bytes() == b"fixture audio bytes"


def test_stale_metadata_temp_file_does_not_cause_a_false_purge_failure(ready_job):
    server, client, original = ready_job
    job_id = original["id"]
    _trash(client, job_id)
    directory = server.JOBS_DIR / job_id
    (directory / "job.json.tmp").write_bytes(b"synthetic interrupted metadata save")
    assert _empty(client, [job_id]) == {"deleted_ids": [job_id], "failed_ids": []}
    assert not directory.exists()


def test_windows_reparse_attribute_is_rejected_before_any_file_removal(ready_job, monkeypatch):
    server, client, original = ready_job
    job_id = original["id"]
    _trash(client, job_id)
    source = server.JOBS_DIR / job_id / "source.wav"
    before = deepcopy(server.jobs[job_id])
    real_lstat = Path.lstat
    def reparse_lstat(path, *args, **kwargs):
        result = real_lstat(path, *args, **kwargs)
        if path == source:
            return SimpleNamespace(st_mode=result.st_mode,
                                   st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
        return result
    with monkeypatch.context() as patch:
        patch.setattr(Path, "lstat", reparse_lstat)
        assert _empty(client, [job_id]) == {"deleted_ids": [], "failed_ids": [job_id]}
    assert server.jobs[job_id] == before
    assert source.read_bytes() == b"fixture audio bytes"


def test_symlink_inside_recording_is_rejected_without_touching_target(ready_job):
    server, client, original = ready_job
    job_id = original["id"]
    _trash(client, job_id)
    directory = server.JOBS_DIR / job_id
    external = server.DATA_DIR / ("outside-" + uuid.uuid4().hex + ".txt")
    external.write_bytes(b"outside data")
    link = directory / "unexpected-link.txt"
    try:
        link.symlink_to(external)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Creating a test symlink is unavailable: {exc}")
    try:
        before = deepcopy(server.jobs[job_id])
        assert _empty(client, [job_id]) == {"deleted_ids": [], "failed_ids": [job_id]}
        assert server.jobs[job_id] == before
        assert link.is_symlink()
        assert external.read_bytes() == b"outside data"
        assert (directory / "source.wav").read_bytes() == b"fixture audio bytes"
    finally:
        link.unlink(missing_ok=True)

