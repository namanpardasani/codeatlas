"""Deterministic offline provider for tests and for running the UI without any LLM.

Scripted mode: FakeLLM(script=["answer text"]) replays the given text (chunked like a stream).
Extractive mode (default): reads the numbered context out of the prompt and quotes the best chunk with a
citation, so the whole chat path (retrieval -> prompt -> stream -> verification -> UI) can be exercised."""
import re
from collections.abc import Iterator

from .types import Delta, Message, Usage, estimate_tokens

CHUNK_HEAD = re.compile(r"^\[(C\d+)\] (\S+?):(\d+)-(\d+)", re.M)


class FakeLLM:
    name = "fake"
    model = "fake-extractive"
    paid = False

    def __init__(self, script: list[str] | None = None):
        self.script = list(script) if script else None
        self.calls: list[list[Message]] = []   # tests inspect the prompts that were sent

    def stream(self, messages: list[Message], *, max_tokens: int = 700, temperature: float = 0.1) -> Iterator[Delta | Usage]:
        self.calls.append(messages)
        text = self.script.pop(0) if self.script else self._extractive(messages)
        for i in range(0, len(text), 24):
            yield Delta(text[i:i + 24])
        yield Usage(estimate_tokens(" ".join(m.content for m in messages)), estimate_tokens(text))

    @staticmethod
    def _extractive(messages: list[Message]) -> str:
        context = next((m.content for m in reversed(messages) if m.role == "user"), "")
        heads = CHUNK_HEAD.findall(context)
        if not heads:
            return "I couldn't find this in the repo."
        label, path, start, end = heads[0]
        return f"The relevant code is in `{path}` (lines {start}-{end}) [{label}:{start}-{end}]."
