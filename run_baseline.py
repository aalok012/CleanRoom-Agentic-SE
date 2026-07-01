#!/usr/bin/env python3
"""Baseline pipeline — a contract-free, naive single-pass alternative to run_pipeline.py.

Flow (NO spec-contract agent, NO dependency/planning agent, NO recovery loop):
  1. LLM extracts features from the RAW SRS text.
  2. LLM writes code for each feature DIRECTLY (naive; one module per feature, a fixed
     `feature_<slug>(payload)` entry so tests can bind — the LLM invents everything else).
  3. Dafny proof tier, 1 round, no revise loop (verification_rate metric).
  4. For UNPROVED features: LLM writes a test file; we RUN it against the code (pytest /
     node --test / javac) and count pass/fail.
  5. Record the SAME metric shape as the full pipeline into <output-dir>/runs/ so
     scripts/collect_metrics.py folds it into a separate baseline CSV.

Usage:
  uv run python run_baseline.py <SRS> --model <M> --language python|java|javascript \
      --output-dir outputs/baseline/<lang>/<srs>/<model>
"""

from __future__ import annotations

import argparse
import re
import time
import traceback
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from pydantic import BaseModel, Field  # noqa: E402

from src.cleanroom.agents.dafny.agent import DafnyAgent  # noqa: E402
from src.cleanroom.llms.callbacks.metric import GLOBAL_METRICS  # noqa: E402
from src.cleanroom.utils.baseline_oracle import run_oracle  # noqa: E402
from src.cleanroom.utils.code_stats import code_stats  # noqa: E402
from src.cleanroom.utils.cost import estimate_cost_by_model  # noqa: E402
from src.cleanroom.utils.dafny_project import scaffold_dafny_project  # noqa: E402
from src.cleanroom.utils.dafny_verify import dafny_available  # noqa: E402
from src.cleanroom.utils.llm_client import DEFAULT_MODEL, get_llm  # noqa: E402
from src.cleanroom.utils.prompt_renderer import PromptRenderer  # noqa: E402
from src.cleanroom.utils.run_record import record_run  # noqa: E402

LANG_EXT = {"python": "py", "java": "java", "javascript": "js"}


# ---- LLM feature-extraction schema (the only structured-output call) -------------
class _FR(BaseModel):
    id: str = Field(description="Requirement id, e.g. '1.1'")
    text: str = Field(description="The functional requirement statement")


class _Feature(BaseModel):
    id: str = Field(description="Feature id, e.g. '1'")
    name: str = Field(description="Short feature name")
    functional_requirements: list[_FR] = Field(default_factory=list)


class _Features(BaseModel):
    features: list[_Feature] = Field(default_factory=list)


def _slug(fid: str) -> str:
    return re.sub(r"[^0-9a-zA-Z]+", "_", fid).strip("_") or "f"


def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9]*\n", "", t)
        t = re.sub(r"\n```\s*$", "", t)
    return t.strip() + "\n"


def _code_paths(language: str, slug: str) -> tuple[str, str]:
    """(code_filename, test_filename) for a feature, per the binding convention."""
    if language == "python":
        return f"feature_{slug}.py", f"test_feature_{slug}.py"
    if language == "javascript":
        return f"feature_{slug}.js", f"feature_{slug}.test.js"
    return f"Feature_{slug}.java", f"Feature_{slug}Test.java"


