"""LLM Gateway: JSON validation, retry, output_schema enforcement.

Multi-model support via environment variables:
  LLM_MODEL     — model name (default: deepseek-v4-flash)
  LLM_BASE_URL  — API base URL (default: https://api.deepseek.com/v1)
  LLM_API_KEY   — API key (default: sk-placeholder)

Examples:
  # DeepSeek (default)
  export LLM_MODEL=deepseek-v4-flash

  # GPT-5 Nano
  export LLM_MODEL=gpt-5-nano
  export LLM_BASE_URL=https://api.openai.com/v1
  export LLM_API_KEY=sk-...
"""
import json
import logging
import os
from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")
DEFAULT_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1")
DEFAULT_API_KEY = os.environ.get("LLM_API_KEY", "sk-placeholder")


class Gateway:
    """All LLM calls route through this gateway for JSON validation and retry."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str = DEFAULT_API_KEY,
        max_retries: int = 3,
    ):
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.max_retries = max_retries
        self.llm = ChatOpenAI(
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=0,
        )

    def call(
        self,
        prompt: str,
        output_schema: type[BaseModel],
        temperature: float = 0,
    ) -> Any:
        """Call LLM with structured output via prompt-based JSON, retry on failure."""
        json_prompt = (
            f"{prompt}\n\n"
            f"Respond ONLY with valid JSON matching this schema: {output_schema.model_json_schema()}\n"
            f"Do NOT include markdown fences, explanations, or extra text. Output raw JSON only."
        )
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                llm_json = ChatOpenAI(
                    model=self.model,
                    base_url=self.base_url,
                    api_key=self.api_key,
                    temperature=temperature,
                )
                result = llm_json.invoke(json_prompt)
                text = result.content.strip()
                if text.startswith("```"):
                    text = text.split("```")[1]
                    if text.startswith("json"):
                        text = text[4:]
                    text = text.strip()
                parsed = json.loads(text)
                return output_schema.model_validate(parsed)
            except Exception as e:
                last_error = e
                logger.warning(
                    f"LLM call attempt {attempt}/{self.max_retries} failed: {e}"
                )
        raise RuntimeError(
            f"LLM call failed after {self.max_retries} attempts. Last error: {last_error}"
        )

    def call_text(self, prompt: str, temperature: float = 0.3) -> str:
        """Call LLM for free-text response (Layer 3 only)."""
        llm_text = ChatOpenAI(
            model=self.model,
            base_url=self.base_url,
            api_key=self.api_key,
            temperature=temperature,
        )
        result = llm_text.invoke(prompt)
        return result.content
