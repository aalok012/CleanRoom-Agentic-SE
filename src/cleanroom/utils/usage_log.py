"""Append-only API usage ledger (Markdown) for shared OpenAI keys."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

# Single consolidated usage ledger (full history from the beginning). All runs append here and
# cumulative totals are recomputed from every row on each write.
DEFAULT_USAGE_LOG = Path("API_USAGE.md")

_HISTORY_HEADER = (
    "| date (UTC) | run_id | status | SRS | model | calls | input tok | output tok | "
    "total tok | cost (USD) | seconds | result |"
)
_HISTORY_SEP = "|---|---|---|---|---:|---:|---:|---:|---:|---:|---|"
_LEGACY_HEADER = (
    "| date (UTC) | status | SRS | model | calls | input tok | output tok | "
    "total tok | cost (USD) | seconds |"
)


def _parse_history_rows(text: str) -> list[dict]:
    rows: list[dict] = []
    in_history = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped in (_HISTORY_HEADER, _LEGACY_HEADER):
            in_history = True
            continue
        if not in_history or not line.startswith("|"):
            continue
        if stripped == _HISTORY_SEP or stripped.replace("---|", "") == _LEGACY_HEADER.replace("|", ""):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 10:
            try:
                rows.append(
                    {
                        "calls": int(cells[4].replace(",", "")),
                        "input_tokens": int(cells[5].replace(",", "")),
                        "output_tokens": int(cells[6].replace(",", "")),
                        "total_tokens": int(cells[7].replace(",", "")),
                        "cost_usd": float(cells[8].replace("$", "")),
                    }
                )
            except ValueError:
                continue
        elif len(cells) == 12:
            try:
                rows.append(
                    {
                        "calls": int(cells[5].replace(",", "")),
                        "input_tokens": int(cells[6].replace(",", "")),
                        "output_tokens": int(cells[7].replace(",", "")),
                        "total_tokens": int(cells[8].replace(",", "")),
                        "cost_usd": float(cells[9].replace("$", "")),
                    }
                )
            except ValueError:
                continue
    return rows


def _normalize_history_line(line: str) -> str:
    """Upgrade legacy 10-column rows to the current 12-column format."""
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    if len(cells) == 12:
        return line
    if len(cells) != 10:
        return line
    return (
        f"| {cells[0]} | `legacy` | {cells[1]} | {cells[2]} | {cells[3]} | "
        f"{cells[4]} | {cells[5]} | {cells[6]} | {cells[7]} | {cells[8]} | {cells[9]} | - |"
    )


def _collect_history_lines(existing: str) -> list[str]:
    history_lines: list[str] = []
    if not existing:
        return history_lines
    in_history = False
    for line in existing.splitlines():
        stripped = line.strip()
        if stripped in (_HISTORY_HEADER, _LEGACY_HEADER):
            in_history = True
            continue
        if not in_history:
            continue
        if stripped.startswith("|---"):
            continue
        if line.startswith("|") and "date (UTC)" not in line:
            history_lines.append(_normalize_history_line(line))
    return history_lines


def _format_row(
    *,
    when: datetime,
    run_id: str,
    status: str,
    srs: str,
    model: str,
    calls: int,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    cost_usd: float,
    seconds: float,
    result_link: str,
) -> str:
    link = result_link or "-"
    return (
        f"| {when.strftime('%Y-%m-%d %H:%M:%S')} | `{run_id}` | {status} | {srs} | {model} | "
        f"{calls:,} | {input_tokens:,} | {output_tokens:,} | {total_tokens:,} | "
        f"${cost_usd:.4f} | {seconds:.1f} | {link} |"
    )


def _render_document(rows: list[dict], history_lines: list[str]) -> str:
    runs = len(rows)
    calls = sum(r["calls"] for r in rows)
    input_tokens = sum(r["input_tokens"] for r in rows)
    output_tokens = sum(r["output_tokens"] for r in rows)
    total_tokens = sum(r["total_tokens"] for r in rows)
    cost_usd = sum(r["cost_usd"] for r in rows)

    lines = [
        "# API Usage Log",
        "",
        "Track OpenAI **token consumption** and **LLM call counts** for the shared professor API key.",
        "Updated automatically at the end of each `run_pipeline.py` invocation (including failed runs).",
        "",
        "## Cumulative totals",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| runs logged | {runs:,} |",
        f"| LLM calls | {calls:,} |",
        f"| input tokens | {input_tokens:,} |",
        f"| output tokens | {output_tokens:,} |",
        f"| total tokens | {total_tokens:,} |",
        f"| estimated cost (USD) | ${cost_usd:.4f} |",
        "",
        "## Run history",
        "",
        _HISTORY_HEADER,
        _HISTORY_SEP,
        *history_lines,
        "",
        "## Notes",
        "",
        "- Costs use `src/cleanroom/utils/cost.py` list prices for the reported model.",
        "- `status=failed` means the pipeline exited early; tokens from completed stages are still counted.",
        "- **Per-run detail** (config, pass@k, stage breakdown): `outputs/runs/<run_id>.md` "
        "and the cumulative index [RUN_RESULTS.md](RUN_RESULTS.md).",
        "- Latest per-SRS snapshot (overwritten): `outputs/<srs>_run_report.md`.",
        "",
    ]
    return "\n".join(lines)


def append_usage_log(
    metrics: dict,
    *,
    path: Path = DEFAULT_USAGE_LOG,
    status: str = "complete",
    run_id: str = "",
    result_path: Path | None = None,
) -> Path:
    """Append one run to the usage log and refresh cumulative totals."""
    tok = metrics.get("tokens") or {}
    input_tokens = int(tok.get("input", 0))
    output_tokens = int(tok.get("output", 0))
    total_tokens = int(tok.get("total", input_tokens + output_tokens))
    calls = int(tok.get("calls", 0))
    cost_usd = float(metrics.get("cost_usd", 0.0))
    seconds = float(metrics.get("total_seconds", 0.0))
    model = metrics.get("model") or "unknown"
    srs = metrics.get("srs") or "unknown"
    run_id = run_id or metrics.get("run_id") or "unknown"

    when = datetime.now(timezone.utc)
    result_link = f"[detail]({result_path.as_posix()})" if result_path else "-"
    new_row = _format_row(
        when=when,
        run_id=run_id,
        status=status,
        srs=srs,
        model=model,
        calls=calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost_usd=cost_usd,
        seconds=seconds,
        result_link=result_link,
    )

    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    parsed = _parse_history_rows(existing)
    history_lines = _collect_history_lines(existing)
    history_lines.append(new_row)
    parsed.append(
        {
            "calls": calls,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "cost_usd": cost_usd,
        }
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_document(parsed, history_lines), encoding="utf-8")
    return path


def metrics_from_globals(*, srs: str, stack: str, stages: list, config: dict | None = None) -> dict:
    """Build a metrics dict from GLOBAL_METRICS when a run aborts mid-pipeline."""
    from src.cleanroom.llms.callbacks.metric import GLOBAL_METRICS
    from src.cleanroom.utils.cost import estimate_cost_by_model

    in_tot, out_tot, calls = GLOBAL_METRICS.snapshot()
    cost, by_model = estimate_cost_by_model(GLOBAL_METRICS.calls)
    from src.cleanroom.utils.llm_client import DEFAULT_MODEL

    model = "+".join(sorted(by_model)) if len(by_model) > 1 else (GLOBAL_METRICS.model or DEFAULT_MODEL)
    return {
        "srs": srs,
        "stack": stack,
        "stages": stages,
        "config": config or {},
        "model": model,
        "total_seconds": round(sum(s.get("seconds", 0) for s in stages), 3),
        "tokens": {
            "input": in_tot,
            "output": out_tot,
            "total": in_tot + out_tot,
            "calls": calls,
        },
        "cost_usd": cost,
        "cost_by_model": by_model,
    }
