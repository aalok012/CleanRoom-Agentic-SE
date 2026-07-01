#!/usr/bin/env python3
"""Aggregate every per-run metrics JSON into one flat CSV.

Each pipeline run writes ``<output-dir>/runs/<run_id>.json`` (see
src/cleanroom/utils/run_record.py). This walks all of them under --root, flattens
each into a single row, and rebuilds --out from scratch (idempotent — safe to
re-run after every pipeline cell). One row per run, keyed/deduped by run_id.

The matrix runner (run_matrix.sh) lays runs out as
``outputs/<language>/<srs_stem>/<model_safe>/runs/<run_id>.json``; language / srs /
model are derived from that path when possible, falling back to the JSON body so
older flat layouts still aggregate.

Usage:
    uv run python scripts/collect_metrics.py [--root outputs] [--out experiment_metrics.csv]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

# Allow `from src.cleanroom...` when run as `python scripts/collect_metrics.py` (repo root on path).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_SRS_DIR = Path(__file__).resolve().parent.parent / "data" / "srs"
_FR_CACHE: dict[str, object] = {}


def _n_frs(srs_stem: str) -> object:
    """Number of functional requirements in this SRS, via the deterministic parser. Cached per
    stem; blank if the SRS file can't be found/parsed. Same value for every row of a given SRS."""
    if srs_stem in _FR_CACHE:
        return _FR_CACHE[srs_stem]
    val: object = ""
    srs_file = _SRS_DIR / f"{srs_stem}.xml"
    if srs_file.is_file():
        try:
            from src.cleanroom.agents.spec_agent.tools.srs_reader import SRSReader
            feats = SRSReader().read_features(srs_file)
            val = sum(len(f.get("functional_requirements", [])) for f in feats)
        except Exception:
            val = ""
    _FR_CACHE[srs_stem] = val
    return val

COLUMNS = [
    "run_id", "timestamp", "status", "language", "srs", "n_frs", "stack", "model",
    "total_seconds",
    "tokens_in", "tokens_out", "tokens_total", "llm_calls", "cost_usd",
    "code_files", "code_loc", "test_features", "test_cases",
    "dafny_n_features", "dafny_n_verified", "dafny_verification_rate", "dafny_axioms",
    "verification_seconds", "certification_seconds",
    "cert_n", "pass@1", "case_pass_rate", "n_tested_frs", "n_proved_features",
    "prove", "certify", "samples", "max_cert_loops", "temperature",
    # headline research summary (from <stem>_full_ir.json metrics.summary; falls back to the
    # always-available token/time/case-rate fields from the run JSON when full_ir is absent).
    "verification_pass_ratio", "test_case_pass_ratio", "avg_input_token", "avg_output_token",
    "total_time", "avg_verification_iter", "avg_test_iter", "PassVer@1",
]

# summary key in full_ir metrics  ->  CSV column
_SUMMARY_MAP = {
    "verification_pass_ratio": "verification_pass_ratio",
    "test_case_pass_ratio": "test_case_pass_ratio",
    "avg_input_token": "avg_input_token",
    "avg_output_token": "avg_output_token",
    "total_time": "total_time",
    "avg_verification_iteration": "avg_verification_iter",
    "avg_test_iteration": "avg_test_iter",
    "PassVer@1": "PassVer@1",
}


