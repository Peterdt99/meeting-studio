import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import audio_engine

class SupportFloorTests(unittest.TestCase):
    def test_brief_outlier_stays_unassigned_and_supported_ids_are_stable(self):
        turns = [{"start": 0, "end": 1, "speaker": "SPEAKER_00"},
                 {"start": 2, "end": 202, "speaker": "SPEAKER_01"},
                 {"start": 203, "end": 303, "speaker": "SPEAKER_02"},
                 {"start": 304, "end": 350, "speaker": "SPEAKER_01"}]
        result = audio_engine._stabilize_auto_speakers(turns)
        self.assertEqual([t["speaker"] for t in result], [audio_engine.UNKNOWN, "SPEAKER_00", "SPEAKER_01", "SPEAKER_00"])
        self.assertEqual([(t["start"], t["end"]) for t in result], [(t["start"], t["end"]) for t in turns])
        self.assertEqual(turns[0]["speaker"], "SPEAKER_00", "Do not mutate the original diarization result")

    def test_short_turn_in_short_clip_is_not_silenced(self):
        turns = [{"start": 0, "end": 1, "speaker": "a"}, {"start": 2, "end": 6, "speaker": "b"}]
        result = audio_engine._stabilize_auto_speakers(turns)
        self.assertEqual(len({t["speaker"] for t in result}), 2)
        self.assertNotIn(audio_engine.UNKNOWN, {t["speaker"] for t in result})

    def test_repeated_brief_contributions_accumulate_support(self):
        turns = [{"start": 0, "end": .8, "speaker": "a"}, {"start": 1, "end": 201, "speaker": "b"},
                 {"start": 202, "end": 202.8, "speaker": "a"}]
        result = audio_engine._stabilize_auto_speakers(turns)
        self.assertEqual(len({t["speaker"] for t in result}), 2)
        self.assertNotIn(audio_engine.UNKNOWN, {t["speaker"] for t in result})



