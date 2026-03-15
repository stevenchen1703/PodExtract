from __future__ import annotations

import unittest

from app.services.stt.elevenlabs import ElevenLabsSTTProvider
from app.services.stt.minimax import MiniMaxSTTProvider


class STTWordJoinTest(unittest.TestCase):
    def test_elevenlabs_chinese_words_join_without_spaces(self) -> None:
        words = [
            {"speaker_id": "s1", "start": 0.0, "end": 0.1, "text": "你"},
            {"speaker_id": "s1", "start": 0.1, "end": 0.2, "text": "好"},
            {"speaker_id": "s1", "start": 0.2, "end": 0.3, "text": "世"},
            {"speaker_id": "s1", "start": 0.3, "end": 0.4, "text": "界"},
        ]
        segments = ElevenLabsSTTProvider._from_words(words)
        self.assertEqual(segments[0].text, "你好世界")

    def test_elevenlabs_english_words_join_with_spaces(self) -> None:
        words = [
            {"speaker_id": "s1", "start": 0.0, "end": 0.1, "text": "hello"},
            {"speaker_id": "s1", "start": 0.1, "end": 0.2, "text": "world"},
        ]
        segments = ElevenLabsSTTProvider._from_words(words)
        self.assertEqual(segments[0].text, "hello world")

    def test_minimax_chinese_words_join_without_spaces(self) -> None:
        words = [
            {"speaker_id": "s1", "start": 0.0, "end": 0.1, "text": "中"},
            {"speaker_id": "s1", "start": 0.1, "end": 0.2, "text": "文"},
            {"speaker_id": "s1", "start": 0.2, "end": 0.3, "text": "稿"},
        ]
        segments = MiniMaxSTTProvider._from_words(words)
        self.assertEqual(segments[0].text, "中文稿")

    def test_minimax_english_words_join_with_spaces(self) -> None:
        words = [
            {"speaker_id": "s1", "start": 0.0, "end": 0.1, "text": "pod"},
            {"speaker_id": "s1", "start": 0.1, "end": 0.2, "text": "extract"},
        ]
        segments = MiniMaxSTTProvider._from_words(words)
        self.assertEqual(segments[0].text, "pod extract")


if __name__ == "__main__":
    unittest.main()