def _summary_fields(json_path: Path, rec: dict) -> dict:
    """The 8 headline metrics for one run. Prefer the authoritative pre-computed
    ``metrics.summary`` in the cell's <stem>_full_ir.json; otherwise fall back to the
    fields recomputable from the run JSON alone (FR-level ratios left blank)."""
    out = {c: "" for c in _SUMMARY_MAP.values()}
    # cell dir = parent of runs/ ; full_ir lives there as <stem>_full_ir.json
    cell_dir = json_path.parent.parent
    fir = next(iter(cell_dir.glob("*full_ir.json")), None)
    if fir is not None:
        try:
            summary = (json.loads(fir.read_text(encoding="utf-8")).get("metrics") or {}).get("summary") or {}
        except (json.JSONDecodeError, OSError):
            summary = {}
        if summary:
            for src, col in _SUMMARY_MAP.items():
                out[col] = summary.get(src, "")
            return out
    # Fallback: token/time/case-rate are present in the run JSON for every cell.
    tok = rec.get("tokens") or {}
    calls = tok.get("calls") or 0
    cert = rec.get("certification") or {}
    if calls:
        out["avg_input_token"] = round(tok.get("input", 0) / calls, 1)
        out["avg_output_token"] = round(tok.get("output", 0) / calls, 1)
    out["total_time"] = rec.get("total_seconds", "")
    if cert.get("aggregate_case_pass_rate") is not None:
        out["test_case_pass_ratio"] = round(cert.get("aggregate_case_pass_rate", 0.0), 4)
    # The naive baseline emits no full_ir summary. Prefer its FR-granular ratio
    # (proved_FRs / total_FRs, matches the full pipeline) when recorded; otherwise fall
    # back to the feature-granular rate (n_verified / n_features).
    dafny = rec.get("dafny") or {}
    if dafny.get("verification_pass_ratio_fr") is not None:
        out["verification_pass_ratio"] = round(dafny.get("verification_pass_ratio_fr", 0.0), 4)
    elif dafny.get("verification_rate") is not None:
        out["verification_pass_ratio"] = round(dafny.get("verification_rate", 0.0), 4)
    return out


def _derive_from_path(json_path: Path, root: Path) -> dict:
    """Pull language / srs / model from outputs/<lang>/<srs>/<model>/runs/<id>.json."""
    out: dict = {}
    try:
        # parts after root: <language>/<srs_stem>/<model_safe>/runs/<file>
        rel = json_path.relative_to(root).parts
    except ValueError:
        rel = json_path.parts
    if len(rel) >= 5 and rel[-2] == "runs":
        out["language"] = rel[-5]
        out["srs"] = rel[-4]
        out["model"] = rel[-3]
    return out


def _row(rec: dict, path_hint: dict) -> dict:
    cfg = rec.get("config") or {}
    tok = rec.get("tokens") or {}
    code = rec.get("code") or {}
    tests = rec.get("tests") or {}
    dafny = rec.get("dafny") or {}
    cert = rec.get("certification") or {}
    pass_at = cert.get("aggregate_pass_at") or {}

    # Per-stage wall time: the "dafny" stage is the verification stage; "certify" is certification.
    stage_secs = {s.get("name"): s.get("seconds", "")
                  for s in (rec.get("stages") or []) if isinstance(s, dict)}

    return {
        "run_id": rec.get("run_id", ""),
        "timestamp": rec.get("timestamp_utc", ""),
        "status": rec.get("status", ""),
        # path is authoritative for the matrix layout; JSON body is the fallback.
        "language": path_hint.get("language") or rec.get("language") or cfg.get("language", ""),
        "srs": path_hint.get("srs") or (Path(rec["srs"]).stem if rec.get("srs") else ""),
        "stack": rec.get("stack") or cfg.get("stack", ""),
        "model": path_hint.get("model") or rec.get("model", ""),
        "total_seconds": rec.get("total_seconds", ""),
        "tokens_in": tok.get("input", ""),
        "tokens_out": tok.get("output", ""),
        "tokens_total": tok.get("total", ""),
        "llm_calls": tok.get("calls", ""),
        "cost_usd": rec.get("cost_usd", ""),
        "code_files": code.get("files", ""),
        "code_loc": code.get("lines_of_code", ""),
        "test_features": tests.get("features", ""),
        "test_cases": tests.get("cases", ""),
        "dafny_n_features": dafny.get("n_features", ""),
        "dafny_n_verified": dafny.get("n_verified", ""),
        "dafny_verification_rate": dafny.get("verification_rate", ""),
        "dafny_axioms": dafny.get("n_proved_with_axioms", ""),
        "verification_seconds": stage_secs.get("dafny", ""),
        "certification_seconds": stage_secs.get("certify", stage_secs.get("certification", "")),
        "cert_n": cert.get("n", ""),
        "pass@1": pass_at.get("pass@1", ""),
        "case_pass_rate": cert.get("aggregate_case_pass_rate", ""),
        "n_tested_frs": cert.get("n_tested_frs", ""),
        "n_proved_features": cert.get("n_proved_features", ""),
        "prove": cfg.get("prove", ""),
        "certify": cfg.get("certify", ""),
        "samples": cfg.get("samples", ""),
        "max_cert_loops": cfg.get("max_cert_loops", ""),
        "temperature": cfg.get("temperature", ""),
    }


