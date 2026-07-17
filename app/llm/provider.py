from __future__ import annotations

import json
import re
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.core.config import get_settings


class QATestCase(BaseModel):
    title: str = Field(min_length=1)
    steps: list[str] = Field(min_length=1)
    expected_result: str = Field(min_length=1)
    source_section_paths: list[str] = Field(default_factory=list)

    @field_validator("steps")
    @classmethod
    def steps_must_be_non_empty_strings(cls, value: list[str]) -> list[str]:
        cleaned = [step.strip() for step in value if step and step.strip()]
        if not cleaned:
            raise ValueError("steps must contain at least one non-empty string")
        return cleaned


class QAGenerationOutput(BaseModel):
    test_cases: list[QATestCase] = Field(min_length=3, max_length=5)


class LLMProvider(Protocol):
    def generate_qa_json(self, *, manual_text: str, attempt: int) -> str:
        """Return raw model text that should contain JSON."""


QA_PROMPT_TEMPLATE = """You are helping QA engineers write concrete test cases for a
medical device manual (CardioTrack CT-200).

Using ONLY the manual excerpts below, generate between 3 and 5 QA test cases.
Each test case must be specific and executable (clear steps + expected result).

Return ONLY valid JSON with this exact shape:
{{
  "test_cases": [
    {{
      "title": "string",
      "steps": ["string", "string"],
      "expected_result": "string",
      "source_section_paths": ["1.1"]
    }}
  ]
}}

Rules:
- Produce 3 to 5 objects in test_cases.
- Do not invent device behavior that is not supported by the excerpts.
- source_section_paths should reference section numbers present in the excerpts when possible.
- No markdown fences, no commentary, JSON only.

MANUAL EXCERPTS:
{manual_text}
"""


def build_qa_prompt(manual_text: str) -> str:
    return QA_PROMPT_TEMPLATE.format(manual_text=manual_text)


def extract_json_payload(raw_text: str) -> Any:
    """Parse JSON from model output, tolerating optional ```json fences."""
    text = raw_text.strip()
    if not text:
        raise ValueError("LLM returned empty content")

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("LLM response did not contain a JSON object")
        text = text[start : end + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM response was not valid JSON: {exc}") from exc


def parse_and_validate_qa_output(raw_text: str) -> QAGenerationOutput:
    payload = extract_json_payload(raw_text)
    try:
        return QAGenerationOutput.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"LLM JSON failed schema validation: {exc}") from exc


class GeminiProvider:
    def __init__(self, api_key: str | None = None, model_name: str | None = None):
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.gemini_api_key
        self.model_name = model_name or settings.gemini_model
        if not self.api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not configured. Set it in the environment or .env."
            )

    def generate_qa_json(self, *, manual_text: str, attempt: int) -> str:
        import google.generativeai as genai

        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel(self.model_name)
        prompt = build_qa_prompt(manual_text)
        if attempt > 1:
            prompt += (
                "\n\nPrevious output was invalid. "
                "Respond with ONLY the JSON object. No markdown."
            )
        
        response = model.generate_content(prompt)
        text = getattr(response, "text", None)
        if not text:
            raise ValueError("Gemini returned no text content")
        return text


class ScriptedLLMProvider:
    """Deterministic provider for tests: returns queued raw responses."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls = 0

    def generate_qa_json(self, *, manual_text: str, attempt: int) -> str:
        self.calls += 1
        if not self._responses:
            raise RuntimeError("ScriptedLLMProvider has no remaining responses")
        return self._responses.pop(0)
