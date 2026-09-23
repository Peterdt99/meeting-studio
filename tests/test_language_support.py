"""Model-catalog, API and language-forwarding checks without real recordings."""
import builtins
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import uuid

from fastapi.testclient import TestClient
import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))
import audio_engine as engine
from languages import ACCEPTED_LANGUAGE_CODES, DEFAULT_LANGUAGE, LANGUAGE_NAMES, LANGUAGE_OPTIONS, SUPPORTED_LANGUAGE_CODES


@pytest.fixture(scope="module")
def language_api():
    data = HERE / ("language-support-state-" + uuid.uuid4().hex)
    prior = os.environ.get("MEETING_STUDIO_DATA")
    os.environ["MEETING_STUDIO_DATA"] = str(data)
    try:
        spec = importlib.util.spec_from_file_location("meeting_studio_language_support", APP / "server.py")
        server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)
        server.executor.shutdown(wait=False, cancel_futures=True)
        server.executor = Mock()
        server.speech_models_status = lambda: {"ready": True}
        server.ollama_status = lambda: {"available": False, "models": []}
        assert server.DATA_DIR == data.resolve()
        with TestClient(server.app, base_url="http://127.0.0.1:8765") as client:
            yield server, client
    finally:
        if prior is None:
            os.environ.pop("MEETING_STUDIO_DATA", None)
        else:
            os.environ["MEETING_STUDIO_DATA"] = prior
        if data.exists():
            assert data.resolve().parent == HERE
            assert data.name.startswith("language-support-state-")
            shutil.rmtree(data)


def test_catalog_exactly_matches_installed_small_model_tokens():
    model = APP / "data" / "models" / "faster-whisper-small"
    if not (model / "config.json").is_file() or not (model / "tokenizer.json").is_file():
        pytest.skip("Optional installed model metadata is absent; do not download it for tests")
    config = json.loads((model / "config.json").read_text(encoding="utf-8"))
    tokenizer = json.loads((model / "tokenizer.json").read_text(encoding="utf-8"))
    language_ids = set(config["lang_ids"])
    installed_codes = {token["content"][2:-2] for token in tokenizer["added_tokens"]
                       if token["id"] in language_ids}
    assert len(installed_codes) == 99
    assert SUPPORTED_LANGUAGE_CODES == installed_codes
    assert "yue" not in SUPPORTED_LANGUAGE_CODES, "Cantonese requires a newer model token"
    assert LANGUAGE_NAMES["ru"] == "Russian"
    assert LANGUAGE_NAMES["zh"] == "Chinese (Mandarin)"


def test_status_exposes_complete_catalog_before_setup_without_loading_models(language_api, monkeypatch):
    server, client = language_api
    monkeypatch.setattr(server, "speech_models_status", lambda: {"ready": False})
    original_import = builtins.__import__
    def no_model_imports(name, *args, **kwargs):
        if name.split(".")[0] in {"faster_whisper", "sherpa_onnx", "ctranslate2"}:
            raise AssertionError("The status catalog must not load speech runtimes")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_model_imports)
    response = client.get("/api/status")
    assert response.status_code == 200
    value = response.json()
    assert value["ready"] is False
    assert value["default_language"] == DEFAULT_LANGUAGE == "en"
    assert value["languages"] == LANGUAGE_OPTIONS
    codes = [language["code"] for language in value["languages"]]
    assert len(codes) == len(set(codes)) == 100
    assert set(codes) == ACCEPTED_LANGUAGE_CODES
    assert all(language["name"].strip() for language in value["languages"])


def test_every_offered_language_is_accepted_and_persisted_on_upload(language_api):
    server, client = language_api
    for language in sorted(ACCEPTED_LANGUAGE_CODES):
        server.executor.reset_mock()
        response = client.post("/api/jobs", data={"language": language}, files=[
            ("files", ("synthetic.wav", b"synthetic audio bytes", "audio/wav"))])
        assert response.status_code == 200, (language, response.text)
        job = response.json()["jobs"][0]
        assert job["requested_language"] == language
        assert server.get_job(job["id"])["requested_language"] == language
        persisted = json.loads((server.JOBS_DIR / job["id"] / "job.json").read_text(encoding="utf-8"))
        assert persisted["requested_language"] == language
        server.executor.submit.assert_called_once_with(server.transcribe_worker, job["id"])


def test_upload_still_defaults_to_english(language_api):
    _, client = language_api
    response = client.post("/api/jobs", files=[
        ("files", ("synthetic.wav", b"synthetic audio bytes", "audio/wav"))])
    assert response.status_code == 200
    assert response.json()["jobs"][0]["requested_language"] == "en"


@pytest.mark.parametrize("language", ["yue", "xx", "zh-CN", "Russian"])
def test_unsupported_codes_reject_before_saving_or_queueing(language_api, language):
    server, client = language_api
    server.executor.reset_mock()
    before_jobs = set(server.jobs)
    before_dirs = set(server.JOBS_DIR.iterdir())
    response = client.post("/api/jobs", data={"language": language}, files=[
        ("files", ("synthetic.wav", b"synthetic audio bytes", "audio/wav"))])
    assert response.status_code == 400
    assert "supported recording language" in response.json()["detail"]
    assert set(server.jobs) == before_jobs
    assert set(server.JOBS_DIR.iterdir()) == before_dirs
    server.executor.submit.assert_not_called()


@pytest.mark.parametrize("language,text", [("ru", "Привет, мир."), ("zh", "你好，世界。"),
                                            ("ja", "こんにちは。"), ("ar", "مرحبا بالعالم."),
                                            ("auto", "A synthetic example.")])
def test_engine_forwards_language_and_preserves_unicode(monkeypatch, language, text):
    monkeypatch.setattr(engine, "models_status", lambda _: {"ready": True})
    monkeypatch.setattr(engine, "decode_audio", lambda _: np.ones(engine.SAMPLE_RATE, dtype=np.float32) * .1)
    segment = SimpleNamespace(start=.1, end=.8, text=text,
                              words=[SimpleNamespace(start=.1, end=.8, word=text)])
    model = Mock()
    actual_language = "en" if language == "auto" else language
    model.transcribe.return_value = (iter([segment]), SimpleNamespace(language=actual_language))
    monkeypatch.setattr(engine, "_whisper_model", lambda _: model)
    result = engine.transcribe_audio(Path("unused.wav"), Path("unused-models"), language, 1)
    assert model.transcribe.call_args.kwargs["language"] == (None if language == "auto" else language)
    assert model.transcribe.call_args.kwargs["task"] == "transcribe"
    assert result["language"] == actual_language
    assert [segment["text"] for segment in result["segments"]] == [text]


@pytest.mark.parametrize("language", ["yue", "xx", "zh-CN"])
def test_engine_rejects_unsupported_language_before_loading_models(monkeypatch, language):
    status = Mock(side_effect=AssertionError("No model access for an invalid language"))
    monkeypatch.setattr(engine, "models_status", status)
    with pytest.raises(engine.AudioEngineError, match="supported recording language"):
        engine.transcribe_audio(Path("unused.wav"), Path("unused-models"), language, 1)
    status.assert_not_called()

