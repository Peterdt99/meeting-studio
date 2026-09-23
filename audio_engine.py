"""Local CPU transcription and speaker diarization; no recording leaves this PC."""
from __future__ import annotations

import math
import os
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Callable

from model_setup import model_paths, models_status, setup_models
from languages import ACCEPTED_LANGUAGE_CODES

SAMPLE_RATE = 16000
Progress = Callable[[str, float], None]
UNKNOWN = "UNKNOWN"
# Sherpa uses cosine-distance clustering: higher thresholds produce fewer clusters.
# Its generic 0.5 default fragments TitaNet voices across recording conditions.
# 0.8 retained distinct fixture speakers while reducing the reported fragmentation.
AUTO_CLUSTER_THRESHOLD = 0.8
AUTO_MIN_SPEAKER_SECONDS = 1.5
AUTO_MIN_SPEECH_FRACTION = 0.01


class AudioEngineError(RuntimeError):
    """Actionable errors that the interface can display directly."""


def _report(progress: Progress | None, message: str, value: float) -> None:
    if progress:
        progress(message, max(0.0, min(1.0, value)))


def decode_audio(audio_path: Path):
    """Decode the first audio stream to normalized mono float32 with bundled PyAV."""
    import av
    import numpy as np
    pieces = []
    try:
        with av.open(str(audio_path)) as container:
            if not container.streams.audio:
                raise AudioEngineError("This file has no audio track. Choose an audio recording or a video with sound.")
            resampler = av.AudioResampler(format="fltp", layout="mono", rate=SAMPLE_RATE)
            for frame in container.decode(audio=0):
                frame.pts = None
                for output in resampler.resample(frame):
                    pieces.append(output.to_ndarray().reshape(-1))
            for output in resampler.resample(None):
                pieces.append(output.to_ndarray().reshape(-1))
    except AudioEngineError:
        raise
    except Exception as exc:
        raise AudioEngineError(f"Could not read this recording. Try exporting a WAV or MP3 copy. Details: {exc}") from exc
    if not pieces:
        raise AudioEngineError("The recording contains no audio samples.")
    audio = np.concatenate(pieces).astype(np.float32, copy=False)
    if not np.isfinite(audio).all():
        raise AudioEngineError("The recording contains invalid audio samples. Export a new WAV copy and try again.")
    return np.ascontiguousarray(audio)


def _union_length(intervals: list[tuple[float, float]]) -> float:
    if not intervals:
        return 0.0
    ordered = sorted(intervals)
    left, right = ordered[0]
    total = 0.0
    for start, end in ordered[1:]:
        if start <= right:
            right = max(right, end)
        else:
            total += right - left
            left, right = start, end
    return total + right - left


def speaker_for_interval(start: float, end: float, turns: list[dict]) -> str:
    """Assign only when the word substantially overlaps one unambiguous speaker."""
    if end <= start:
        start, end = max(0.0, start - 0.02), start + 0.02
    duration = end - start
    overlaps = defaultdict(list)
    for turn in turns:
        left, right = max(start, turn["start"]), min(end, turn["end"])
        if right > left:
            overlaps[turn["speaker"]].append((left, right))
    scores = sorted(((_union_length(intervals), speaker) for speaker, intervals in overlaps.items()), reverse=True)
    if not scores or scores[0][0] / duration < 0.35:
        return UNKNOWN
    if len(scores) > 1 and (scores[0][0] - scores[1][0]) / duration < 0.15:
        return UNKNOWN
    return scores[0][1]


