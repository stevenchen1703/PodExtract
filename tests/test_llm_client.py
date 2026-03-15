from __future__ import annotations

import unittest

from app.services.llm_client import LLMClient


class LLMClientParseTest(unittest.TestCase):
    def test_parse_plain_json(self) -> None:
        text = '{"logic_outline":["a"],"highlights":[],"work_connections":[],"kb_connections":[]}'
        payload = LLMClient._parse_json_response(text)
        self.assertEqual(payload["logic_outline"], ["a"])

    def test_parse_code_fenced_json(self) -> None:
        text = (
            "```json\n"
            '{"logic_outline":["a"],"highlights":[],"work_connections":[],"kb_connections":[]}\n'
            "```"
        )
        payload = LLMClient._parse_json_response(text)
        self.assertEqual(payload["logic_outline"], ["a"])

    def test_parse_think_then_json(self) -> None:
        text = (
            "<think>internal reasoning</think>\n"
            '{"logic_outline":["a"],"highlights":[],"work_connections":[],"kb_connections":[]}'
        )
        payload = LLMClient._parse_json_response(text)
        self.assertEqual(payload["logic_outline"], ["a"])

    def test_parse_text_wrapped_json(self) -> None:
        text = (
            "Here is the result:\n"
            '{"logic_outline":["a"],"highlights":[],"work_connections":[],"kb_connections":[]}\n'
            "done"
        )
        payload = LLMClient._parse_json_response(text)
        self.assertEqual(payload["logic_outline"], ["a"])


if __name__ == "__main__":
    unittest.main()
