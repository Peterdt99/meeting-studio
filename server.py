"""Meeting Studio: a private, loopback-only recording workbench."""
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import copy
import json
import logging
import math
import os
import re
import stat
import threading
import time
import uuid
from urllib.parse import urlparse, quote
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator

from notes import DEFAULT_MODEL, generate_notes, ollama_status
from languages import ACCEPTED_LANGUAGE_CODES, DEFAULT_LANGUAGE, LANGUAGE_OPTIONS
from note_templates import DEFAULT_TEMPLATE, list_templates
from transcript_search import search_recordings

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("MEETING_STUDIO_DATA", str(APP_DIR / "data"))).resolve()
JOBS_DIR = DATA_DIR / "recordings"
MODELS_DIR = DATA_DIR / "models"
MAX_BYTES = 2 * 1024 ** 3
ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".mp4", ".flac", ".ogg", ".webm", ".aac", ".wma", ".aiff", ".aif", ".opus", ".3gp"}
jobs = {}
lock = threading.RLock()
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="meeting")
setup_state = {"state": "idle", "message": "Download the speech models once to get started.", "progress": 0}
status_cache = {"time": 0, "value": None}
logger = logging.getLogger("meeting-studio")


def now():
    return datetime.now(timezone.utc).isoformat()


def save_job(job):
    directory = JOBS_DIR / job["id"]
    directory.mkdir(parents=True, exist_ok=True)
    temp = directory / "job.json.tmp"
    temp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(directory / "job.json")


def update_job(job_id, **changes):
    with lock:
        job = copy.deepcopy(jobs[job_id])
        job.update(changes, updated_at=now())
        save_job(job)
        jobs[job_id] = job
        return copy.deepcopy(job)


def get_job(job_id, *, include_deleted=False):
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise HTTPException(404, "Recording not found")
    with lock:
        if job_id not in jobs or (jobs[job_id].get("deleted_at") and not include_deleted):
            raise HTTPException(404, "Recording not found")
        return copy.deepcopy(jobs[job_id])


def public_job(job, detail=True):
    value = {k: v for k, v in job.items() if k != "audio_file"}
    value.setdefault("notes_template", DEFAULT_TEMPLATE)
    if not detail:
        for k in ("segments", "notes", "speaker_turns"):
            value.pop(k, None)
    return value