def run_baseline(srs_path: Path, output_dir: Path, model: str, language: str,
                 prove_rounds: int = 1) -> dict:
    started = time.time()
    renderer = PromptRenderer()
    llm = get_llm(model=model, temperature=0.0)
    ext = LANG_EXT[language]
    app_dir = output_dir / "app"
    app_dir.mkdir(parents=True, exist_ok=True)

    metrics: dict = {
        "srs": srs_path.name, "stack": "naive", "language": language,
        "config": {"language": language, "baseline": True, "prove": True, "certify": True,
                   "samples": 1, "max_cert_loops": 0, "temperature": 0.0, "prove_rounds": prove_rounds},
        "stages": [],
    }

    # 1) LLM feature extraction from raw SRS text.
    srs_text = srs_path.read_text(encoding="utf-8", errors="ignore")
    prompt = renderer.render("extract_features.j2", {"srs_text": srs_text[:120_000]})
    extracted: _Features = llm.with_structured_output(_Features).invoke(prompt)
    features = [f for f in extracted.features if f.functional_requirements] or extracted.features
    print(f"Extracted features: {len(features)}")
    if not features:
        raise ValueError("LLM extracted 0 features from the SRS")

    # Build the minimal ir shim so the Dafny agent can iterate features (FR text -> contract.response).
    ir_features = [{"id": f.id, "name": f.name,
                    "functional_requirements": [{"id": r.id, "text": r.text} for r in f.functional_requirements]}
                   for f in features]
    contracts = [{"fr_id": r.id, "feature_id": f.id,
                  "contract": {"stimulus": "", "precondition": "", "response": r.text, "postcondition": ""}}
                 for f in features for r in f.functional_requirements]
    ir = {"project_name": srs_path.stem, "features": ir_features, "planning": {"contracts": contracts}}

    # 2) Naive code gen — one module per feature.
    code_tpl = f"generate_code_naive_{'js' if language == 'javascript' else language}.j2"
    gen_files = []
    for f in features:
        slug = _slug(f.id)
        reqs = [{"id": r.id, "text": r.text} for r in f.functional_requirements]
        cp = renderer.render(code_tpl, {"feature_id": f.id, "name": f.name, "slug": slug, "requirements": reqs})
        resp = llm.invoke(cp)
        content = _strip_fences(resp.content if isinstance(resp.content, str) else str(resp.content))
        code_name, _ = _code_paths(language, slug)
        (app_dir / code_name).write_text(content, encoding="utf-8")
        gen_files.append({"fr_id": f.id, "feature_id": f.id, "path": code_name,
                          "mvc_layer": "controller", "content": content})
    metrics["code"] = code_stats({"files": gen_files})
    metrics["code"]["language"] = {"python": "Python", "java": "Java", "javascript": "JavaScript"}[language]
    print(f"Generated {len(gen_files)} {language} module(s)")

    # FR count per feature id (for FR-granular verification ratio, like the full pipeline).
    fr_count = {f.id: len(f.functional_requirements) for f in features}
    n_frs_total = sum(fr_count.values())

    # 3) Dafny proof — 1 round, no loop.
    proved: set[str] = set()
    if dafny_available():
        proj = scaffold_dafny_project(output_dir / "dafny_proof")
        gen = DafnyAgent(proj, model=model, max_rounds=prove_rounds).generate(ir)
        proved = {x.feature_id for x in gen.features if x.verified}
        ntot, nver = len(gen.features), gen.n_verified
        n_frs_proved = sum(fr_count.get(fid, 0) for fid in proved)
        metrics["dafny"] = {"model": model, "n_features": ntot, "n_verified": nver,
                            "n_proved_with_axioms": sum(1 for x in gen.features if x.verified and x.axioms),
                            "verification_rate": round(nver / ntot, 3) if ntot else 0.0,
                            # FR-granular: proved_FRs / total_FRs (matches the full pipeline's metric).
                            "n_frs_total": n_frs_total, "n_frs_proved": n_frs_proved,
                            "verification_pass_ratio_fr": round(n_frs_proved / n_frs_total, 4) if n_frs_total else 0.0,
                            "features": [{"feature_id": x.feature_id, "module": x.module,
                                          "verified": x.verified, "rounds": x.rounds,
                                          "axioms": len(x.axioms),
                                          "n_frs": fr_count.get(x.feature_id, 0)} for x in gen.features]}
        print(f"Proved {nver}/{ntot} features ({n_frs_proved}/{n_frs_total} FRs, 1 round)")
    else:
        print("dafny not available — skipping proof tier (all features go to test).")
        metrics["dafny"] = {"model": model, "n_features": len(features), "n_verified": 0,
                            "n_proved_with_axioms": 0, "verification_rate": 0.0,
                            "n_frs_total": n_frs_total, "n_frs_proved": 0,
                            "verification_pass_ratio_fr": 0.0, "features": []}

    # 4) For UNPROVED features: naive test gen + run.
    test_tpl = f"generate_tests_naive_{'js' if language == 'javascript' else language}.j2"
    unproved = [f for f in features if f.id not in proved]
    tested_slugs: list[str] = []
    for f in unproved:
        slug = _slug(f.id)
        reqs = [{"id": r.id, "text": r.text} for r in f.functional_requirements]
        tp = renderer.render(test_tpl, {"feature_id": f.id, "name": f.name, "slug": slug, "requirements": reqs})
        tcontent = _strip_fences(llm.invoke(tp).content)
        _, test_name = _code_paths(language, slug)
        (app_dir / test_name).write_text(tcontent, encoding="utf-8")
        tested_slugs.append(slug)
    metrics["tests"] = {"features": len(unproved), "cases": len(unproved)}

    passed, total = run_oracle(language, app_dir, tested_slugs) if unproved else (0, 0)
    rate = (passed / total) if total else 0.0
    print(f"Tests: {passed}/{total} passed (rate {rate:.3f}) over {len(unproved)} unproved feature(s)")
    metrics["certification"] = {"n": 1, "k_values": [1],
                                "aggregate_pass_at": {"pass@1": round(rate, 4)},
                                "aggregate_case_pass_rate": round(rate, 4),
                                "n_tested_frs": total, "n_proved_features": len(proved),
                                "n_total_tested_features": len(unproved), "pass_at_1_fr_ids": []}

    # 5) Finalize token/cost metrics (same as run_pipeline).
    in_tot, out_tot, calls = GLOBAL_METRICS.snapshot()
    cost, by_model = estimate_cost_by_model(GLOBAL_METRICS.calls)
    metrics["model"] = model
    metrics["total_seconds"] = round(time.time() - started, 3)
    metrics["tokens"] = {"input": in_tot, "output": out_tot, "total": in_tot + out_tot, "calls": calls}
    metrics["cost_usd"] = cost
    metrics["cost_by_model"] = by_model
    return metrics


