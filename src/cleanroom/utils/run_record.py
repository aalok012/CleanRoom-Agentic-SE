"""Per-run result records for paper tracking + cumulative RUN_RESULTS.md index."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_RUNS_DIR = Path("outputs/runs")
DEFAULT_RESULTS_INDEX = Path("RUN_RESULTS.md")

_INDEX_HEADER = (
    "| run_id | date (UTC) | status | SRS | stack | certify | pass@1 | case rate | "
    "tokens | cost (USD) | seconds | detail |"
)
_INDEX_SEP = "|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---|"


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return slug[:48] or "run"


def make_run_id(srs_name: str, when: datetime | None = None) -> str:
    """Stable, sortable run id: ``YYYYMMDD-HHMMSS-<srs-slug>``."""
    when = when or datetime.now(timezone.utc)
    stem = Path(srs_name).stem
    return f"{when.strftime('%Y%m%d-%H%M%S')}-{_slug(stem)}"


def _cert_summary(metrics: dict) -> tuple[str, str]:
    cert = metrics.get("certification") or {}
    if not cert:
        return "-", "-"
    pass_at = cert.get("aggregate_pass_at") or {}
    pass1 = pass_at.get("pass@1")
    case_rate = cert.get("aggregate_case_pass_rate")
    pass1_s = f"{pass1:.3f}" if pass1 is not None else "-"
    case_s = f"{case_rate:.3f}" if case_rate is not None else "-"
    return pass1_s, case_s


def _config_lines(metrics: dict) -> list[str]:
    cfg = metrics.get("config") or {}
    lines = [
        f"- **SRS**: `{metrics.get('srs', 'unknown')}`",
        f"- **stack**: `{metrics.get('stack', 'python')}`",
        f"- **model**: `{metrics.get('model', 'n/a')}`",
    ]
    if cfg:
        lines.append(
            f"- **flags**: certify={cfg.get('certify', False)} "
            f"(n={cfg.get('samples', 'n/a')}), "
            f"prove={cfg.get('prove', False)} "
            f"(target={cfg.get('prove_target', 'n/a')})"
        )
    return lines


def write_run_record(
    metrics: dict,
    *,
    status: str,
    run_id: str,
    runs_dir: Path = DEFAULT_RUNS_DIR,
) -> tuple[Path, Path]:
    """Write one markdown + JSON record for this run. Returns (md_path, json_path)."""
    runs_dir.mkdir(parents=True, exist_ok=True)
    when = datetime.now(timezone.utc)
    tok = metrics.get("tokens") or {}
    pass1, case_rate = _cert_summary(metrics)

    payload = {
        "run_id": run_id,
        "timestamp_utc": when.isoformat(),
        "status": status,
        "srs": metrics.get("srs"),
        "stack": metrics.get("stack"),
        "model": metrics.get("model"),
        "total_seconds": metrics.get("total_seconds", 0.0),
        "tokens": tok,
        "cost_usd": metrics.get("cost_usd", 0.0),
        "config": metrics.get("config", {}),
        "stages": metrics.get("stages", []),
        "code": metrics.get("code"),
        "tests": metrics.get("tests"),
        "dafny": metrics.get("dafny"),
        "compile": metrics.get("compile"),
        "certification": metrics.get("certification"),
    }

    json_path = runs_dir / f"{run_id}.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        f"# Pipeline run `{run_id}`",
        "",
        f"_Status: **{status}** · {when.strftime('%Y-%m-%d %H:%M:%S')} UTC_",
        "",
        "## Configuration",
        "",
        *_config_lines(metrics),
        "",
        "## Outcome",
        "",
        f"- **duration**: {metrics.get('total_seconds', 0.0):.1f}s",
        f"- **tokens**: {tok.get('total', 0):,} "
        f"(in {tok.get('input', 0):,} / out {tok.get('output', 0):,})",
        f"- **LLM calls**: {tok.get('calls', 0)}",
        f"- **estimated cost**: ${metrics.get('cost_usd', 0.0):.4f}",
    ]

    if metrics.get("code"):
        c = metrics["code"]
        lines += [
            "",
            "## Generated code",
            "",
            f"- files: {c.get('files', 0)} · LOC: {c.get('lines_of_code', 0):,}",
            f"- layers: {c.get('files_per_layer', {})}",
        ]

    if metrics.get("tests"):
        t = metrics["tests"]
        lines += ["", "## Generated tests", "", f"- features: {t.get('features', 0)} · cases: {t.get('cases', 0)}"]

    if metrics.get("dafny"):
        d = metrics["dafny"]
        lines += [
            "",
            "## Dafny proof tier",
            "",
            f"- proved: {d.get('n_verified', 0)}/{d.get('n_features', 0)} · rate: {d.get('verification_rate', 0):.3f}",
        ]

    if metrics.get("certification"):
        cert = metrics["certification"]
        lines += ["", "## Certification (pass@k)", "", f"- samples n={cert.get('n', 'n/a')}"]
        for k, v in (cert.get("aggregate_pass_at") or {}).items():
            lines.append(f"- **{k}**: {v:.3f}")
        if cert.get("aggregate_case_pass_rate") is not None:
            lines.append(f"- **case pass rate**: {cert['aggregate_case_pass_rate']:.3f}")

    lines += [
        "",
        "## Per-stage timing & tokens",
        "",
        "| stage | seconds | input tok | output tok | calls |",
        "|---|---:|---:|---:|---:|",
    ]
    for s in metrics.get("stages", []):
        lines.append(
            f"| {s.get('name', '?')} | {s.get('seconds', 0):.2f} | "
            f"{s.get('input_tokens', 0):,} | {s.get('output_tokens', 0):,} | {s.get('calls', 0)} |"
        )
    lines += ["", "## Machine-readable", "", f"- JSON: `{json_path}`", ""]

    md_path = runs_dir / f"{run_id}.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path, json_path


def _parse_index_rows(text: str) -> list[str]:
    rows: list[str] = []
    in_table = False
    for line in text.splitlines():
        if line.strip() == _INDEX_HEADER:
            in_table = True
            continue
        if not in_table or not line.startswith("|"):
            continue
        if line.strip() == _INDEX_SEP:
            continue
        if "run_id" in line:
            continue
        rows.append(line)
    return rows


def append_run_results_index(
    *,
    run_id: str,
    status: str,
    metrics: dict,
    detail_path: Path,
    index_path: Path = DEFAULT_RESULTS_INDEX,
) -> Path:
    """Prepend one row to RUN_RESULTS.md (newest runs first)."""
    when = datetime.now(timezone.utc)
    tok = metrics.get("tokens") or {}
    total_tokens = int(tok.get("total", 0))
    cost_usd = float(metrics.get("cost_usd", 0.0))
    seconds = float(metrics.get("total_seconds", 0.0))
    pass1, case_rate = _cert_summary(metrics)
    cfg = metrics.get("config") or {}
    certify = "yes" if cfg.get("certify") else "no"

    rel_detail = detail_path.as_posix()
    row = (
        f"| `{run_id}` | {when.strftime('%Y-%m-%d %H:%M:%S')} | {status} | "
        f"{metrics.get('srs', '?')} | {metrics.get('stack', '?')} | {certify} | "
        f"{pass1} | {case_rate} | {total_tokens:,} | ${cost_usd:.4f} | {seconds:.1f} | "
        f"[{run_id}.md]({rel_detail}) |"
    )

    existing = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
    old_rows = _parse_index_rows(existing)
    all_rows = [row, *old_rows]

    lines = [
        "# Pipeline Run Results",
        "",
        "Paper-friendly index of every `run_pipeline.py` invocation. "
        "Each run has a dedicated markdown + JSON file under `outputs/runs/`.",
        "",
        _INDEX_HEADER,
        _INDEX_SEP,
        *all_rows,
        "",
        "## Notes",
        "",
        "- Newest runs appear at the top of the table.",
        "- Token/cost totals across all runs: see [API_USAGE.md](API_USAGE.md).",
        "- Latest per-SRS artifacts (overwritten each run): `outputs/<srs>_full_ir.json`, "
        "`outputs/<srs>_run_report.md`.",
        "",
    ]
    index_path.write_text("\n".join(lines), encoding="utf-8")
    return index_path


def record_run(
    metrics: dict,
    *,
    status: str,
    runs_dir: Path = DEFAULT_RUNS_DIR,
    index_path: Path = DEFAULT_RESULTS_INDEX,
    run_id: str | None = None,
) -> dict:
    """Write per-run files + update RUN_RESULTS.md. Returns paths dict."""
    run_id = run_id or make_run_id(metrics.get("srs") or "unknown")
    md_path, json_path = write_run_record(metrics, status=status, run_id=run_id, runs_dir=runs_dir)
    index_path = append_run_results_index(
        run_id=run_id,
        status=status,
        metrics=metrics,
        detail_path=md_path,
        index_path=index_path,
    )
    return {"run_id": run_id, "markdown": md_path, "json": json_path, "index": index_path}
