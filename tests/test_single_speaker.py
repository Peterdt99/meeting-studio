"""Regression checks for the explicit single-speaker mode."""
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
import audio_engine as engine


@pytest.fixture
def audio_setup(monkeypatch):
    monkeypatch.setattr(engine, "models_status", lambda _: {"ready": True})
    monkeypatch.setattr(engine, "decode_audio", lambda _: np.ones(4 * engine.SAMPLE_RATE, dtype=np.float32) * 0.1)
    # Cover a silence gap and a zero-length final word at the recording boundary.
    words = [SimpleNamespace(start=0.1, end=0.8, word=" Hello."),
             SimpleNamespace(start=2.0, end=2.8, word=" Still me."),
             SimpleNamespace(start=4.0, end=4.0, word=" Goodbye.")]
    speech = [SimpleNamespace(start=0.1, end=4.0, text=" Hello. Still me. Goodbye.", words=words)]
    model = Mock()
    model.transcribe.return_value = (iter(speech), SimpleNamespace(language="en"))
    monkeypatch.setattr(engine, "_whisper_model", lambda _: model)
    diarize = Mock(side_effect=AssertionError("Voice splitting must not run for one speaker"))
    monkeypatch.setattr(engine, "_diarize", diarize)
    return model, diarize


def test_one_speaker_skips_clustering_and_keeps_every_word(audio_setup):
    _, diarize = audio_setup
    result = engine.transcribe_audio(Path("unused.wav"), Path("unused-models"), "en", 1)
    diarize.assert_not_called()
    assert result["speakers"] == [{"id": "SPEAKER_00", "name": "Speaker 1"}]
    assert {s["speaker"] for s in result["segments"]} == {"SPEAKER_00"}
    assert " ".join(s["text"] for s in result["segments"]) == "Hello. Still me. Goodbye."
    assert [(s["start"], s["end"]) for s in result["segments"]] == [(0.1, 0.8), (2.0, 2.8), (4.0, 4.0)]
    assert not any("Unassigned" in warning or "Overlapping" in warning for warning in result["warnings"])


def test_no_recognized_speech_does_not_invent_a_speaker(audio_setup):
    model, diarize = audio_setup
    model.transcribe.return_value = (iter([]), SimpleNamespace(language="en"))
    result = engine.transcribe_audio(Path("unused.wav"), Path("unused-models"), "en", 1)
    assert result["segments"] == []
    assert result["speakers"] == []
    diarize.assert_not_called()


@pytest.mark.parametrize("count", [0, 2])
def test_auto_and_multiple_speakers_still_use_voice_detection(audio_setup, count):
    _, diarize = audio_setup
    diarize.side_effect = None
    diarize.return_value = [{"start": 0, "end": 1, "speaker": "SPEAKER_00"},
                           {"start": 1.9, "end": 4, "speaker": "SPEAKER_01"}]
    result = engine.transcribe_audio(Path("unused.wav"), Path("unused-models"), "en", count)
    assert diarize.call_count == 1
    assert diarize.call_args.args[2] == count
    assert {s["speaker"] for s in result["segments"]} >= {"SPEAKER_00", "SPEAKER_01"}