def align_words_to_speakers(asr_segments: list[dict], turns: list[dict], duration: float) -> list[dict]:
    """Split ASR phrases at detected speaker changes without inventing word times."""
    valid_turns = sorted([t for t in turns if t["end"] > t["start"]], key=lambda t: t["start"])
    result = []
    cursor = 0
    for segment in asr_segments:
        words = segment.get("words") or [{"start": segment["start"], "end": segment["end"], "word": segment["text"]}]
        current = None
        for word in words:
            text = str(word.get("word", ""))
            if not text.strip():
                continue
            start = max(0.0, min(duration, float(word["start"])))
            end = max(start, min(duration, float(word["end"])))
            # The list is ordered in normal ASR output; retain only overlapping candidates.
            while cursor < len(valid_turns) and valid_turns[cursor]["end"] < start - 0.02:
                cursor += 1
            candidates = []
            for turn_index in range(cursor, len(valid_turns)):
                turn = valid_turns[turn_index]
                if turn["start"] > end + 0.02:
                    break
                candidates.append(turn)
            speaker = speaker_for_interval(start, end, candidates)
            if (current is None or current["speaker"] != speaker or start - current["end"] > 1.0
                    or end - current["start"] > 25.0 or len(current["text"]) > 500):
                if current:
                    current["text"] = current["text"].strip()
                    result.append(current)
                current = {"start": start, "end": end, "speaker": speaker, "text": text}
            else:
                current["end"] = max(current["end"], end)
                current["text"] += text
        if current:
            current["text"] = current["text"].strip()
            result.append(current)
    for i, segment in enumerate(result):
        segment["id"] = i
        segment["start"] = round(segment["start"], 3)
        segment["end"] = round(segment["end"], 3)
    return result


@lru_cache(maxsize=1)
def _whisper_model(path: str):
    from faster_whisper import WhisperModel
    return WhisperModel(path, device="cpu", compute_type="int8", cpu_threads=min(8, max(1, (os.cpu_count() or 2) // 2)),
                        num_workers=1, local_files_only=True)


def _stabilize_auto_speakers(turns: list[dict]) -> list[dict]:
    """Do not count a very brief, isolated voice fragment as another participant.

    This is an evidence floor, not a claim that the fragment belongs to somebody
    else. Short contributions in short clips are retained. Weak fragments remain
    UNKNOWN for review, and supported speaker IDs follow first appearance.
    """
    intervals = defaultdict(list)
    for turn in turns:
        intervals[turn["speaker"]].append((turn["start"], turn["end"]))
    total_speech = _union_length([(t["start"], t["end"]) for t in turns])
    if total_speech <= 0:
        return turns
    unsupported = set()
    for speaker, spans in intervals.items():
        support = _union_length(spans)
        if support < AUTO_MIN_SPEAKER_SECONDS and support / total_speech < AUTO_MIN_SPEECH_FRACTION:
            unsupported.add(speaker)
    labels = {}
    result = []
    for turn in turns:
        original = turn["speaker"]
        if original in unsupported or original == UNKNOWN:
            speaker = UNKNOWN
        else:
            if original not in labels:
                labels[original] = f"SPEAKER_{len(labels):02d}"
            speaker = labels[original]
        result.append({**turn, "speaker": speaker})
    return result


def _diarize(audio, paths: dict[str, Path], num_speakers: int, progress: Progress | None) -> list[dict]:
    import sherpa_onnx
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(paths["segmentation"])),
            num_threads=2, provider="cpu"),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(paths["embedding"]), num_threads=2, provider="cpu"),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=num_speakers if num_speakers > 0 else -1,
                                                  threshold=AUTO_CLUSTER_THRESHOLD),
        min_duration_on=0.3, min_duration_off=0.5,
    )
    if not config.validate():
        raise AudioEngineError("The speaker models could not be validated. Run model setup again before processing recordings.")
    diarizer = sherpa_onnx.OfflineSpeakerDiarization(config)
    if diarizer.sample_rate != SAMPLE_RATE:
        raise AudioEngineError("The speaker model expects a different audio sample rate. Reinstall the supported models.")
    def callback(done: int, total: int) -> int:
        _report(progress, "Finding speaker turns", 0.08 + 0.32 * done / max(1, total))
        return 0
    result = diarizer.process(audio, callback=callback).sort_by_start_time()
    labels = {}
    turns = []
    for turn in result:
        raw_speaker = int(turn.speaker)
        if raw_speaker < 0 or not (math.isfinite(turn.start) and math.isfinite(turn.end)) or turn.end <= turn.start:
            continue
        if raw_speaker not in labels:
            labels[raw_speaker] = f"SPEAKER_{len(labels):02d}"
        turns.append({"start": float(turn.start), "end": float(turn.end), "speaker": labels[raw_speaker]})
    return _stabilize_auto_speakers(turns) if num_speakers == 0 else turns


