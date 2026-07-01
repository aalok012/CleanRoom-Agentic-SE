# CLEANROOM-AGENT

**Turn a Software Requirements Specification (SRS) into a working application in which every functional requirement carries an auditable certification label — `PROVED`, `PROVED-WITH-AXIOMS`, `TESTED`, or `UNCERTIFIED`.**

CLEANROOM-AGENT adapts the *certify-rather-than-debug* orientation of Cleanroom software engineering to LLM-based code generation. Code, tests, and a formal model are derived **independently** from the same frozen requirement-level specification, and each requirement is routed to the strongest available evidence: behavior that can be modeled is **proved** by an external Dafny verifier over all reachable states; behavior that cannot be modeled falls back to **independently generated black-box tests**.

---

## Contents

- [**Approach**](#how-it-works) — the clean-room pipeline and its three key ideas
- [**Install**](#installation) — set up with `uv` and an API key
- [**Quick start**](#quick-start) — one SRS, end-to-end, in a single command
- [**Reproduce the paper**](#reproducing-the-paper) — RQ1 / RQ2 / RQ3
- [**Results**](#results) — headline numbers
- [**Benchmark**](#benchmark) — the 10 SRS subjects
- [**Repository layout**](#repository-layout)

---

## How it works

CLEANROOM-AGENT is built on three ideas:

1. **Independent derivation (the clean-room property).** From one frozen, requirement-indexed specification, the Code Agent, Test Agent, and Proof Generator each work in isolation. The Code Agent **never sees the tests**; the Test Agent **never sees the code**. They meet only at certification, so evidence is not produced by the same judgment that produced the code.

2. **Route each requirement to its strongest check.** Model-layer behavior (state invariants) is cast into a **Dafny state machine** and discharged by an external verifier over all reachable states. Effectful behavior (databases, frameworks, sessions) that the verifier cannot reach is sent to **independent black-box tests**. Proof certifies what testing cannot.

3. **Per-requirement auditable labels.** Every functional requirement exits with a label recording *how* it was established — `PROVED`, `PROVED-WITH-AXIOMS`, `TESTED (pass@k)`, or `UNCERTIFIED` — so success and failure are no longer indistinguishable behind a green test suite.

The pipeline stages are: **Spec** (deterministic FR parse + LLM behavioral contracts) → **Dependency** analysis → **Planning** (per-FR, MVC-layered) → **clean-room proof / code / test generation** → **proof-guided + pass@k certification** → optional **controlled recovery** (a separate, reported phase). Full detail: [`docs/methodology.md`](docs/methodology.md).

---

## Requirements

- **Python ≥ 3.11** and [**uv**](https://docs.astral.sh/uv/) for environment management.
- An LLM API key — **OpenRouter** (recommended; all paper runs used it) or **OpenAI**.
- For the **proof track**: the [**Dafny**](https://github.com/dafny-lang/dafny) verifier on your `PATH`.
- For the **Java / Spring** target: a JDK + Maven. For **JavaScript / Express**: Node.js.

## Installation

```bash
# 1. clone, then create the environment from the locked dependencies
uv sync

# 2. provide an API key (OpenRouter routes to every model in the study)
echo 'OPENROUTER_API_KEY=sk-or-...' > .env
#   (alternatively: OPENAI_API_KEY=sk-... for the OpenAI endpoint)
```

## Quick start

Run the full pipeline on a single specification and print where the per-requirement audit labels land:

```bash
./run_example.sh
```

By default this proves + certifies the smallest subject (`Human.xml`, 2 FRs) with DeepSeek in Python. Override anything via environment variables:

```bash
MODEL=openai/gpt-5.1 LANG=java SRS="data/srs/dineout_srs.xml" ./run_example.sh
```

Or call the pipeline directly:

```bash
uv run python run_pipeline.py data/srs/Human.xml \
  --model deepseek/deepseek-v3.2 --language python \
  --prompt-strategy mot --prove --certify
```

Key flags: `--language {python,java,javascript}`, `--prompt-strategy {baseline,cot,mot}`, `--prove` (proof track), `--certify` (pass@k track), `--model` (any OpenRouter/OpenAI id). Artifacts, a run report, and per-run metrics JSON are written under `--output-dir` (default `outputs/`).

---

## Reproducing the paper

All reported numbers are aggregated from per-run metrics with [`scripts/collect_metrics.py`](scripts/collect_metrics.py) and archived under [`results/`](results/).

**RQ1 — Effectiveness (full pipeline vs. Baseline, all models).**
```bash
# full clean-room pipeline: every SRS × every model × 3 languages
uv run python run_pipeline.py <srs> --model <model> --language <lang> --prove --certify
# direct-generation baseline (contract-free, no proof, no recovery)
uv run python run_baseline.py <srs> --model <model> --language <lang>
```

**RQ2 — Prompting strategy on a cost-constrained model (DeepSeek).**
```bash
uv run python scripts/run_cot_experiment.py          # Chain-of-Thought arm
uv run python scripts/run_mot_matrix_parallel.py     # Module-of-Thought arm
uv run python scripts/compare_three_way.py           # ZS vs CoT vs MoT → results table
```

**RQ3 — Overhead.** Token/time overhead per functional requirement is derived from the same `experiment_metrics.csv` (pipeline vs. baseline rows).

The `--prompt-strategy` flag selects which prompt variant each stage uses: `baseline` (zero-shot), `cot` (`*_cot.j2`), or `mot` (`*_mot.j2`), resolved by [`src/cleanroom/utils/prompt_renderer.py`](src/cleanroom/utils/prompt_renderer.py).

---

## Benchmark

Ten real-world SRS documents from the PURE requirements corpus and additional specifications, spanning **2 – 54 functional requirements** (176 total), each generated to Java, Python, and JavaScript:

| Subject | Domain | Subject | Domain |
|---|---|---|---|
| `Human.xml` | minimal (2 FRs) | `Event Management.xml` | event system |
| `2009 - video search.xml` | video search | `TRADING SOFTWARE.xml` | trading |
| `0000 - gamma j.xml` | management | `kinmail_srs.xml` | messaging |
| `0000 - cctns.xml` | command & control | `dineout_srs.xml` | reservations |
| `foodsaver.xml` | food-rescue platform | `Shoten_SRS.xml` | multi-feature (54 FRs) |

Sources live in [`data/srs/`](data/srs/).

---

## Repository layout

```
.
├── run_pipeline.py          # full clean-room pipeline (single SRS)
├── run_baseline.py          # direct-generation baseline
├── run_example.sh           # one-command end-to-end demo
├── src/cleanroom/
│   ├── agents/              # spec · dependency · planning · code · test · dafny · recovery · evaluation · baseline
│   ├── targets/             # python / java-spring / js-express code targets
│   └── utils/               # prompt rendering, Dafny marshalling, packagers, metrics
├── data/srs/                # the 10-SRS benchmark
├── scripts/                 # metrics collection + RQ2 experiment drivers
├── results/                 # archived metrics CSVs + consolidated spreadsheet
└── docs/                    # methodology, run records, API usage, Dafny workflow
```


```

## License

Released under the [MIT License](LICENSE).