def main() -> None:
    p = argparse.ArgumentParser(description="Baseline (naive, contract-free) pipeline.")
    p.add_argument("srs_path", type=Path)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--language", default="python", choices=list(LANG_EXT))
    p.add_argument("--output-dir", type=Path, default=Path("outputs/baseline_run"))
    p.add_argument("--prove-rounds", type=int, default=1)
    args = p.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    try:
        metrics = run_baseline(args.srs_path, args.output_dir, args.model, args.language, args.prove_rounds)
        rec = record_run(metrics, status="complete", runs_dir=args.output_dir / "runs",
                         index_path=args.output_dir / "index.md")
        print(f"Recorded: {rec['json']}")
    except Exception as exc:
        print(f"BASELINE FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        in_tot, out_tot, calls = GLOBAL_METRICS.snapshot()
        cost, by_model = estimate_cost_by_model(GLOBAL_METRICS.calls)
        partial = {"srs": args.srs_path.name, "stack": "naive", "language": args.language,
                   "model": args.model, "tokens": {"input": in_tot, "output": out_tot,
                   "total": in_tot + out_tot, "calls": calls}, "cost_usd": cost,
                   "cost_by_model": by_model, "total_seconds": 0.0,
                   "config": {"language": args.language, "baseline": True}}
        record_run(partial, status="failed", runs_dir=args.output_dir / "runs",
                   index_path=args.output_dir / "index.md")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
