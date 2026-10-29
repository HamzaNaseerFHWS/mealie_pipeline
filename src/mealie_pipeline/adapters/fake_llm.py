"""Scripted LLMBackend: responses matched by task and a prompt substring; calls are recorded.

A response is a dict, an exception to raise, or a function of the prompt that returns the dict."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mealie_pipeline.adapters.llm import LLMError, Tier


@dataclass
class LLMCall:
    task: str
    prompt: str
    schema: dict[str, Any]
    tier: Tier


Response = dict[str, Any] | Exception | Callable[[str], dict[str, Any]]


class FakeLLM:
    def __init__(self) -> None:
        self.calls: list[LLMCall] = []
        self._scripts: list[tuple[str, str, Response]] = []

    def script(self, task: str, response: Response, *, when_prompt_has: str = "") -> None:
        self._scripts.append((task, when_prompt_has, response))

    def complete(
        self, task: str, prompt: str, schema: dict[str, Any], tier: Tier, images: tuple[Path, ...] = ()
    ) -> dict[str, Any]:
        self.calls.append(LLMCall(task, prompt, schema, tier))
        for scripted_task, needle, response in self._scripts:
            if scripted_task == task and needle in prompt:
                if isinstance(response, Exception):
                    raise response
                return response(prompt) if callable(response) else response
        raise LLMError(f"FakeLLM has no script for task {task!r}")
