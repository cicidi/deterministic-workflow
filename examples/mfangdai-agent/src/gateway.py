"""LLM Gateway: JSON validation, retry, output_schema enforcement."""
import json
import logging
from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "deepseek-v4"
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"


class Gateway:
    """All LLM calls route through this gateway for JSON validation and retry."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str = "sk-placeholder",
        max_retries: int = 3,
    ):
        self.model = model
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
        """Call LLM with structured output, retry on failure."""
        llm_with_schema = self.llm.with_structured_output(output_schema)
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                result = llm_with_schema.invoke(prompt)
                return result
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
