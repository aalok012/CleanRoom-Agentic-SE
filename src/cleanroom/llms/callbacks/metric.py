"""LLM metrics: token/latency accounting via a LangChain callback.

`GLOBAL_HANDLER` is attached by `get_llm()` to every model, so every LLM call is
counted without the agents having to know about it. It observes only token COUNTS
and latency — never prompt/response content — so the clean-room isolation between
agents is unaffected.
"""

import time
from dataclasses import dataclass, field

from langchain_core.callbacks import BaseCallbackHandler


@dataclass
class LLMMetrics:
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    model: str = ""
    calls: list[dict] = field(default_factory=list)

    def record(self, model: str, input_tokens: int, output_tokens: int, latency_ms: float) -> None:
        self.model = model or self.model
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.latency_ms += latency_ms
        self.calls.append(
            {
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "latency_ms": latency_ms,
            }
        )

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def snapshot(self) -> tuple[int, int, int]:
        """(input_tokens, output_tokens, call_count) — for computing per-stage deltas."""
        return self.input_tokens, self.output_tokens, len(self.calls)


class MetricsCallbackHandler(BaseCallbackHandler):
    def __init__(self, metrics: "LLMMetrics") -> None:
        self.metrics = metrics
        self._starts: dict = {}

    def on_llm_start(self, serialized, prompts, *, run_id=None, **kwargs) -> None:
        self._starts[run_id] = time.perf_counter()

    def on_llm_end(self, response, *, run_id=None, **kwargs) -> None:
        latency_ms = 0.0
        start = self._starts.pop(run_id, None)
        if start is not None:
            latency_ms = (time.perf_counter() - start) * 1000.0
        model, inp, out = self._extract(response)
        self.metrics.record(model, inp, out, latency_ms)

    @staticmethod
    def _extract(response) -> tuple[str, int, int]:
        """Pull (model, input_tokens, output_tokens) from an LLMResult, defensively."""
        inp = out = 0
        for gens in getattr(response, "generations", None) or []:
            for gen in gens:
                msg = getattr(gen, "message", None)
                usage = getattr(msg, "usage_metadata", None) if msg is not None else None
                if usage:
                    inp += usage.get("input_tokens", 0)
                    out += usage.get("output_tokens", 0)
        llm_output = getattr(response, "llm_output", None) or {}
        if not (inp or out):
            tu = llm_output.get("token_usage") or llm_output.get("usage") or {}
            inp = tu.get("prompt_tokens", 0)
            out = tu.get("completion_tokens", 0)
        model = llm_output.get("model_name", "") or ""
        return model, inp, out


# Process-wide collector + handler, attached by get_llm().
GLOBAL_METRICS = LLMMetrics()
GLOBAL_HANDLER = MetricsCallbackHandler(GLOBAL_METRICS)
