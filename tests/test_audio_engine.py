"""Meaningful time-alignment and decoder checks; no model downloads needed."""
import math
from pathlib import Path
import struct
import sys
import unittest
import wave

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from audio_engine import UNKNOWN, align_words_to_speakers, decode_audio, speaker_for_interval
from model_setup import models_status


class AlignmentTests(unittest.TestCase):
    def test_split_phrase_at_speaker_change_preserves_all_words(self):
        phrase = [{"start": 0.0, "end": 2.0, "text": " Hello there. Good morning.",
                   "words": [{"start": 0.0, "end": .4, "word": " Hello"},
                             {"start": .4, "end": .9, "word": " there."},
                             {"start": 1.1, "end": 1.5, "word": " Good"},
                             {"start": 1.5, "end": 2.0, "word": " morning."}]}]
        turns = [{"start": 0, "end": 1, "speaker": "SPEAKER_00"},
                 {"start": 1, "end": 2.1, "speaker": "SPEAKER_01"}]
        result = align_words_to_speakers(phrase, turns, 3)
        self.assertEqual([(x["speaker"], x["text"]) for x in result],
                         [("SPEAKER_00", "Hello there."), ("SPEAKER_01", "Good morning.")])
        self.assertEqual([x["id"] for x in result], [0, 1])
        self.assertEqual([(x["start"], x["end"]) for x in result], [(0.0, .9), (1.1, 2.0)])

    def test_ambiguous_overlapping_voices_remain_unknown(self):
        turns = [{"start": 0, "end": 2, "speaker": "SPEAKER_00"},
                 {"start": 0, "end": 2, "speaker": "SPEAKER_01"}]
        self.assertEqual(speaker_for_interval(.5, 1.0, turns), UNKNOWN)

    def test_silence_gap_is_not_assigned_to_nearest_speaker(self):
        self.assertEqual(speaker_for_interval(2, 3, [{"start": 0, "end": 1, "speaker": "SPEAKER_00"}]), UNKNOWN)

    def test_duplicate_turns_do_not_bias_overlap(self):
        turns = [{"start": 0, "end": .6, "speaker": "SPEAKER_00"},
                 {"start": 0, "end": .6, "speaker": "SPEAKER_00"},
                 {"start": 0, "end": .6, "speaker": "SPEAKER_01"}]
        self.assertEqual(speaker_for_interval(0, 1, turns), UNKNOWN)

    def test_zero_duration_timestamp_is_handled(self):
        self.assertEqual(speaker_for_interval(.5, .5, [{"start": 0, "end": 1, "speaker": "SPEAKER_00"}]), "SPEAKER_00")

    def test_no_word_times_uses_phrase_without_fabricating_words(self):
        result = align_words_to_speakers([{"start": 0, "end": 1, "text": "Hello world", "words": []}],
                                        [{"start": 0, "end": 1, "speaker": "SPEAKER_00"}], 1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["text"], "Hello world")

    def test_long_overlapping_turn_does_not_hide_later_turns(self):
        words = [{"start": 0, "end": .5, "word": "One"}, {"start": 3, "end": 3.5, "word": " two"}]
        turns = [{"start": 0, "end": 4, "speaker": "SPEAKER_00"},
                 {"start": 2, "end": 4, "speaker": "SPEAKER_01"}]
        result = align_words_to_speakers([{"start": 0, "end": 4, "text": "One two", "words": words}], turns, 4)
        self.assertEqual([x["speaker"] for x in result], ["SPEAKER_00", UNKNOWN])

    def test_missing_models_are_not_reported_ready(self):
        result = models_status(Path(__file__).resolve().parent / "nonexistent-models")
        self.assertFalse(result["ready"])
        self.assertEqual(len(result["missing"]), 3)


class DecodeTests(unittest.TestCase):
    def test_stereo_48k_resamples_to_mono_16k(self):
        path = Path(__file__).resolve().parent / "tone.wav"
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(2)
            wav.setsampwidth(2)
            wav.setframerate(48000)
            values = bytearray()
            for n in range(48000):
                sample = int(8000 * math.sin(2 * math.pi * 440 * n / 48000))
                values.extend(struct.pack("<hh", sample, sample))
            wav.writeframes(values)
        audio = decode_audio(path)
        self.assertEqual(audio.ndim, 1)
        self.assertEqual(audio.dtype.name, "float32")
        self.assertLessEqual(abs(len(audio) - 16000), 1)
        self.assertGreater(float(abs(audio).max()), .1)
        self.assertLess(float(abs(audio).max()), .5)


if __name__ == "__main__":
    unittest.main()

