"""Rough USD cost estimate from token counts.

Prices are USD per 1M tokens and may drift over time — update PRICING if they change.
"""

from src.cleanroom.utils.llm_client import DEFAULT_MODEL

PRICING: dict[str, dict[str, float]] = {
    "deepseek-v3.2": {"input": 0.2288, "output": 0.3432},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "gpt-5.5": {"input": 5.00, "output": 30.00},
}


def _normalize_model(model: str) -> str:
    """Strip an OpenRouter-style provider prefix (``openai/gpt-4.1`` → ``gpt-4.1``)."""
    return model.split("/", 1)[1] if "/" in model else model


def _rates(model: str) -> dict[str, float]:
    """Prices for a model, matching the longest known prefix (handles dated suffixes)."""
    model = _normalize_model(model)
    if model in PRICING:
        return PRICING[model]
    for name in sorted(PRICING, key=len, reverse=True):
        if model.startswith(name):
            return PRICING[name]
    return PRICING[_normalize_model(DEFAULT_MODEL)]


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = _rates(model)
    return input_tokens / 1_000_000 * rates["input"] + output_tokens / 1_000_000 * rates["output"]


def estimate_cost_by_model(calls) -> tuple[float, dict[str, dict]]:
    """Accurate cost for a MIXED-model run (e.g. --prove: gpt-4o-mini + gpt-4.1).

    Groups per-call records (``{model, input_tokens, output_tokens}`` from GLOBAL_METRICS.calls)
    by model and prices each group at its own rate. Returns (total_usd, {model: {input, output,
    calls, cost_usd}}). Pricing each model separately avoids the under/over-billing you get from
    applying one model's rate to every token.
    """
    by_model: dict[str, dict] = {}
    for c in calls or []:
        m = c.get("model") or DEFAULT_MODEL
        agg = by_model.setdefault(m, {"input": 0, "output": 0, "calls": 0, "cost_usd": 0.0})
        agg["input"] += int(c.get("input_tokens", 0))
        agg["output"] += int(c.get("output_tokens", 0))
        agg["calls"] += 1
    total = 0.0
    for m, agg in by_model.items():
        agg["cost_usd"] = round(estimate_cost(m, agg["input"], agg["output"]), 6)
        total += agg["cost_usd"]
    return round(total, 6), by_model
