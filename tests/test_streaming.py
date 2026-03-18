import unittest

from app.streaming import StreamingTranscriptionSession, build_stream_event, reconcile_segments


class StreamEventTests(unittest.TestCase):
    def test_build_partial_segment_event(self) -> None:
        event = build_stream_event(
            event_type="partial_segment",
            sequence=2,
            session_id="s1",
            text="ni hao",
            start=0.0,
            end=0.8,
            is_final=False,
        )
        self.assertEqual(event["type"], "partial_segment")
        self.assertEqual(event["sequence"], 2)
        self.assertFalse(event["is_final"])


class StreamReconciliationTests(unittest.TestCase):
    def test_reconcile_segments_promotes_stable_prefix(self) -> None:
        previous_final = [{"text": "hello", "start": 0.0, "end": 0.5}]
        latest_segments = [
            {"text": "hello", "start": 0.0, "end": 0.5},
            {"text": "world maybe", "start": 0.5, "end": 1.2},
        ]
        result = reconcile_segments(previous_final, latest_segments)
        self.assertEqual(result.final_segments, previous_final)
        self.assertEqual(result.partial_segment["text"], "world maybe")


class StreamSessionTests(unittest.TestCase):
    def test_streaming_session_emits_final_and_partial_events(self) -> None:
        session = StreamingTranscriptionSession(language="auto", session_id="s1")

        first_pass = session.apply_transcription_result(
            {
                "requested_language": "auto",
                "detected_language": "yue",
                "language_probability": 0.98,
                "text": "hello maybe",
                "segments": [{"text": "hello maybe", "start": 0.0, "end": 0.8}],
            }
        )
        self.assertEqual([event["type"] for event in first_pass], ["partial_segment"])

        second_pass = session.apply_transcription_result(
            {
                "requested_language": "auto",
                "detected_language": "yue",
                "language_probability": 0.98,
                "text": "hello world",
                "segments": [
                    {"text": "hello", "start": 0.0, "end": 0.4},
                    {"text": "world", "start": 0.4, "end": 0.8},
                ],
            }
        )
        self.assertEqual([event["type"] for event in second_pass], ["final_segment", "partial_segment"])
        self.assertEqual(second_pass[0]["text"], "hello")
        self.assertEqual(second_pass[1]["text"], "world")


if __name__ == "__main__":
    unittest.main()
