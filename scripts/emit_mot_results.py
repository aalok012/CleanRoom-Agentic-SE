#!/usr/bin/env python3
"""Consolidate every MoT cell into ONE results CSV — mot_deepseek_results.csv.

Walks outputs/mot/<srs_stem>/<language>/*full_ir.json (the per-run IR each pipeline writes),
pulls the headline metrics, and writes a single row per (srs, language). Columns mirror
cot_deepseek_results.csv exactly, so it drops straight into compare_three_way.py (which prefers
this file over assembling from outputs). Idempotent: rebuilt from scratch each run.

    python scripts/emit_mot_results.py [--root outputs/mot] [--out mot_deepseek_results.csv]
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LANGS = ["python", "java", "javascript"]

# full_ir metrics.summary key -> output column (matches compare_three_way / emit_cot_results)
SUMMARY_MAP = {
    "verification_pass_ratio": "verification_pass_ratio",
    "test_case_pass_ratio": "test_case_pass_ratio",
    "avg_input_token": "avg_input_token",
    "avg_output_token": "avg_output_token",
    "total_time": "total_time",
    "avg_verification_iteration": "avg_verification_iter",
    "avg_test_iteration": "avg_test_iter",
    "PassVer@1": "PassVer@1",
}
COLUMNS = ["srs", "language", *SUMMARY_MAP.values(), "total_tokens"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=ROOT / "outputs" / "mot")
    ap.add_argument("--out", type=Path, default=ROOT / "mot_deepseek_results.csv")
    args = ap.parse_args()

    rows = []
    if args.root.exists():
        for stem_dir in sorted(p for p in args.root.iterdir() if p.is_dir() and not p.name.startswith("_")):
            for lang in LANGS:
                fir = next(iter((stem_dir / lang).glob("*full_ir.json")), None)
                if fir is None:
                    continue
                try:
                    m = (json.loads(fir.read_text(encoding="utf-8")).get("metrics") or {})
                except (json.JSONDecodeError, OSError):
                    continue
                summary = m.get("summary") or {}
                row = {"srs": stem_dir.name, "language": lang}
                for src, col in SUMMARY_MAP.items():
                    row[col] = summary.get(src, "")
                row["total_tokens"] = (m.get("tokens") or {}).get("total", "")
                rows.append(row)

    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {args.out} ({len(rows)} rows) from {args.root}")


if __name__ == "__main__":
    main()
