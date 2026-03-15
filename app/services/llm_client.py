from __future__ import annotations

import json
import re

import httpx


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    async def chat_json(self, system_prompt: str, user_prompt: str) -> dict:
        if not self.api_key:
            raise RuntimeError("Missing LLM_API_KEY")

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }

        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"]
        if isinstance(content, list):
            text = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        else:
            text = str(content)

        return self._parse_json_response(text)

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        cleaned = text.strip()
        if cleaned.startswith("```") and cleaned.endswith("```"):
            lines = cleaned.splitlines()
            if len(lines) >= 3:
                return "\n".join(lines[1:-1])
        return cleaned

    @staticmethod
    def _parse_json_response(text: str) -> dict:
        cleaned = LLMClient._strip_code_fence(text)
        cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL).strip()

        for candidate in (
            cleaned,
            LLMClient._extract_json_from_fence(cleaned),
            LLMClient._extract_first_json_object(cleaned),
        ):
            if not candidate:
                continue
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue

        raise json.JSONDecodeError("Unable to parse JSON from LLM response", cleaned, 0)

    @staticmethod
    def _extract_json_from_fence(text: str) -> str:
        match = re.search(r"```(?:json)?\\s*(\\{[\\s\\S]*?\\})\\s*```", text, flags=re.IGNORECASE)
        if not match:
            return ""
        return match.group(1).strip()

    @staticmethod
    def _extract_first_json_object(text: str) -> str:
        for start in range(len(text)):
            if text[start] != "{":
                continue

            depth = 0
            in_string = False
            escaped = False

            for idx in range(start, len(text)):
                ch = text[idx]

                if in_string:
                    if escaped:
                        escaped = False
                    elif ch == "\\":
                        escaped = True
                    elif ch == '"':
                        in_string = False
                    continue

                if ch == '"':
                    in_string = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return text[start : idx + 1]

        return ""