def load_jobs():
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    with lock:
        for path in JOBS_DIR.glob("*/job.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
                if not re.fullmatch(r"[0-9a-f]{32}", str(job.get("id", ""))) or path.parent.name != job["id"]:
                    continue
                if job.get("status") in ("queued", "processing"):
                    job.update(status="failed", stage="Interrupted", error="Processing was interrupted. Use Retry to resume from the original recording.")
                if job.get("notes_status") in ("queued", "processing"):
                    job.update(notes_status="failed", notes_error="Notes were interrupted. Generate them again.")
                jobs[job["id"]] = job
                save_job(job)
            except (ValueError, OSError):
                logger.exception("Could not load recording metadata at %s", path)


def speech_models_status():
    from model_setup import models_status
    return models_status(MODELS_DIR)


@asynccontextmanager
async def lifespan(app):
    load_jobs()
    yield
    executor.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="Meeting Studio", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.middleware("http")
async def local_only(request: Request, call_next):
    hostname = request.url.hostname
    if hostname not in {"localhost", "127.0.0.1", "::1", "testserver"}:
        return JSONResponse({"detail": "Meeting Studio is available on this computer only."}, status_code=403)
    origin = request.headers.get("origin")
    if origin:
        try:
            parsed_origin = urlparse(origin)
            origin_allowed = (parsed_origin.hostname in {"localhost", "127.0.0.1", "::1"}
                              and parsed_origin.netloc == request.url.netloc)
        except ValueError:
            origin_allowed = False
        if not origin_allowed:
            return JSONResponse({"detail": "Requests must come from the local Meeting Studio page."}, status_code=403)
    if request.headers.get("sec-fetch-site") == "cross-site":
        return JSONResponse({"detail": "Cross-site requests are disabled."}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api") else "no-cache"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
    return response


@app.get("/api/status")
def status():
    with lock:
        if time.monotonic() - status_cache["time"] > 8 or status_cache["value"] is None:
            status_cache.update(time=time.monotonic(), value=ollama_status())
        ollama = copy.deepcopy(status_cache["value"])
        setup = copy.deepcopy(setup_state)
    models = speech_models_status()
    return {"app": "Meeting Studio", "version": "1.2.0", "ready": models["ready"],
            "models": models, "ollama": ollama, "setup": setup,
            "languages": LANGUAGE_OPTIONS, "default_language": DEFAULT_LANGUAGE}


@app.get("/api/note-templates")
def note_templates():
    return {"templates": list_templates(), "default": DEFAULT_TEMPLATE}


@app.get("/api/search")
def search(q: str = Query(min_length=1, max_length=200), limit: int = Query(default=50, ge=1, le=100),
           offset: int = Query(default=0, ge=0)):
    query = q.strip()
    if not query:
        raise HTTPException(400, "Enter a word or phrase to find in your recordings.")
    with lock:
        snapshot = [copy.deepcopy({key: job.get(key) for key in ("id", "title", "filename", "created_at", "status", "segments")})
                    for job in jobs.values() if not job.get("deleted_at") and job.get("status") == "complete"]
    return search_recordings(snapshot, query, limit, offset)


def setup_worker():
    from model_setup import setup_models
    def progress(message, amount):
        with lock:
            setup_state.update(message=message, progress=float(amount))
    try:
        setup_models(MODELS_DIR, progress)
        with lock:
            setup_state.update(state="complete", message="Speech models are ready. Recordings can now be processed offline.", progress=1)
    except Exception as exc:
        logger.exception("Model setup failed")
        with lock:
            setup_state.update(state="failed", message="The model download did not finish. Retry when connected.", error=str(exc))


@app.post("/api/setup")
def setup():
    with lock:
        if setup_state["state"] != "running":
            setup_state.clear()
            setup_state.update(state="running", message="Preparing model downloads", progress=0)
            threading.Thread(target=setup_worker, daemon=True).start()
        return copy.deepcopy(setup_state)


def transcribe_worker(job_id):
    from audio_engine import transcribe_audio
    job = get_job(job_id)
    update_job(job_id, status="processing", stage="Opening recording", progress=0, error=None)
    def progress(message, amount):
        update_job(job_id, stage=message, progress=max(0, min(1, float(amount))))
    try:
        result = transcribe_audio(JOBS_DIR / job_id / job["audio_file"], MODELS_DIR,
                                  job["requested_language"], job["num_speakers"], progress)
        if not isinstance(result.get("segments"), list):
            raise RuntimeError("The speech engine returned an invalid result.")
        update_job(job_id, **result, status="complete", stage="Ready for review", progress=1,
                   transcript_revision=1, notes_status="idle", notes_stale=False)
    except Exception as exc:
        logger.exception("Transcription failed for %s", job_id)
        update_job(job_id, status="failed", stage="Could not transcribe", error=str(exc), progress=0)


@app.get("/api/jobs")
def list_jobs():
    with lock:
        return [public_job(copy.deepcopy(j), False) for j in sorted(jobs.values(), key=lambda j: j["created_at"], reverse=True)
                if not j.get("deleted_at")]


@app.get("/api/trash")
def list_trash():
    with lock:
        fields = ("id", "title", "filename", "created_at", "deleted_at", "duration")
        return [{**{key: job.get(key) for key in fields},
                 **({"purge_started": True} if job.get("purge_started") else {})}
                for job in sorted((job for job in jobs.values() if job.get("deleted_at")),
                                  key=lambda job: job["deleted_at"], reverse=True)]


class EmptyTrashRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=10000)


def recording_files_to_purge(job_id):
    """Validate the entire flat recording folder before deleting any content."""
    root = JOBS_DIR.absolute()
    directory = root / job_id
    if root.resolve() != root or directory.resolve() != root / job_id:
        raise OSError("Recording storage points outside its expected folder.")
    if not directory.exists():
        return directory, []
    entries = [directory, *directory.iterdir()]
    for entry in entries:
        info = entry.lstat()
        if entry.is_symlink() or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise OSError("Linked recording files cannot be permanently removed.")
        if entry != directory and not stat.S_ISREG(info.st_mode):
            raise OSError("Unexpected folders in recording storage cannot be permanently removed.")
    return directory, [entry for entry in entries[1:] if entry.name != "job.json"]


@app.post("/api/trash/empty")
def empty_trash(options: EmptyTrashRequest):
    """Permanently remove only the confirmed snapshot of trashed recordings."""
    if any(not re.fullmatch(r"[0-9a-f]{32}", job_id) for job_id in options.ids):
        raise HTTPException(400, "Invalid recording identifier. Reload Trash and try again.")
    deleted_ids, failed_ids = [], []
    with lock:
        for job_id in dict.fromkeys(options.ids):
            job = jobs.get(job_id)
            if job is None:
                deleted_ids.append(job_id)  # A retry after a completed deletion.
                continue
            if not job.get("deleted_at") or job.get("status") in {"queued", "processing"} or job.get("notes_status") in {"queued", "processing"}:
                failed_ids.append(job_id)
                continue
            try:
                directory, files = recording_files_to_purge(job_id)
                if directory.exists():
                    # Keep metadata until last; interrupted deletion remains retryable
                    # after restart, and cannot restore partially removed audio.
                    if not job.get("purge_started"):
                        pending = {**job, "purge_started": True, "updated_at": now()}
                        save_job(pending)
                        jobs[job_id] = pending
                    for path in files:
                        path.unlink(missing_ok=True)
                    (directory / "job.json").unlink(missing_ok=True)
                    try:
                        directory.rmdir()
                    except OSError:
                        logger.warning("Could not remove empty recording folder %s", job_id)
                jobs.pop(job_id, None)
                deleted_ids.append(job_id)
            except OSError:
                logger.exception("Could not permanently remove recording %s", job_id)
                failed_ids.append(job_id)
    return {"deleted_ids": deleted_ids, "failed_ids": failed_ids}


@app.delete("/api/jobs/{job_id}")
def delete_recording(job_id: str):
    """Move a recording to recoverable Trash; keep its local audio and work."""
    with lock:
        job = get_job(job_id, include_deleted=True)
        if job.get("deleted_at"):
            return {"id": job_id, "deleted": True}
        if job.get("status") in {"queued", "processing"} or job.get("notes_status") in {"queued", "processing"}:
            raise HTTPException(409, "Wait for transcription and meeting notes to finish before deleting this recording.")
        job.update(deleted_at=now(), updated_at=now())
        # Commit before changing memory so a failed write keeps the item visible.
        save_job(job)
        jobs[job_id] = job
        return {"id": job_id, "deleted": True}


@app.post("/api/trash/{job_id}/restore")
def restore_recording(job_id: str):
    with lock:
        job = get_job(job_id, include_deleted=True)
        if job.get("purge_started"):
            raise HTTPException(409, "Permanent deletion has started. Empty Trash again to finish removing this recording.")
        if job.get("deleted_at"):
            job.update(deleted_at=None, updated_at=now())
            save_job(job)
            jobs[job_id] = job
        return public_job(job)


@app.post("/api/jobs")
async def upload_recordings(files: list[UploadFile] = File(...), language: str = Form(DEFAULT_LANGUAGE),
                            num_speakers: int = Form(0)):
    if not speech_models_status()["ready"]:
        raise HTTPException(409, "Download the speech models first.")
    if language not in ACCEPTED_LANGUAGE_CODES:
        raise HTTPException(400, "Choose a supported recording language or automatic language detection.")
    if not 0 <= num_speakers <= 12:
        raise HTTPException(400, "Choose Auto or between 1 and 12 speakers.")
    if not 1 <= len(files) <= 30:
        raise HTTPException(400, "Import between 1 and 30 recordings at a time.")
    prepared = []
    # Validate the entire batch before saving or submitting any jobs.
    for file in files:
        name = Path((file.filename or "recording.wav").replace("\\", "/")).name
        suffix = Path(name).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise HTTPException(400, f"Unsupported recording format: {suffix or 'no file extension'}")
        if file.size is not None and file.size > MAX_BYTES:
            raise HTTPException(413, "Each recording must be smaller than 2 GB.")
        prepared.append((file, name, suffix))
    created = []
    try:
        for file, name, suffix in prepared:
            job_id = uuid.uuid4().hex
            directory = JOBS_DIR / job_id
            directory.mkdir(parents=True)
            target = directory / ("source" + suffix)
            created.append((job_id, directory))
            size = 0
            with target.open("wb") as stream:
                while data := await file.read(1024 * 1024):
                    size += len(data)
                    if size > MAX_BYTES:
                        raise HTTPException(413, "Each recording must be smaller than 2 GB.")
                    stream.write(data)
            if not size:
                raise HTTPException(400, f"{name} is empty.")
            job = {"id": job_id, "title": Path(name).stem[:200], "filename": name[:250],
                   "audio_file": target.name, "created_at": now(), "updated_at": now(),
                   "status": "queued", "stage": "Waiting to transcribe", "progress": 0,
                   "requested_language": language, "num_speakers": num_speakers,
                   "speakers": [], "segments": [], "warnings": [], "notes_status": "idle",
                   "notes": None, "notes_template": DEFAULT_TEMPLATE, "notes_stale": False, "transcript_revision": 0}
            with lock:
                jobs[job_id] = job
                save_job(job)
    except Exception:
        # These are newly created, unpublished batch files; never touch existing recordings.
        for job_id, directory in created:
            with lock:
                jobs.pop(job_id, None)
            for path in directory.iterdir():
                if path.is_file():
                    path.unlink()
            directory.rmdir()
        raise
    for job_id, _ in created:
        executor.submit(transcribe_worker, job_id)
    return {"jobs": [public_job(get_job(job_id)) for job_id, _ in created]}


@app.get("/api/jobs/{job_id}")
def recording(job_id: str):
    return public_job(get_job(job_id))


@app.get("/api/jobs/{job_id}/audio")
def audio(job_id: str):
    job = get_job(job_id)
    filename = Path(job["audio_file"]).name
    path = JOBS_DIR / job_id / filename
    if not path.is_file():
        raise HTTPException(404, "The audio file is missing.")
    return FileResponse(path)


class Speaker(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)


class TextRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(max_length=20000)
    bold: bool = Field(default=False, strict=True)
    italic: bool = Field(default=False, strict=True)
    underline: bool = Field(default=False, strict=True)


class Segment(BaseModel):
    id: int = Field(ge=0)
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(ge=0, allow_inf_nan=False)
    speaker: str = Field(min_length=1, max_length=80)
    text: str = Field(max_length=20000)
    text_join_before: Literal["", " "] | None = None
    runs: list[TextRun] | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_runs(self):
        if self.runs is not None:
            if sum(len(run.text) for run in self.runs) > 20000:
                raise ValueError("Formatted text must not exceed 20,000 characters per transcript part.")
            if "".join(run.text for run in self.runs) != self.text:
                raise ValueError("Formatted text must exactly match the transcript part's text.")
        return self


class EditRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    speakers: list[Speaker] | None = Field(default=None, max_length=100)
    segments: list[Segment] | None = Field(default=None, max_length=100000)
    notes_template: Literal["meeting", "lecture", "journal"] | None = None


def notes_are_stale(job, selected_template=None, revision=None):
    if not job.get("notes"):
        return False
    selected = selected_template if selected_template is not None else job.get("notes_template", DEFAULT_TEMPLATE)
    current_revision = job.get("transcript_revision", 0) if revision is None else revision
    generated_revision = job.get("notes_transcript_revision")
    source_changed = (generated_revision != current_revision if generated_revision is not None
                      else bool(job.get("notes_stale")))
    return source_changed or job["notes"].get("template", DEFAULT_TEMPLATE) != selected


@app.patch("/api/jobs/{job_id}")
def edit(job_id: str, changes: EditRequest):
    with lock:
        job = get_job(job_id)
        if job["status"] != "complete":
            raise HTTPException(409, "Wait for transcription to finish before editing.")
        patch = changes.model_dump(exclude_none=True)
        speakers = patch.get("speakers", job["speakers"])
        speaker_ids = {s["id"] for s in speakers}
        if len(speaker_ids) != len(speakers):
            raise HTTPException(400, "Speaker identifiers must be unique.")
        segments = patch.get("segments", job["segments"])
        segment_ids = [s["id"] for s in segments]
        if len(set(segment_ids)) != len(segment_ids):
            raise HTTPException(400, "Transcript identifiers must be unique.")
        for s in segments:
            if s["end"] < s["start"] or s["speaker"] not in speaker_ids:
                raise HTTPException(400, "Each transcript line needs a valid time range and speaker.")
            if s["end"] > float(job.get("duration", s["end"])) + 1:
                raise HTTPException(400, "A transcript timestamp is beyond the recording.")
        if patch:
            source_changed = bool({"title", "speakers", "segments"} & patch.keys())
            revision = job.get("transcript_revision", 0) + int(source_changed)
            if source_changed:
                patch["transcript_revision"] = revision
            # Capture the known fresh revision of legacy notes before changing preference.
            if job.get("notes") and "notes_transcript_revision" not in job and not job.get("notes_stale"):
                patch["notes_transcript_revision"] = job.get("transcript_revision", 0)
            candidate = {**job, **patch}
            patch["notes_stale"] = (notes_are_stale(candidate, revision=revision)
                                    or source_changed and job.get("notes_status") in ("queued", "processing"))
            job = update_job(job_id, **patch)
        return public_job(job)


class NotesRequest(BaseModel):
    model: str = Field(default=DEFAULT_MODEL, min_length=1, max_length=120)
    template: Literal["meeting", "lecture", "journal"] = DEFAULT_TEMPLATE


def notes_worker(job_id, model, snapshot=None):
    snapshot = copy.deepcopy(snapshot) if snapshot is not None else get_job(job_id)
    revision = snapshot["transcript_revision"]
    template = snapshot.get("notes_template", DEFAULT_TEMPLATE)
    update_job(job_id, notes_status="processing", notes_stage="Preparing notes", notes_error=None)
    def progress(message, amount):
        update_job(job_id, notes_stage=message, notes_progress=amount)
    try:
        document = generate_notes(snapshot, model, progress)
        document = {**document, "template": template}
        with lock:
            current = get_job(job_id)
            update_job(job_id, notes=document, notes_status="complete", notes_stage="Draft ready for review",
                       notes_progress=1, notes_model=model, notes_generated_at=now(),
                       notes_transcript_revision=revision,
                       notes_stale=current["transcript_revision"] != revision or current.get("notes_template", DEFAULT_TEMPLATE) != template)
    except Exception as exc:
        logger.exception("Notes failed for %s", job_id)
        update_job(job_id, notes_status="failed", notes_error=str(exc), notes_stage="Could not draft notes")


@app.post("/api/jobs/{job_id}/notes")
def make_notes(job_id: str, options: NotesRequest):
    with lock:
        job = get_job(job_id)
        if job["status"] != "complete" or not any((s.get("text") or "").strip() for s in job["segments"]):
            raise HTTPException(409, "A completed speech transcript with some text is needed first.")
        if job.get("notes_status") in ("queued", "processing"):
            if job.get("notes_template", DEFAULT_TEMPLATE) != options.template:
                job = update_job(job_id, notes_template=options.template,
                                 notes_stale=notes_are_stale(job, options.template))
            return public_job(job)
        job = update_job(job_id, notes_status="queued", notes_stage="Waiting to draft notes", notes_progress=0, notes_error=None,
                         notes_template=options.template, notes_stale=notes_are_stale(job, options.template))
        executor.submit(notes_worker, job_id, options.model, copy.deepcopy(job))
        return public_job(job)


@app.post("/api/jobs/{job_id}/retry")
def retry(job_id: str):
    with lock:
        job = get_job(job_id)
        if job["status"] != "failed":
            raise HTTPException(409, "Only failed recordings can be retried.")
        if not speech_models_status()["ready"]:
            raise HTTPException(409, "Complete speech model setup first.")
        job = update_job(job_id, status="queued", stage="Waiting to retry", error=None, progress=0)
        executor.submit(transcribe_worker, job_id)
        return public_job(job)


@app.get("/api/jobs/{job_id}/export")
def export(job_id: str, format: str = "md"):
    from exports import render_markdown, render_docx
    job = get_job(job_id)
    if job["status"] != "complete":
        raise HTTPException(409, "Wait for the recording to finish.")
    stem = re.sub(r"[\x00-\x1f<>:\"/\\|?*]", "_", job["title"]).strip(" .") or "Meeting"
    if format == "md":
        body, media = render_markdown(job).encode("utf-8"), "text/markdown; charset=utf-8"
    elif format == "docx":
        body, media = render_docx(job), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif format == "json":
        body, media = json.dumps(public_job(job), indent=2, ensure_ascii=False).encode("utf-8"), "application/json"
    else:
        raise HTTPException(400, "Choose md, docx or json.")
    return Response(body, media_type=media, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(stem + '.' + format)}"})


@app.get("/")
def home():
    return FileResponse(APP_DIR / "static" / "index.html")


app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