def _cell_key(row: dict) -> str:
    """Cell identity used to dedupe/update: language/srs/model."""
    return f"{row.get('language','')}/{row.get('srs','')}/{row.get('model','')}"


def _scan_rows(root: Path) -> dict[str, dict]:
    """Build {cell_key -> row} from every run JSON under ``root`` (latest per cell wins)."""
    rows: dict[str, dict] = {}
    for json_path in sorted(root.glob("**/runs/*.json")):
        try:
            rec = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"  skip {json_path}: {e}")
            continue
        row = _row(rec, _derive_from_path(json_path, root))
        row["n_frs"] = _n_frs(row.get("srs", ""))
        row.update(_summary_fields(json_path, rec))
        try:
            key = "/".join(json_path.parent.parent.relative_to(root).parts)  # lang/srs/model
        except ValueError:
            key = _cell_key(row) if any((row.get("language"), row.get("srs"))) else (row["run_id"] or json_path.stem)
        prev = rows.get(key)
        if prev is None or (row.get("timestamp") or "") >= (prev.get("timestamp") or ""):
            rows[key] = row
    return rows


def _write(rows: dict[str, dict], out: Path) -> int:
    ordered = sorted(rows.values(), key=lambda r: (r.get("timestamp") or "", r.get("run_id") or ""))
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(ordered)
    return len(ordered)


def collect(root: Path, out: Path) -> int:
    """Rebuild ``out`` from scratch from every run JSON under ``root``."""
    return _write(_scan_rows(root), out)


def append(root: Path, out: Path) -> tuple[int, int, int]:
    """Non-destructive update: keep every existing row in ``out``, then ADD new cells and
    UPDATE re-run cells (newer timestamp wins) from the scan of ``root``. Existing rows that
    aren't re-scanned are preserved verbatim. Returns (preserved, added, updated)."""
    existing: dict[str, dict] = {}
    if out.exists():
        with out.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                existing[_cell_key(r)] = r
    preserved = len(existing)
    added = updated = 0
    for key, row in _scan_rows(root).items():
        if key in existing:
            if (row.get("timestamp") or "") >= (existing[key].get("timestamp") or ""):
                existing[key] = row
                updated += 1
        else:
            existing[key] = row
            added += 1
    _write(existing, out)
    return preserved, added, updated


def main() -> None:
    ap = argparse.ArgumentParser(description="Aggregate per-run metrics JSON into one CSV.")
    ap.add_argument("--root", type=Path, default=Path("outputs"), help="Dir to scan (default: outputs)")
    ap.add_argument("--out", type=Path, default=Path("experiment_metrics.csv"), help="CSV path (default: experiment_metrics.csv)")
    ap.add_argument("--append", action="store_true",
                    help="Non-destructive: keep existing rows, only ADD new cells / UPDATE re-run "
                         "cells (don't rebuild the whole CSV from scratch).")
    args = ap.parse_args()

    if not args.root.exists():
        print(f"root {args.root} does not exist — nothing to collect")
        return
    if args.append:
        preserved, added, updated = append(args.root, args.out)
        print(f"append -> {args.out}: {preserved} preserved, {added} added, {updated} updated")
    else:
        n = collect(args.root, args.out)
        print(f"wrote {n} run(s) -> {args.out}")


if __name__ == "__main__":
    main()