def transcribe_audio(audio_path: Path, models_dir: Path, language: str = "en", num_speakers: int = 0,
                     progress: Progress | None = None) -> dict:
    """Transcribe and diarize on the CPU. Speaker names are anonymous, per recording."""
    language = (language or "en").lower()
    if language not in ACCEPTED_LANGUAGE_CODES:
        raise AudioEngineError("Choose a supported recording language or automatic language detection.")
    if not 0 <= num_speakers <= 30:
        raise AudioEngineError("Speaker count must be automatic (0) or between 1 and 30.")
    status = models_status(models_dir)
    if not status["ready"]:
        raise AudioEngineError("Local models are missing. Select Set up models first: " + ", ".join(status["missing"]))
    _report(progress, "Reading audio", 0.01)
    audio = decode_audio(Path(audio_path))
    duration = len(audio) / SAMPLE_RATE
    if duration < 0.3:
        raise AudioEngineError("The recording is too short. Choose a recording at least one second long.")
    import numpy as np
    if float(np.max(np.abs(audio))) < 0.00001:
        _report(progress, "No audible speech detected", 1.0)
        return {"language": language if language != "auto" else "unknown", "duration": duration,
                "segments": [], "speakers": [], "warnings": ["The recording is silent; no speech or speakers were identified."]}
    paths = model_paths(models_dir)
    single_speaker = num_speakers == 1
    if single_speaker:
        # The user's known count is authoritative; do not cluster their voice.
        _report(progress, "Using one speaker for this recording", 0.06)
        turns = [{"start": 0.0, "end": duration, "speaker": "SPEAKER_00"}]
    else:
        _report(progress, "Loading speaker models", 0.06)
        try:
            turns = _diarize(audio, paths, num_speakers, progress)
        except AudioEngineError:
            raise
        except Exception as exc:
            raise AudioEngineError(f"Speaker identification failed. Check that local models are installed, and try automatic speaker count. Details: {exc}") from exc
    _report(progress, "Transcribing speech on this computer", 0.42)
    try:
        model = _whisper_model(str(paths["whisper"]))
        generated, info = model.transcribe(audio, language=None if language == "auto" else language,
                                          task="transcribe", beam_size=5, word_timestamps=True,
                                          vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
                                          condition_on_previous_text=False)
        asr = []
        for segment in generated:
            asr.append({"start": float(segment.start), "end": float(segment.end), "text": segment.text,
                        "words": [{"start": float(w.start), "end": float(w.end), "word": w.word} for w in (segment.words or [])]})
            _report(progress, "Transcribing speech on this computer", 0.42 + 0.53 * min(1.0, segment.end / max(duration, 0.1)))
    except Exception as exc:
        raise AudioEngineError(f"Speech recognition failed. Check available memory and the local model setup. Details: {exc}") from exc
    if asr and not turns:
        raise AudioEngineError("Speech was transcribed, but the speaker model found no speaker turns. Try a clearer recording or rerun model setup; no speaker labels were invented.")
    _report(progress, "Applying the single speaker label" if single_speaker else "Matching words to speaker turns", 0.97)
    segments = align_words_to_speakers(asr, turns, duration)
    if single_speaker:
        # Include ambiguous/zero-length word timestamps in the user's one label.
        for segment in segments:
            segment["speaker"] = "SPEAKER_00"
    present = list(dict.fromkeys(s["speaker"] for s in segments))
    speakers = [{"id": speaker, "name": "Unassigned" if speaker == UNKNOWN else f"Speaker {int(speaker.rsplit('_', 1)[-1]) + 1}"} for speaker in present]
    warnings = (["You selected one speaker. All recognized speech uses the same speaker label; review the transcript and add a name."]
                if single_speaker else
                ["Speaker labels are automatic and apply only within this recording. Review and rename them before sharing.",
                 "Overlapping voices are not reliably separated; unclear speaker matches are marked Unassigned."])
    if num_speakers == 0 and any(t["speaker"] == UNKNOWN for t in turns):
        warnings.append("A very brief voice fragment had too little evidence to count as another speaker and was left Unassigned. Review it; a genuine short interjection may need a speaker label.")
    if not segments:
        warnings.append("No speech was recognized in this recording.")
    if UNKNOWN in present:
        warnings.append("Some words could not be confidently matched to a speaker. Review the Unassigned segments.")
    if language == "auto":
        warnings.append("Automatic language detection chooses one primary language for this recording; choose a language manually if it is wrong.")
    _report(progress, "Transcript ready", 1.0)
    return {"language": info.language, "duration": round(duration, 3), "segments": segments, "speakers": speakers, "warnings": warnings}
