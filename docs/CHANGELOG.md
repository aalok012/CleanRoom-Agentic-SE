# Changelog

A step-by-step log of every change made to the Agentic Cleanroom project.
Newest entries go at the top. Each entry records **what** changed, **why**, and
**how** (the concrete files/commands), so the history is a readable audit trail.

The format loosely follows [Keep a Changelog](https://keepachangelog.com/).
Categories used: `Added`, `Changed`, `Fixed`, `Removed`, `Docs`.

---

## How to read / add entries

Each dated section is one unit of work. Within it, list the individual steps in
the order they were performed:

```
## YYYY-MM-DD — short title

### Added | Changed | Fixed | Removed | Docs
- **Step 1 — <what>.** Why: <reason>. How: <files touched / command run>.
- **Step 2 — <what>.** ...
```

Keep each step small and concrete so anyone can follow the change after the fact.

---

## 2026-06-29 — SRS reader: enrich thin flat-list IEEE SRS (Event Management / Trading)

### Fixed
- **`build_tagged_pdf_ieee_features` now harvests functional bullets from *all* functional sections, not just the single anchor section, when a Tagged-PDF IEEE SRS collapses to ONE feature.** Why: the two newest SRS — Event Management and Trading Software — are thin student-template docs that state their real functionality across several sections (`Product Functionality`, `Functional Requirements`, `User Interfaces`), but the reader only extracted the one section literally anchored as "Functional Requirements"/"System Features". Result: Event=5 FRs and Trading=6 FRs, dropping the register/post-event/CRUD/admin operations (Event §2.2) and the login/signup/forgot-password/buy-sell-order use cases (Trading §4.1 + traceability matrix). Running the matrix on those would exercise a thin slice of each spec. How: new helpers `_collect_functional_bullets()` (a sticky section-context tracker that flattens the doc to a leaf stream, keeps a `functional` flag on by section title via `_IEEE_FUNC_SECTION` / off via `_IEEE_NONFUNC_SECTION`, handles the split `Lbl`number + `LBody`title header quirk, and collects `LBody`/bulleted-`P` items ≥12 chars) and `_enrich_flat_ieee()` (merge anchor FRs + harvested bullets, de-dupe by normalized text, emit one feature per requirement — the small-proof granularity matching `_split_lone_feature`). Gated to fire **only when the IEEE branch yields exactly one feature**, so multi-feature docs (Shoten 17 feat/54 FRs, G16) are untouched. Result: **Event 5→12 FRs/feat, Trading 6→12 FRs/feat; all other SRS identical** (cctns 7, gamma 6, video 7, Human 2, Shoten 54, dineout 26, foodsaver 37, kinmail 13). Note: this broadens Trading beyond the earlier "6/6 verified" stance (which counted only the §3.1 Features list) to include the UI-behavior use cases.

---

## 2026-06-28 — Pipeline: opt-in stage-level checkpoint / `--resume`

### Added
- **Per-stage checkpointing in `run_pipeline.py` so a failed run resumes from the failed stage instead of re-spending earlier stages' tokens.** Why: `run_pipeline` only wrote its IR at the very end, so any failure (e.g. a transient proof/cert error on a 26-feature SRS) meant re-running the whole expensive sequence. How: new helpers `_save_ckpt` / `_load_ckpt` / `_ckpt_path` write `outputs/<stem>_ckpt.json` after **every** completed stage (`spec, dependency, planning, proof, code, test, certification`), capturing the enriched `ir`, the `metrics` (incl. the per-stage timing/token table) and a full snapshot of `GLOBAL_METRICS` (input/output tokens + per-call records) so resumed token totals and cost stay accurate. Writes are atomic (`*.json.tmp` → `replace`). Each stage is wrapped in an `if "<stage>" in done:` skip-branch that reconstructs the locals it would have produced — the proof tier re-derives `proved_*` from `ir['generated_dafny']` + `metrics['compile']` and re-scaffolds the on-disk Dafny project (mkdir + copy kernel, **no tokens**). New `--resume` flag (and `RunConfig.resume`) controls *loading* the checkpoint; checkpoints are always *written*. A fully-completed run clears its checkpoint. Verified token-free: save/load round-trip restores `GLOBAL_METRICS` accounting and the completed-stage set.

---

## 2026-06-28 — SRS reader: Tagged-PDF (Acrobat SaveAsXML) support for foodsaver

### Fixed
- **`_strip_ns` no longer crashes on comment / processing-instruction nodes** (`src/cleanroom/agents/spec_agent/tools/srs_reader.py`). Why: `foodsaver.xml` is an Acrobat "SaveAsXML" export whose root carries `<?xpacket?>` PIs; lxml gives those a *callable* `.tag`, and `read_tree`'s `_strip_ns(child.tag)` raised `TypeError: ... not a container`. How: `_strip_ns` now returns `""` for any non-str tag, so iterators over mixed children skip non-elements.

### Added
- **`build_tagged_pdf_usecase_features(root)` — new additive reader branch for `<TaggedPDF-doc>` exports.** Why: foodsaver is a Tagged-PDF logical tree (`Part > Sect > {H1..H6, P, L, Table}`) matching none of the existing shapes, so it parsed to zero features. How: scopes to the "3. Specific Requirements" subtree, flattens it to an ordered block stream, and splits on the `3.1.<n> <Title>` use-case marker. Each use case's following body prose (Description/Actor/Trigger/Conditions/Exceptions) becomes a single `REQ-1`. Wired into `read_features` after the PEPPOL branch and before the last-resort module builder, so the other 6 SRS are untouched.

### Fixed
- **Tagged-PDF reader was MERGING ~11 use cases into their predecessors (caught reviewing the run checkpoint).** Why: the Acrobat export is inconsistent — it tags *some* use-case titles as `<H4>` headings but leaves others (3.1.4, 3.1.6, 3.1.12, 3.1.14, 3.1.16, 3.1.22, 3.1.23, 3.1.25, 3.1.29, 3.1.32, 3.1.33) as plain `<P>` text inside the previous use case's section. The first cut split only on `<H4>`, so those 11 got swallowed into the preceding feature's body and never became top-level features (so planning/codegen skipped their endpoints — e.g. "Add food post", "Reserve Food"). How: the builder now splits on the `3.1.<n>` marker **wherever it appears** — heading or a short standalone paragraph (a length guard rejects long body lines that merely cite a section number) — with lists/tables flattened as opaque blobs so inner cells don't double-count. Also de-duplicates the source's two `3.1.10` sections (`3.1.10` Report a user + `3.1.10_2` Edit profile) so feature ids stay unique. Result: foodsaver → **37 features / 37 FRs** (was 26); all 11 recovered, ids unique; other 6 SRS unchanged (cctns 7, gamma 6, video 7, Human 2, dineout 10/26, kinmail 13).

---

## 2026-06-28 — LLM client: bounded timeout + automatic retries

### Added
- **Per-request `timeout` and `max_retries` on the `ChatOpenAI` client** (`get_llm()` in
  `src/cleanroom/utils/llm_client.py`). Why: a deepseek kinmail run crashed at the Dafny proof
  stage with `json.decoder.JSONDecodeError` — OpenRouter returned a half-delivered / non-JSON
  body (transient, likely rate-limiting under concurrent runs), and with no timeout/retry it
  killed the whole pipeline run. How: new env-tunable helpers `_llm_timeout()`
  (`CLEANROOM_LLM_TIMEOUT`, default 120s — generous enough for the proof stage's long reasoning
  responses, bounded enough to catch hangs) and `_llm_max_retries()` (`CLEANROOM_LLM_MAX_RETRIES`,
  default 3) feed `timeout`/`max_retries` into the client, so transient timeouts/429/5xx/hung
  bodies are retried instead of aborting the run. Verified the client picks up both values and
  honors env overrides (token-free).

---

## 2026-06-28 — consolidate API usage into one ledger + fix totals bug

### Fixed
- **`_parse_history_rows` / `_normalize_history_line` off-by-one** (`src/cleanroom/utils/usage_log.py`).
  History rows are 12 cells (current) / 10 cells (legacy), but the parser only matched 11/13, so it
  parsed ZERO rows — cumulative totals always reset to just the latest run ("runs logged | 1" despite
  hundreds of history rows). Changed the length checks to 12 (current) and 10 (legacy). Cumulative
  totals now accumulate across every row.

### Changed
- **Merged `API_USAGE.md` (2026-06-21..24) + `API_USAGE_2.md` (2026-06-26..28) into a single
  `API_USAGE.md`** covering the full history from the beginning (219 runs; corrected cumulative
  totals: 7,878 calls, 40.7M tokens, $80.13). Re-pointed `DEFAULT_USAGE_LOG` back to `API_USAGE.md`
  so all future runs append to the one ledger. Removed `API_USAGE_2.md`. Why: the deliberate
  2-file split (frozen historical + active) was confusing and, combined with the totals bug, made
  the cumulative numbers meaningless. How: merged via the module's own `_collect_history_lines` /
  `_render_document` so the format stays append-compatible; verified the consolidated file
  round-trips (219 rows parse back; a dry append correctly yields 220).

## 2026-06-28 — video search: split a lone multi-requirement feature

### Changed
- **`build_fr_features()` now splits a SINGLE collapsed feature into per-requirement features**
  via new helper `_split_lone_feature()` (`src/cleanroom/agents/spec_agent/tools/srs_reader.py`).
  Why: video search parsed to just 1 feature ("Torrent Search") holding all 7 FRs, so the Dafny
  proof was one oversized all-or-nothing state machine that weaker models (deepseek/gpt) could
  not discharge — verification rate stuck at 0. How: the guard fires ONLY when the document
  yields exactly one feature with >1 requirement, so multi-feature SRS that share this branch
  (dineout, gamma, Human) are returned untouched and their existing results stand. Verified:
  video search 1→**7 features**; dineout 10, gamma 6, Human 2, cctns 7, kinmail 13 all unchanged.

## 2026-06-28 — kinmail: split UserClass actor-groups into per-requirement features

### Changed
- **`build_userclass_features()` now emits one feature per `<Requirement>`, not one per
  `<UserClass>`** (`src/cleanroom/agents/spec_agent/tools/srs_reader.py`). Why: kinmail's 13 FRs
  were collapsed into just 2 "features" (the two `<UserClass>` actor blocks), producing oversized
  single-state-machine Dafny proofs that almost never verified — `verification_pass_ratio` was 0
  for most models/languages and only swung to 1.0 when a top-tier model (gemini) discharged both
  giant proofs. The baseline pipeline, which extracts ~9 features for kinmail, verified far better
  on identical inputs (up to 9/9), confirming feature granularity as the cause. How: each
  `<Requirement>` becomes its own feature — id from the `id` attr, name from `<Title>`, text from
  `<Desc>`, owning `<UserClass>` name kept as `description` (actor context); added a duplicate-id
  guard. The SRS XML is intentionally untouched (input data; fix belongs in the deterministic
  reader). Verified `python -m src.cleanroom.agents.spec_agent.tools.srs_reader data/srs/*.xml`:
  kinmail 2→**13 features**; cctns 7, gamma 6, video-search 1, Human 2, dineout 10 all unchanged.

---

## 2026-06-27 — collect_metrics: per-SRS FR count, and FIX cell-dropping dedup bug

### Added
- **`n_frs` column** (after `srs`) — number of functional requirements per SRS from the
  deterministic `SRSReader` (cctns 7, gamma-j 6, video-search 7, Human 2, dineout 26, kinmail 13).
  Same value for every row of a given SRS; filled even for failed cells.

### Fixed
- **`scripts/collect_metrics.py` was dropping cells.** It deduped rows by `run_id`
  (`timestamp-srs`, no model), so parallel cells of the same SRS finishing in the same second
  collided and overwrote each other — `experiment_metrics.csv` had 58/72 cells, `baseline_metrics.csv`
  40/72. Now dedupes by the **cell identity** (language/srs/model from the path), keeping the latest
  run per cell. Both CSVs now contain all **72 rows (24 per language)**.

### Verified
- Per-cell `tokens_total` cross-checked against run-JSON `tokens.total`, the per-stage token sum,
  and `full_ir` metrics across all 144 run JSONs — 0 discrepancies. Failed (402) cells correctly
  show `tokens_total=0` (died before spending tokens).

---

## 2026-06-27 — Add the 8 headline summary metrics as columns in the metrics CSV

### Changed
- **`scripts/collect_metrics.py`** now emits `verification_pass_ratio, test_case_pass_ratio,
  avg_input_token, avg_output_token, total_time, avg_verification_iter, avg_test_iter, PassVer@1`.
  Why: these run-report headline metrics weren't in the CSV (the per-run JSON doesn't store them).
  How: per run JSON, read the authoritative pre-computed `metrics.summary` from the cell's
  `<stem>_full_ir.json` (exactly what `run_pipeline._compute_summary` wrote); fall back to the
  always-available token/time/case-rate fields from the run JSON when full_ir is absent.
- Rebuilt `experiment_metrics.csv` (72 rows). avg_input/output/total_time populated for all 72;
  the FR-level ratios are blank only for the 3 failed cells (no full_ir). Java rows now carry
  verification_pass_ratio / PassVer@1 / avg_verification_iter even though their pass@k was skipped
  (no Maven oracle). Values verified against the per-cell run reports (e.g. dineout/python/gpt-4.1
  = 0.4615).

---

## 2026-06-27 — Baseline pipeline (contract-free naive flow) + separate metrics

### Added
- **Step 1 — `run_baseline.py`** — a standalone NAIVE pipeline (does not touch run_pipeline.py).
  Per cell: (1) LLM extracts features from the raw SRS (`agents/baseline/prompts/extract_features.j2`,
  pydantic structured output); (2) LLM writes code per feature DIRECTLY
  (`generate_code_naive_{python,java,js}.j2`) with a fixed `feature_<slug>(payload)` binding
  convention; (3) Dafny proof **1 round, no loop** (reuses `DafnyAgent(max_rounds=1)` via a minimal
  features→`planning.contracts` shim that maps FR text into `contract.response`); (4) UNPROVED
  features get a naive test (`generate_tests_naive_*.j2`) that is RUN against the code; (5) records
  the SAME metric shape via `record_run` into `outputs/baseline/<lang>/<srs>/<model>/runs/`.
- **Step 2 — `utils/baseline_oracle.py`** — runs the generated tests: python `pytest`, javascript
  `node --test` (Node built-in, no npm), java `javac` compile-check per feature pair (matches the
  full pipeline's Java oracle). Returns (passed, total) → mapped to `pass@1`/`case_pass_rate`.
- **Step 3 — `run_baseline_matrix.sh`** — 3 languages × 6 SRS × 4 models, parallel-by-model,
  idempotent skip, `MATRIX_MODELS` override. Output `outputs/baseline/...`; collected into a
  SEPARATE `baseline_metrics.csv` via the existing `scripts/collect_metrics.py` (schema aligns).

### Verified
- Smoke per language: python oracle 6/9, java 5/5 (compile), js runs `node --test` (0/8 — a genuine
  naive-mismatch signal: code & tests invent different field names with no shared contract).
  `baseline_metrics.csv` builds with verification_rate + pass@1 + cost populated.

### Notes / caveats (by design)
- Baseline `pass@1` = *test-file pass rate* (a DIFFERENT oracle than the full pipeline's structured
  pass@k) — comparable in spirit, not numerically identical. Lives in `baseline_metrics.csv`,
  separate from `experiment_metrics.csv`.
- "Fully contract-free" makes code/tests bind only by naming convention → expect low pass rates;
  that is the intended baseline contrast with the full pipeline.

---

## 2026-06-26 — Third language target: JavaScript (Node/Express + SQLite), mirroring the Python stack

### Added
- **Step 1 — `targets/js.py` (`JsTarget`)** + registered in `targets/__init__.py`
  (`get_target` returns it for `language=="javascript"`). Mirrors the FastAPI/web pattern:
  Express + SQLite app, Jest tests, in-process executable oracle. Like Java, it ships no
  Dafny-core adapter in v1 (proof tier still runs for the verification metric).
- **Step 2 — `utils/js_tooling.py`** (`node_available()` gates the oracle, like `java_available()`)
  and **`utils/js_packager.py`** (`write_js_sources`: writes each FR module as `.js` + an
  Express `app.js` with route auto-discovery + a `db.js` SQLite key/value store mirroring the
  Python adapter's AppState + `package.json`).
- **Step 3 — Prompts** `agents/code/prompts/generate_code_express.j2` (one pure, stdlib-only
  CommonJS module per FR, function named per contract, single `args` object param, `throw` on
  precondition failure) and `agents/test/prompts/generate_tests_jest.j2` (Jest module + the
  canonical structured `cases`).
- **Step 4 — `run_case_js` + `_JS_RUNNER_SCRIPT` in `agents/evaluation/runner.py`**: a Node
  subprocess loads the generated module and calls the function directly (no Express/DB/`npm`),
  deep-compares JSON (`eq`) or checks a throw (`raises`). The JS analog of the Python `run_case`.

### Changed
- **Step 5 — `config.py`**: `LANGUAGES` gains `javascript`; `from_args` resolves its stack to
  `express` and `prove_target` to `py` (compiled cores are unused for JS, and verification_rate is
  target-independent, so this avoids any dafny-JS-compile risk).
- **Step 6 — `run_pipeline.py`**: added the `javascript`/`express` branches (language banner,
  `code.language="JavaScript"` label, `Jest` test-framework label) and `express` to `--stack`
  choices; **`TestAgent.write_files`** writes `feature_<id>.test.js` for JS. Metrics/run-records are
  unchanged (language-agnostic), so JS records the SAME metrics as python/java.

### Verified
- End-to-end without the LLM: config wiring, `get_target("javascript")`, `write_js_sources`, and
  the Node oracle on a hand-written function — `eq` pass=True, `eq` mismatch=False, `raises`=True;
  both prompts render; agents construct; `run_pipeline` imports. node v22 + npm 10 present.

### Tooling
- **Step 7 — Run the matrix for JS**: `./run_matrix.sh javascript express` (4 models in parallel
  per SRS) → `outputs/matrix/javascript/...`, folded into `experiment_metrics.csv` (`language=javascript`).

---

## 2026-06-26 — SRS reader: support two more SRS schemas (cctns, kinmail)

### Added
- **Step 1 — `build_userclass_features()` in `srs_reader.py`.** Why: `kinmail_srs.xml`
  uses a `<SRS><FunctionalRequirements><UserClass id name><Requirement id><Title>/<Desc>`
  schema that no existing branch understood → 0 features → every cell crashed at the Code
  Agent. How: each `<UserClass>` becomes a feature, each `<Requirement>` an FR (id from the
  attribute, text from `<Desc>`).
- **Step 2 — `build_module_section_features()` in `srs_reader.py`.** Why: `0000 - cctns.xml`
  is a `req_document` but its section is titled "Description of the Modules and Functional
  Requirements" (not the exact "Functional Requirements" the reader keys on), with each
  module's requirement as prose in `<text_body>`. How: a last-resort branch that finds a
  section whose title *contains* "functional requirements" (excluding non-functional) and
  treats each child `<p>` module as a feature (prose body → `<id>.REQ-1`). `walk()` inspects
  the node itself, not just children, so a top-level modules section is matched.

### Changed
- **Step 3 — Wired both into the `read_features()` fallback chain** (after FR-section and
  SystemRequirements; userclass before peppol; module-section last). Both are **purely
  additive** — only reached when all prior branches return 0 features, so the SRS that
  already parsed are provably untouched.

### Verified
- **Step 4 — Parsed all 6 SRS.** cctns 0→**7** features, kinmail 0→**2** (13 FRs); the 4
  working SRS unchanged (gamma j 6, video search 1/7, Human 2, dineout 10/26). Confirmed via
  `SpecAgent.run` (full IR build) and live in the running pipeline (cctns cell logged
  "Features : 7"). Safe to edit mid-batch because working files short-circuit earlier.

### Added (tooling)
- **Step 5 — `rerun_cells.sh`** to backfill a single SRS's 4-model group into the matrix
  layout without rebuilding the CSV (the main collector folds them in). Used to re-run the
  cctns Python cells that failed before the fix; kinmail Python (later group) and both Java
  phases auto-pick-up the fix.

---

## 2026-06-26 — Experiment matrix runner + unified metrics CSV

### Added
- **Step 1 — Added `scripts/collect_metrics.py`.** Why: there was no single place
  to compare runs — metrics lived as scattered per-run JSON and markdown ledgers.
  How: walks `outputs/**/runs/*.json` (the per-run records written by
  `src/cleanroom/utils/run_record.py`), flattens each into one row, dedupes by
  `run_id`, and rebuilds `experiment_metrics.csv` at the repo root. Idempotent
  (full rebuild each call), stdlib-only (`csv`/`json`/`pathlib`). Derives
  language/srs/model from the path `outputs/<lang>/<srs>/<model>/runs/...` and
  falls back to the JSON body so older flat layouts still aggregate. Columns
  cover timing, tokens, cost, code/test counts, Dafny verification rate, and
  certification pass@1 / case-pass-rate.
- **Step 2 — Added `run_matrix.sh`.** Why: collect benchmark data across the full
  SRS × model matrix hands-off, reusable per language. How: fully sequential
  nested loop over every `data/srs/*.xml` × the Frontier-mix models
  (`openai/gpt-5.5`, `google/gemini-3.1-pro-preview`, `anthropic/claude-sonnet-4-6`,
  `deepseek/deepseek-v4-pro`). Each cell runs into an isolated
  `outputs/<language>/<srs_stem>/<model_safe>/` with its own `--output-dir`,
  `PIPELINE_LEDGER_FILE`, and `run.log`; flags `--prove --certify --max-cert-loops 4`.
  A failing cell logs FAIL and the batch continues (partial metrics still recorded).
  Rebuilds the unified CSV after every cell. Phase-1 default is `python fastapi`;
  reuse for Java via `./run_matrix.sh java spring`. Mirrors the `tr '/:.' '___'`
  model-naming and `PIPELINE_LEDGER_FILE` conventions from `run_parallel.sh`.

### Verified
- **Step 3 — Ran the collector against existing run JSONs.** Aggregated 11 prior
  runs; completed runs populate all rich columns (code LOC, Dafny rate, pass@1,
  cost), failed runs degrade to blank cells without crashing.

### Known limitations
- JS/MERN is not yet a supported pipeline target (`LANGUAGES = ("python", "java")`).
  `run_matrix.sh` accepts language as an arg, but the JS phase needs a pipeline
  target added first.

---

## 2026-06-26 — Spring Boot Dafny-core adapters (proved features ship in the Spring build)

Made `--prove --stack spring` actually **ship** the translated Dafny: proved features whose
Dafny `dafny translate java` succeeded are now staged into the Spring Maven build and exposed
through a thin `@RestController` adapter (the Java analog of the FastAPI Dafny-core adapter),
and are excluded from pass@k. Previously the translated Java was produced but left unused in
the proof dir.

### Added
- **Step 1 — Target adapter hooks** in [src/cleanroom/targets/base.py](src/cleanroom/targets/base.py):
  `adapter_file_path(feature_id)` (default Python `controllers/f<fid>_adapter.py`) and
  `stage_cores(app_dir, project_dir, modules)` (default = FastAPI's `stage_dafny_cores`). Why:
  let each target own its adapter path + core-staging layout instead of hard-coding the Python
  one. `SpringBootTarget` ([spring.py](src/cleanroom/targets/spring.py)) overrides
  `adapter_template` → `generate_adapter_spring.j2`, `adapter_file_path` →
  `controllers/F<fid>Adapter.java`, `stage_cores` → Java staging; plain `JavaTarget` gets a
  no-op `stage_cores` (its adapter path is never taken).
- **Step 2 — `stage_dafny_cores_java`** in [src/cleanroom/utils/dafny_project.py](src/cleanroom/utils/dafny_project.py).
  Why: get the translated cores onto the Maven compile path. How: replicates each
  `out/<module>-java/**.java` at its package-relative path under `src/main/java`, **skipping a
  destination that already exists** — that dedupes the `dafny` runtime that every
  `--include-runtime` core bundles, so javac never sees a duplicate class.
- **Step 3 — `generate_adapter_spring.j2`** [prompt](src/cleanroom/agents/code/prompts/generate_adapter_spring.j2).
  Why: write the Spring glue over the proved core. How: one `@RestController` per feature, no
  business logic (every transition goes through `<pkg>.__default.Apply/Normalize`), documents
  Dafny's Java-backend calling conventions (`__default`, `create_<Ctor>`, `DafnySequence`/
  `DafnyMap`, `BigInteger`), in-memory state (v1, no DB), verbatim `@PostMapping` routes.
- **Step 4 — Code Agent adapter wiring** in [src/cleanroom/agents/code/agent.py](src/cleanroom/agents/code/agent.py):
  adapter path now comes from `target.adapter_file_path`, and the prompt context carries the
  Java core package (`module`/`core_java_package`) + a per-contract `route`.

### Changed
- **Step 5 — Pipeline adapter routing** in [run_pipeline.py](run_pipeline.py): `adapter_mode`
  is now true for `fastapi` OR `spring`; for Spring only `proved ∩ proved_compiled_ids` become
  adapters+`cert_skip` (a proved-but-untranslated feature would leave its adapter with no core
  to call and the build-check compiles the whole project, so it safely falls back to normal
  codegen + cert). Staging now goes through `target.stage_cores`; the Spring branch stages the
  Java cores into the Maven project and records `dafny_cores`. The certification sample writer
  ([evaluation/agent.py](src/cleanroom/agents/evaluation/agent.py)) routes staging through
  `self.target.stage_cores` too, so each sample app boots with its cores.
- **Step 6 — Robustness fix:** the adapter context now coalesces a present-but-`None`
  behavioral contract (`c.get("contract") or {}`) — previously `.get("contract", {})` returned
  `None` and the FastAPI/Spring adapter templates raised `'None' has no attribute 'get'`.

### Verified
- Token-free: target/adapter-hook routing, `prove_target=java` for spring, the
  proved∩compiled gating, `stage_dafny_cores_java` (incl. shared-runtime **dedup** across two
  cores + missing-core reporting), Spring adapter prompt rendering with the agent's real
  context, and end-to-end `generate_adapter` (fake LLM) → spring packager placement (correct
  sub-package, core call survives packaging). `py_compile` clean across all touched modules.
- **Not run live** (host has no `dafny`/`mvn`): an actual `dafny translate java` + `mvn compile`
  of a staged core + adapter is the remaining live check. The LLM-written adapter glue is the
  fragile part (see [[cleanroom-adapter-glue-gap]]) — the Spring build-check oracle is exactly
  what surfaces any core/adapter mismatch.

---

## 2026-06-26 — Spring Boot web stack for the Java target

Added a Spring Boot web stack under `--language java`, as the Java analog of the Python
`fastapi` stack: per-FR `@RestController`s generated in isolation, then assembled
**mechanically** into a runnable Maven project via Spring component scanning (so the
Code/Test isolation guarantee is preserved). Selected with `--language java --stack spring`.

### Added
- **Step 1 — `SpringBootTarget`** in [src/cleanroom/targets/spring.py](src/cleanroom/targets/spring.py).
  Why: route the Spring stack through the existing `LanguageTarget` dispatch rather than
  branching inside agents. How: subclass of `JavaTarget` overriding `code_template`
  (`generate_code_spring.j2`), `test_template` (`generate_tests_spring.j2`), `oracle_name`
  (`spring-build`), `package_sample` (Maven project), `run_case` (build-check), and
  `oracle_available` (mvn+JDK).
- **Step 2 — Stack-aware `get_target(language, stack)`** in
  [src/cleanroom/targets/__init__.py](src/cleanroom/targets/__init__.py). Why: one language
  (java) now has two stacks. How: returns `SpringBootTarget` for `(java, spring)`, else
  `JavaTarget`/`LanguageTarget`. Updated the three callers (code/test/evaluation agents) to
  pass their `stack`.
- **Step 3 — Spring code prompt** [generate_code_spring.j2](src/cleanroom/agents/code/prompts/generate_code_spring.j2).
  Why: emit Spring Web REST handlers, not plain Java. How: one `@RestController` per FR, no
  `package` line (the packager injects it), in-memory state (no JPA in v1 → self-contained,
  compile-clean), deterministic `@PostMapping("/{route}")`, `ResponseStatusException(400)` on
  precondition failure. Threaded a deterministic `route` into the Code Agent's render context
  (`_route_from_path`).
- **Step 4 — Spring test prompt** [generate_tests_spring.j2](src/cleanroom/agents/test/prompts/generate_tests_spring.j2).
  Why: JUnit5 + `@SpringBootTest`/MockMvc tests. How: structured `cases` stay the canonical
  oracle (status 400 for `raises`); `test_source` is a MockMvc class for human use.
- **Step 5 — `spring_packager`** [src/cleanroom/utils/spring_packager.py](src/cleanroom/utils/spring_packager.py).
  Why: assemble isolated controllers into a buildable app. How: writes `pom.xml`
  (spring-boot-starter-parent 3.3.4, web+test, Java 17), `Application.java`
  (`@SpringBootApplication` component-scanning `com.cleanroom.app`), `application.properties`,
  and each FR's class into its OWN sub-package `...gen.g<fr_slug>` so identically-named
  classes from isolated generations never collide. Mechanical only — strips any stray
  `package` line and injects the real one; no program logic.
- **Step 6 — Build-check oracle** `run_case_spring` in
  [src/cleanroom/agents/evaluation/runner.py](src/cleanroom/agents/evaluation/runner.py) +
  [src/cleanroom/utils/maven_tooling.py](src/cleanroom/utils/maven_tooling.py). Why: a clean
  `mvn compile` proves the isolated controllers assemble into a well-typed Spring app. How:
  runs `mvn -B -q compile` once per sample dir (cached across the sample's cases, like the
  `javac` compile-check), gated by `spring_oracle_available()` (mvn + JDK present) so
  certification SKIPS gracefully when the toolchain is absent — exactly like the `javac`/Dafny
  tiers. In-process MockMvc HTTP execution is a documented follow-up.

### Changed
- **Step 7 — CLI/config wiring.** Why: let users pick the stack. How: `--stack` choices now
  include `java`/`spring` ([run_pipeline.py](run_pipeline.py)); `RunConfig.from_args` resolves
  the Java sub-stack (`spring` if asked, else plain `java`) ([src/cleanroom/config.py](src/cleanroom/config.py));
  run_pipeline honors `stack` for java, labels the stack/test-framework, prints the
  `mvn spring-boot:run` command, and records `runnable_app`.

### Verified
- **Step 8 — Token-free smoke checks.** Routing, config resolution, packager layout (incl.
  duplicate-class collision avoidance + bogus-package stripping), Jinja rendering of both new
  prompts, well-formed `pom.xml`, and graceful oracle degradation when `mvn` is absent — all
  pass. (Host has javac/java but not mvn, so the Spring oracle correctly reports unavailable.)

### Known limitations (v1)
- In-memory state only (no JPA/DB); the oracle is a build-check, not HTTP execution. A real
  HTTP oracle (boot + MockMvc) and JPA persistence (needs a JavaParser repair layer mirroring
  the FastAPI packager) are follow-ups. The Dafny-core adapter and recovery loop remain
  Python-only, so Spring inherits `JavaTarget`'s `NotImplementedError` on those paths.

---

## 2026-06-24 — Delete standalone baseline; per-agent ON/OFF switches on the pipeline

Replaces the separate `run_baseline.py` with composable per-agent flags on `run_pipeline.py`,
so any "arm" (including a baseline) is just a flag combination over the SAME harness, contracts
(task spec), oracle, and metric code — the correct setup for a controlled ablation. Required
agents (Spec, Planning, Code) are the irreducible spec→code task and have no switch.

### Removed
- **Step 1 — Deleted `run_baseline.py`, `output_baseline/`, and `dineout_srs_run_baseline_report.md`.**
  Why: the standalone baseline used a different oracle/metric path (confounds) and produced an
  inaccurate `PassVer@1=0.10` (untestable interactive code, decoupled vacuous Dafny proofs). How:
  removed the files; verified nothing imports `run_baseline`.

### Added
- **Step 2 — Per-agent switches in `RunConfig`** (`src/cleanroom/config.py`): `run_dependency`,
  `run_test`, `run_recovery` + `agents_enabled()`; `from_args` maps `--dependency/--test/--recovery`
  and forces recovery→0 loops when off or under `--baseline`. Why: one switch per optional agent.
- **Step 3 — CLI flags** (`run_pipeline.py`): `--dependency/--no-dependency`, `--test/--no-test`,
  `--recovery/--no-recovery`; converted `--prove` and `--certify` to symmetric
  `BooleanOptionalAction`. Added an "Agents: …=on/off" banner at run start.

### Changed
- **Step 4 — Stage gating** (`run_pipeline.py`): `--no-dependency` injects a valid EMPTY graph via
  `_inject_empty_dependency` (Planning still runs; features independent); `--no-test` skips test
  generation (certification, if on, synthesizes ephemeral tests). `--baseline` kept as a preset
  (proof OFF, recovery OFF, regex deps, temp 0) but now expressed through the same switches.

### Tests
- **Step 5 — Verified**: full suite 66 passed; offline flag→config mapping check confirms
  full / minimal / cert-no-recovery / baseline arms resolve correctly.

---

## 2026-06-24 — Headline run-metrics are all FR-level now

### Changed
- **`_compute_summary` reports every ratio at FR granularity** (the FR is the atomic
  independently-certifiable unit; the per-FR pass@k already used it, but proof/PassVer were
  feature-level, so the headline numbers mixed denominators). How: `verification_pass_ratio` =
  |FRs of proved features| / total FRs; `PassVer@1` = |FRs of proved features ∪ FRs passing pass@1|
  / total FRs (a proved feature certifies ALL its FRs; union dedupes overlap);
  `avg_verification_iteration` is FR-weighted (each FR inherits its feature's proof rounds).
  Certification now stores `pass_at_1_fr_ids` (from `cert.frs`) instead of feature ids. Tests
  rewritten to FR-level synthetic data; suite 66 passed.

## 2026-06-24 — Drop the redundant `<stem>_ir.json` dump from pipeline runs

### Changed
- **`SpecAgent.run` writes `_ir.json` only when `output_dir` is given.** Why: the per-stage spec
  dump is a strict SUBSET of the final `full_ir.json` (each stage writes the whole running IR, so
  ir ⊂ contracts ⊂ dependency ⊂ planning ⊂ full_ir) — pure duplication in a full run. How:
  `output_dir: Path | None`; `run_pipeline` Stage 1 now passes `output_dir=None`. Standalone
  `spec_agent/cli.py` still writes it. Suite: 66 passed.

## 2026-06-24 — Cross-agent audit: de-bias schemas/prompts for python | fastapi | java

Read every agent's schema + prompt and made them correct/parameterized for all three targets.
Most were already target-agnostic (spec contract is explicitly stack-agnostic; dependency is
language-neutral; code + test prompts dispatch via the language target; certification/dafny
schemas are neutral). Two real biases fixed:

### Changed
- **Planning had no Java branch.** Why: `plan_feature.j2`'s TARGET STACK was `fastapi` vs
  `else=plain Python`, so a `--language java` run (stack="java") was told "plain Python". How:
  added a `java` branch, and reframed the signature as the CANONICAL language-neutral interface
  (Python syntax) that codegen realizes in the target language — updated `FRPlan.signature` /
  `Contract.signature` descriptions to match.
- **Test schema was Python-named.** Why: `FeatureTests.pytest_source` held the JUnit class on a
  Java run, and `expected_json`'s description hardcoded `ValueError`. How: renamed
  `pytest_source → test_source` (all refs in `test/agent.py` + both test prompts), generalized its
  description (pytest for Python/FastAPI, JUnit5 for Java), and generalized the `raises` example to
  name the per-target exception. Suite: 66 passed.

### Changed
- **`infer_fr_deps.j2` sharpened.** Why: the most error-prone rule ("a cross-reference is not a
  dependency") was only described, never shown, inviting false-positive edges. How: added a worked
  NEGATIVE example beside the positive one, and reworded the DIRECTION block from "source/target"
  to the actual structured-output field names (`id` / `prerequisite_ids`) so the model fills the
  schema directly. No code change; suite still 66 passed.

## 2026-06-24 — Code-agent prompts: de-bias across stacks (Python/Java parity)

### Changed
- **Java codegen prompt brought to parity with Python.** Why: `generate_code_java.j2` was thinner
  than `generate_code.j2`, making Java a second-class citizen. How: added the same
  contract-adherence framing ("implement EXACTLY this contract, nothing beyond it"), full
  prerequisites guidance (don't call update/setup from read paths), exact-output matching, and
  direct-map-key reading — Java-correct equivalents of the Python rules.
- **All code-agent templates now route through the target.** Why: `generate_adapter.j2` and
  `regenerate_with_feedback.j2` were hardcoded in `code/agent.py`, i.e. silently Python-only — a
  latent bias if ever run for Java. How: `LanguageTarget.adapter_template()` /
  `feedback_template()` (base returns the Python prompts); `JavaTarget` overrides them to raise
  `NotImplementedError` (adapter = FastAPI-only, recovery = Python-only in v1) so nothing silently
  falls back to a Python prompt. `code/agent.py` renders via `self.target.*`.
- Tests: target routing + Java-refusal + Java-prompt parity (prereqs/error-mode). Suite: 66 passed.

## 2026-06-24 — Configurable, multi-language pipeline (Python + Java) via CLI

Make the pipeline versatile: choose the target **language** (python | java) and configure
**every knob via the CLI** — a separate model per stage, pass@k, samples, stack, prove/certify.
Java produces Java code + JUnit tests and (with a JDK) compile-checks them. Built in three
phases behind a clean target abstraction so the Python path is unchanged.

### Added
- **Step 1 — `RunConfig` (`src/cleanroom/config.py`).** Why: one object holding every knob,
  populated from argparse, threaded through `run()`. How: dataclass with per-stage models
  (`spec/dependency/planning/code/test/proof/cert`), `language`, `stack`, `samples`, `k_values`,
  prove/certify; `from_args()` (java pins its own stack; `--prove-target` follows the language).
- **Step 2 — Per-stage model selection.** Why: a mixed-model run (e.g. cheap spec, strong code)
  prices correctly via the existing `estimate_cost_by_model`. How: `run()` builds a separate
  `get_llm(model=...)` per agent instead of one shared client; new flags `--spec-model …
  --cert-model`, plus `--language`, `--k`.
- **Step 3 — `LanguageTarget` abstraction (`src/cleanroom/targets/`).** Why: keep all
  language-specific choices (templates, packaging, oracle) in one place. How: base class *is* the
  Python behavior; `JavaTarget` overrides. `CodeAgent`/`TestAgent`/`CertificationAgent` take a
  `language` and dispatch the codegen/test template and the oracle through `self.target` instead
  of branching on `stack` inline (Python output unchanged).
- **Step 4 — Java target.** Why: the new capability. How: `targets/java.py`; prompts
  `generate_code_java.j2` (plain Java class per contract, stdlib only) + `generate_tests_junit.j2`
  (JUnit5); `utils/java_packager.py` (write `<PublicClass>.java`); `utils/java_tooling.py`
  (`java_available`/`junit_jar` — mirrors `dafny_available`); `run_case_java` in
  `evaluation/runner.py` (v1 oracle = `javac` compile-check; full JUnit execution deferred behind
  `$JUNIT_JAR`). Certification skips gracefully when no JDK; recovery loop stays Python-only.

- **Step 5 — Headline run-metrics summary.** Why: surface the research metrics in one organized
  block at the end of every run (and in the run report). How: `_compute_summary` + `_print_summary`
  in `run_pipeline.py` emit `verification_pass_ratio`, `test_case_pass_ratio`, `PassVer@1`
  (= (proved + pass@1) / total features), `avg_verification_iteration` (mean Dafny rounds),
  `avg_test_iteration` (1 + recovery passes), `avg_input_token`, `avg_output_token`, `total_time`.

- **Step 6 — `PassVer@1` is a set UNION, not a sum.** Why: `PassVer@1` = features certified by
  proof OR pass@1, over all features. The first cut summed `n_proved + n_pass@1`, which
  double-counts a feature that is both proved and passes pass@1 (possible when proved features
  aren't skipped from the test track — non-adapter stacks) and can exceed 1.0. How: thread the
  proved feature ids + pass@1 feature ids into the summary and compute `|proved ∪ pass@1| / total`.

### Tests
- **Step 7 — `tests/test_config.py`, `tests/test_targets.py`, `tests/test_summary.py`.** Config
  mapping, registry, Python template parity, Java prompt render, java packaging, a `javac`
  compile-oracle test (`skipif(not java_available())`), the summary metric definitions, and a
  PassVer@1 union/dedup test. Full suite: 64 passed.

### Non-goals (v1)
- Java web framework (Spring), a Java Dafny-core adapter, and executing the generated JUnit per
  case (needs a JUnit jar + JSON marshalling) are follow-ups.

## 2026-06-24 — Default certification to pass@1 only; finish dead `revise()` removal

### Changed
- **Step 1 — pass@1 is the only default metric.** Why: generating 3 samples just to
  compute pass@3 burns 3× the tokens, and the pipeline standardized on pass@1 (the
  recovery loop already uses it). How: `CertificationAgent.k_values` defaults to
  `[1]` (was `[1, 3] if n >= 3`); `--samples` default `3 → 1` and `run()` default
  `5 → 1`. Multi-sample estimates still possible via explicit `k_values`/`--samples`.

### Removed
- **Step 2 — Deleted the orphaned `revise()` path.** Why: commit a6d0ca0 removed
  `generate_code_revision.j2` but left `CodeAgent.revise()` + its test referencing the
  now-missing template (the suite's only failure). `revise()` had zero callers since the
  verify→revise loop was dropped. How: removed `revise()` from `code/agent.py` and
  `test_generate_code_revision_j2` from `tests/test_template_alignment.py`. Suite: 48 passed.

## 2026-06-24 — Recovery loop (re-prove + test-informed regen) at Stage 4↔6

Adds a last-resort fallback so a feature that fails BOTH formal proof and the
clean-room pass@1 gets one more chance: re-prove it harder, and if it still won't
verify, regenerate its code WITH the failing test cases fed back, then re-certify.
User decisions for this loop: full test feedback (deliberate, contained clean-room
break), configurable cap (`--max-cert-loops`, default 2), and both escalations
(Dafny rounds + code temperature). Failing signal = pass@1 < 1.0.

### Added
- **Step 1 — `CertificationResult.failures`.** Why: the loop needs the failing
  inputs/expected/reason to feed back. How: added the field in
  `src/cleanroom/agents/evaluation/schema/certification.py` and populated it in
  `certify()` (`agents/evaluation/agent.py`) from the existing diagnostics.
- **Step 2 — Test-informed repair prompt.** Why: a regeneration prompt that
  shows the failing cases (the clean-room first pass must NOT). How: new
  `src/cleanroom/agents/code/prompts/regenerate_with_feedback.j2`.
- **Step 3 — `CodeAgent.regenerate_with_test_feedback(...)`.** Why: the ONLY code
  path that may see tests; the clean `generate()` stays untouched. How: new method
  in `agents/code/agent.py` with a loud header marking the contained clean-room
  break; regenerates only the targeted failing features, embedding each FR's
  failing cases.
- **Step 4 — `RecoveryLoop`.** Why: orchestrate (a) escalated re-prove → ship as
  Dafny-core adapter, (b) test-informed regen, (c) re-certify (n=1, pass@1), up to
  the cap. How: new `src/cleanroom/agents/recovery/loop.py` (+ `__init__.py`).
  Escalation: Dafny rounds `6 + 2·i`, code temperature `0.4 + 0.2·i`. Tests are
  NEVER regenerated inside the loop (the oracle stays frozen).
- **Step 5 — Per-feature certification labels.** Why: never overclaim a clean-room
  pass we didn't earn. How: the loop emits `PROVED` / `TESTED (clean-room)` /
  `TESTED (repaired-with-tests)` / `UNCERTIFIED`, surfaced in the run report.

### Changed
- **Step 6 — Wired the loop into `run_pipeline.py`.** Why: run it after Stage 6.
  How: new `--max-cert-loops` flag (default 2; needs `--certify`; 0 disables);
  Stage 6b invokes `RecoveryLoop`, swaps the repaired result/code into the IR and
  metrics, and prints the labels. Added a "Recovery loop" section to the run report.

### Tests
- **Step 7 — `tests/test_recovery_loop.py`.** Why: lock the deterministic
  orchestration offline. How: fake LLM + stubbed `_certify` covering the
  test-informed regen targeting, the pass@1 failing signal, repair→label, and the
  give-up→UNCERTIFIED + escalation schedule. Full suite: 49 passed.

---

## 2026-06-23 — Stronger MVC-classification prompt; drop the keyword fallback

### Changed — `plan_feature.j2` MVC classifier
Rewrote the `mvc_layer` instruction with a Role/Definitions/Data-flow/Example structure: classify
from the behavioral **contract** (stimulus + response), not name keywords; strict separation-of-
concerns definitions for model/view/controller; a data-flow line (Controller → Model → View);
a primary-effect tie-breaker (state change → controller even if it also reads; pure read → view;
bare entity store → model); and three worked examples. Made the FastAPI `TARGET STACK` block map
each layer to a concrete artifact (model=SQLAlchemy, controller=APIRouter handler, view=read
endpoint/serializer). This fixes mis-tags like 4.1 ("Place Order" — a create) being labelled `view`.

### Removed — the deterministic keyword classifier
`MVC_KEYWORDS` + `classify_layer` deleted (the prompt is now the sole classifier; the Literal-typed
`mvc_layer` field already constrains output). `_normalize_layer` now just defaults invalid output to
`controller`. Restored `_LAYER_DIR` (the model→models/ directory map — not a classifier, still used
for file paths). Fixed the resulting `NameError`. Suite **45 passed**.

---

## 2026-06-23 — Remove the LLM Verification Agent entirely

The LLM "Verification Agent" was a reasoning-only reviewer (not a real verifier). Removed it so the
pipeline has one honest verification story: the Dafny proof track. Code is now generated and either
proved (Dafny) or tested (pass@k) — no LLM "review" middle layer.

### Removed
- Deleted `src/cleanroom/agents/verification/` (agent.py, loop.py, schema, `verify_contract.j2`).
- `run_pipeline.py`: dropped `--verify`/`--verify-rounds`/`--verify-model`/`--verify-passes`, the
  Stage 4b block, the `verification` metrics + report section, and the `generate_and_verify` path
  (code is now just `code_agent.generate` or the adapter split).
- `CertificationAgent`: dropped `verify*` params, the `VerificationAgent`/`generate_and_verify`
  imports, and the verify branch in `_collect_samples`.
- Removed the stale `test_verify_contract_j2` template test.
- README/diagrams/flags + `run_record.py` de-referenced the agent; `run_record` now persists the
  `dafny`/`compile` metrics (and a Dafny proof-tier section) instead of `verification`.

Suite **45 passed**. Pipeline stages are now: Spec → Dependency → Planning → [4a Prove] → Code →
Test → [6 Certify].

---

## 2026-06-23 — De-brand: remove the "lemmafit" name from submitted artifacts

For the research submission: strip the literal name "lemmafit" from `src/`, `README.md`, `docs/`
(dev logs CHANGELOG/RUN_RESULTS kept as honest history). **Labels/comments/filenames only — no
technical content changed**, so the proof pipeline behaves identically (system prompt 6931→6891
chars: only headings differ; the Dafny examples, proof tactics, kernel code, and contracts are
byte-identical). Renamed `skills/lemmafit-{dafny,proofs}.md` → `skills/dafny-{patterns,proofs}.md`
(updated `_load_skill` args + the `=== DAFNY PATTERNS/PROOFS ===` prompt headers); de-branded
docstrings/comments in `agent.py`, `dafny_verify.py`, `dafny_project.py`, `kernel/Replay.dfy`,
tests, docs, README; removed the dead `~/.lemmafit` binary-probe fallback (PATH is checked first, so
behaviour is unchanged). Suite 46.

NOTE (provenance): the `Replay.dfy` kernel and the two `skills/` guidance docs are *adapted from
LemmaFit (MIT)*. The in-code attribution was removed per request, but the derivation should be
acknowledged in the paper — renaming does not make the work original.

---

## 2026-06-23 — Real (vendored) LemmaFit prompts, drop SPEC.yaml, verification-workflow doc

### Fixed — proof-prompt regression
- A previous edit had bloated the global proof prompt (`PROOF_REF`), which **regressed the proof
  count 6→4** in a full run (broke 4.4/4.5/4.8/4.9, several into syntax errors). Root cause:
  wall-specific tactics in the *system* prompt hurt the easy cases.
- Now use the **actual LemmaFit skill prompts verbatim**, vendored in-repo at
  `src/cleanroom/agents/dafny/skills/{lemmafit-dafny,lemmafit-proofs}.md` (the tuned originals that
  achieved 6/10), instead of a hand-condensed paraphrase. `DafnyAgent._build_system` loads them;
  `DAFNY_REF` syntax guardrails kept; wall-specific tactics live ONLY in `_targeted_hint` (fired on
  the matching error during revise). No runtime LemmaFit dependency — the skill text is owned in-repo.

### Removed — SPEC.yaml conversion (vestigial)
- Verification reads the `.dfy` directly; nothing consumed `SPEC.yaml` (no LemmaFit daemon/claimcheck).
  Deleted `utils/dafny_spec.py` + `tests/test_dafny_spec.py`; dropped `GeneratedDafny.spec_yaml`, the
  `proj/SPEC.yaml` write, and the redundant spec-entries section in the Dafny prompt (postconditions
  still flow via the behavioral contracts).

### Added
- `docs/dafny-verification-workflow.md` — full workflow: the inner mechanism (Dafny→Boogie→VCs→Z3,
  proof by refutation, inductive invariant safety), the proof walls, and the DafnyAgent
  generate→verify→revise→compile loop, with diagrams.

Suite **46 passed** (−4 = the removed SPEC.yaml tests).

---

## 2026-06-22 — Fix adapter app-boot failures found by the first real --prove run

The first paid `--prove --certify` FastAPI run (6/10 proved, $0.62, logged correctly with the new
mixed-model cost) failed every pass@k test with `ModuleNotFoundError: No module named
'dafny_marshal'`. Two bugs, both diagnosed + fixed + validated for $0 (n=1 pipeline sample, no LLM):

### Fixed
- **Cert oracle didn't stage the Dafny cores.** `CertificationAgent._write_sample` re-packages each
  sample into a temp app but never copied `dafny_cores/` → proved-feature adapters' `import
  dafny_marshal` crashed at boot → ALL tests failed (even unproved features). Fix: `_write_sample`
  now calls `stage_dafny_cores`; `__init__` takes `dafny_proj`/`dafny_modules`; `run_pipeline` passes
  them when `adapter_mode`.
- **Dafny mangles `_`→`__` in compiled module names.** Adapter imported `F4_1Domain` but Dafny emits
  `F4__1Domain.py` — earlier tests missed it (underscore-free names `Menu`/`Fm`). Fix:
  `generate_adapter` mangles `core_module = f"{module}Domain".replace("_","__")` (the core DIR keeps
  the single underscore). Regression test now uses an underscored module.
- **pytest scoped to `tests/`** (`pyproject.toml [tool.pytest.ini_options] testpaths`) so generated
  test artifacts under `outputs/` no longer pollute the suite.

### Validated (free, n=1 local re-cert with both fixes)
- App boots; all 6 proved adapters import (no `module_`/`_dafny` multi-core collision). Unproved
  features now test for real: 4.3=1.00 (4/4), 4.10=2/4, 4.6=2/4, 4.7=1/3 → aggregate pass@1 **0.25**,
  case rate **0.60** (was 0.00 / all-boot-crash). Remaining failures are genuine code issues
  (empty-DB seeding, validation) — what pass@k should catch. Suite **50 passed**.

---

## 2026-06-21 — Accurate per-model API-usage cost (mixed-model --prove runs)

Goal: a `--prove` run mixes models (gpt-4o-mini for most stages + gpt-4.1 for the proof tier), but
the usage log priced ALL tokens at the last model's rate — under-billing the expensive gpt-4.1
tokens ~9× (a real $0.37 run logged as $0.04). Token COUNTS were always accurate; only the dollar
figure was wrong.

### Added / Changed
- **`estimate_cost_by_model(calls)`** in `cost.py` — groups the per-call records (model already
  recorded in `GLOBAL_METRICS.calls`) by model and prices each at its own rate. Tests: `test_cost.py`.
- **`_finalize_metrics` + `metrics_from_globals`** now use it: `cost_usd` is the exact per-model sum,
  `model` shows all models used (e.g. `gpt-4.1+gpt-4o-mini`), and `cost_by_model` is stored.
- **Run report** prints a per-model cost breakdown for mixed runs.
- Logging path unchanged and confirmed: `append_usage_log` writes to `API_USAGE.md` on BOTH success
  and failure (partial runs still counted), with cumulative totals + per-run history. Suite **50**.

---

## 2026-06-21 — Ship the PROVED logic from Dafny (FastAPI core + thin adapter)

Goal (user decision): for a FastAPI feature that the proof tier verifies, **ship the logic as the
compiled Dafny core** rather than CodeAgent-generated code — the Code Agent writes only the thin
DB/HTTP adapter that calls the proved core. Unproved features fall back to full CodeAgent code +
pass@k (prove-or-test). Reorders the pipeline so the proof tier runs BEFORE codegen.

### De-risked first (free, no LLM)
- Confirmed `dafny translate py` output is callable: `MenuDomain.default__.Apply/Normalize`,
  `Action_*` constructors, `_dafny` runtime bundled in `<module>-py/`. Inputs/outputs are Dafny
  runtime types (`_dafny.Seq` strings via `VerbatimString(False)`, `_dafny.Map` state). Validated a
  full JSON round-trip through a compiled core.

### Added
- **`src/cleanroom/utils/dafny_marshal.py`** — JSON/DB ↔ Dafny-runtime shim (`to_str/from_str`,
  `to_seq/from_seq`, `to_map/from_map`), shipped INTO the app so adapters import it. Lazy `_dafny`
  import so it loads anywhere. Tests: `tests/test_dafny_marshal.py` (incl. a real compile+roundtrip).
- **`CodeAgent.generate_adapter`** + **`generate_adapter.j2`** — writes one FastAPI controller per
  proved feature that imports the compiled core, persists the Dafny Model as serialized state,
  marshals via `dafny_marshal`, and calls `Normalize(Apply(state, action))` — NO business logic.
  Prompt bakes in the validated calling convention + an upward `dafny_cores` discovery header.
- **`CodeAgent.generate(skip_feature_ids=…)`** — omit whole features (those shipping from Dafny).
- **`stage_dafny_cores`** (`dafny_project.py`) — copy each proved `out/<mod>-py/` + the shim into
  `app/dafny_cores/`. Tests: `tests/test_adapter_mode.py`.

### Changed
- **`run_pipeline.py` reorder**: proof tier is now **Stage 4a (before codegen)**. `adapter_mode =
  prove and stack==fastapi and proved>0`: proved features → `generate_adapter` over the compiled
  core; the rest → `generate(skip_feature_ids=proved)`; app packaging stages the cores+shim. pass@k
  skips proved features only in adapter_mode (`cert_skip`). On the python stack `--prove` stays
  proof-only (code/test proceed for all). `--verify` applies only on the non-adapter path.

### Verified
- Full suite **46 passed**. Offline-validated: adapter file placement + prompt conventions, feature
  skipping, core/shim staging, and (with real dafny) the compiled-core round-trip. NOTE: adapter
  *quality* (does the LLM write correct glue for arbitrary Model shapes) is unproven until a real
  `--prove --certify` FastAPI run — that's the paid validation step.

---

## 2026-06-21 — De-LemmaFit + prove-or-test certification tiering

Goal (user decision): drop the LemmaFit runtime dependency (it's a wrapper of Dafny + workflow +
prompts — we already call `dafny verify` directly), and restructure the pipeline so `lemmafit` is
no longer a stack. New shape: generate the MVC app in the best stack, then per feature **prove**
its logic in Dafny where possible (compile proved features to native code) and **test** the rest
with the Testing Agent (pass@k) — a prove-or-test fallback.

### Removed
- **LemmaFit runtime dependency.** Why: the verifier was always just `dafny verify` + a parse; the
  CLI/daemon/dafny2js/npm/`.claude/skills` were workflow, not verification. How: deleted
  `src/cleanroom/utils/lemmafit_project.py` (lemmafit init + npm + dafny2js compile) and the stale
  `scripts/lemmafit_dafny_spike.py`; dropped `--stack lemmafit`.

### Added
- **Vendored kernel** `src/cleanroom/agents/dafny/kernel/Replay.dfy`. Why: own the abstract
  Domain/Kernel features refine, instead of getting it from `lemmafit init`.
- **`src/cleanroom/utils/dafny_project.py`** — `scaffold_dafny_project` (mkdir + copy vendored
  kernel, no CLI/npm) and `compile_dafny` (`dafny translate <target>`, default `py`, replaces
  dafny2js).
- **`extract_axioms`** in `dafny_verify.py` — surfaces `assume {:axiom}` escape hatches
  (`DafnyResult.axioms`), so an unprovable obligation can pass as an explicit, auditable assumption.
- **Proof tier (`--prove`)** + **`--prove-target`** in `run_pipeline.py`: Stage 5b authors+proves a
  Dafny state machine per feature (gpt-4.1), compiles proved features to native code, degrades
  gracefully (no dafny binary → 0 proved → everything tested).
- **`skip_feature_ids`** on `CertificationAgent`: pass@k skips features already PROVED by the tier
  (the test-fallback half of prove-or-test).

### Changed
- **`DafnyAgent`** (`agents/dafny/agent.py`): reads the vendored kernel from `<proj>/dafny/`; prompt
  knowledge owned in-repo (`DAFNY_REF` syntax + new `PROOF_REF` tactics folded in from the former
  LemmaFit skills); no `.claude/skills` reads. System prompt de-branded from "LemmaFit".
- **Renamed** `utils/lemmafit_spec.py` → `utils/dafny_spec.py`; `tests/test_lemmafit_spec.py` →
  `tests/test_dafny_spec.py`.
- **`dafny_verify.py`** binary probe: $DAFNY → PATH → `~/.lemmafit` download (now just a fallback,
  not a requirement).
- **`run_pipeline.py`** flow: removed the `if stack == "lemmafit": … return` branch; `--stack`
  restricted to `auto|python|fastapi`; run-report headings de-branded (proof tier / native compile).

### Verified
- Imports resolve; offline scaffold copies the 155-line kernel; CLI exposes `--prove`/`--prove-target`
  and `--stack {auto,python,fastapi}`. Full suite **41 passed**.

### Fixed (two-pass review against the agreed pipeline)
- **Axiom audit trail propagated.** Why: `extract_axioms` existed but nothing carried `assume {:axiom}`
  through, so a feature passing via an assumed axiom was silently labeled PROVED. How: added
  `FeatureDafny.axioms` (+ `proved_clean` property); `DafnyAgent` populates it from `res.axioms`;
  run output / `metrics['dafny']` / run-report now show "PROVED [N assumed axiom(s)]" and a
  `n_proved_with_axioms` count.
- **All-proved certification reporting.** Why: when every feature was proved, pass@k had nothing to
  test and printed a misleading `pass@1: 0.000`. How: print "(no features to test — all certified by
  the proof tier)" when `cert.frs` is empty; otherwise annotate pass@k with the un-proved FR count;
  added `n_tested_frs`/`n_proved_features` to metrics.
- **Validated against a real Dafny binary** (Homebrew dafny 4.11 on PATH, after removing the LemmaFit
  toolchain): end-to-end scaffold(vendored kernel)+`verify_dafny` of a refining module (3 verified, 0
  errors); `compile_dafny` real `dafny translate py` → `out/<mod>-py`; axiom escape-hatch verifies and
  is recorded. Full suite **41 passed**.

### Ops (LemmaFit removal from the machine)
- Removed `~/lemmafit` scratch project (stale daemon status panel), the global `lemmafit` npm package
  (+bin symlink), and `~/.lemmafit/.dafny2js`. Installed `dafny` independently (`brew install dafny`,
  4.11 on PATH) and removed `~/.lemmafit` entirely. Cleared the stale LemmaFit block from
  `~/.claude/CLAUDE.md`. The pipeline's verifier now finds dafny on PATH.

---

## 2026-06-21 — Remove the python-stack deterministic verification layers

Goal (user decision): with verification moving to the LemmaFit/Dafny track, strip the two
deterministic verdict sources from the python-stack generate→verify→revise loop. Verdicts now
come solely from the LLM `VerificationAgent`; the `verifier=None` path is a no-op pass-through.

### Removed
- **CrossHair symbolic verifier.** Why: deterministic layer no longer wanted on the python
  track. How: `git rm src/cleanroom/agents/verification/crosshair_verify.py` +
  `tests/test_crosshair_verify.py`.
- **Executable canonical-I/O oracle.** Why: the other deterministic source, removed together.
  How: `git rm src/cleanroom/agents/verification/executable.py` (`executable_verdicts`,
  `merge_verdicts`).

### Changed
- **`loop.py` `generate_and_verify`.** Why: drop the two deterministic groups. How: `_verdicts`
  now returns `{}` when `verifier is None`, else the LLM verdicts only; removed crosshair/
  executable imports; aggregate model label `deterministic`→`none`; updated docstrings.
- **`run_pipeline.py`.** Why: the `elif certify and stack == "python"` deterministic-fix branch
  had no verdict source left. How: removed it (and the `crosshair_available` print) so python
  `--certify` falls through to plain `code_agent.generate`.
- **`evaluation/agent.py`.** Why: same — the python per-sample `generate_and_verify(max_rounds=2)`
  branch is now equivalent to plain generate. How: collapsed it into the `else` branch.

### Verified
- Imports resolve (`run_pipeline`, loop, `CertificationAgent`); no dangling refs to removed
  symbols. Full suite **41 passed** (down from 47 — the 6 removed crosshair tests).

---

## 2026-06-21 — LemmaFit/TypeScript stack: Phase 0 (discovery) + SPEC.yaml generator

Goal (user decision): move code generation from Python to a TypeScript stack verified by
**LemmaFit** (formal verification via Dafny, compiled to TS), replacing the CrossHair/executable
verification on that track.

### Changed (extended the Dafny syntax cheat-sheet — recovers syntax-failing features)
- **Added the Dafny forms the LLM kept getting wrong** to `DAFNY_REF` in both
  [dafny/agent.py](src/cleanroom/agents/dafny/agent.py) and
  [scripts/lemmafit_dafny_spike.py](scripts/lemmafit_dafny_spike.py): quantifiers/comprehensions use
  `|` for the range and `::` for the body (never `::` twice); functions are pure (no reassignment;
  `var x := e; <expr>` let-bindings only); every `if` needs an `else`; empty literals are `map[]` /
  `{}` / `[]` (not `set {}`/`map []`). Targeted spike re-runs (gpt-4.1) on the three syntax-failing
  features: **4.4 → VERIFIED** (5 rounds); **4.3** cleared its syntax error and advanced to the
  proof stage (7 verified, residual postcondition obligations); **4.6** cleared the syntax classes
  but then cascaded into deeper type/modeling errors — genuinely hard, like 4.10. So the cheat-sheet
  converts the simple syntax failures; the remaining failures (4.3 proof, 4.6 modeling, 4.10 proof)
  are real difficulty, not syntax. Expected full-run rate ≈ 7/10.

### Fixed (verification false-negatives — true rate is 6/10, not 4/10)
- **Dafny warnings were failing verified code.** `dafny verify`/`dafny translate` exit non-zero on
  STYLE warnings (e.g. `==>` indentation) even when every proof obligation is discharged. The verify
  adapter required `returncode == 0`, so it false-negatived two fully-verified DineOut features
  (4.7, 4.8). Fix: pass `--allow-warnings` and judge by the verification summary, not the exit code,
  in [dafny_verify.py](src/cleanroom/utils/dafny_verify.py); same `--allow-warnings` on the
  `dafny translate js` step in [lemmafit_project.py](src/cleanroom/utils/lemmafit_project.py).
  Corrected the DineOut run to its true result: **6/10 features verified** (4.1, 4.2, 4.5, 4.7, 4.8,
  4.9) and **6/6 compiled to runnable TS**. The 4 real failures are 3 Dafny **syntax** errors
  (4.3 closeparen, 4.4 else-branch, 4.6 set-comprehension — promptable) and 1 genuine **proof**
  failure (4.10, map-lookup precondition).

### Completed (Phases 1-6 — full LemmaFit/TypeScript pipeline, end to end)
- **`--stack lemmafit` wired through `run_pipeline`.** After Planning, a dedicated branch replaces
  the Python stages 4-6: scaffold a LemmaFit project, generate VERIFIED Dafny per feature, then
  compile to TypeScript. New constant `_DAFNY_MODEL = "gpt-4.1"` (the spikes proved weaker models
  can't discharge the proofs). `--stack` help updated.
- **Packager for the stack.** [lemmafit_project.py](src/cleanroom/utils/lemmafit_project.py):
  `scaffold_lemmafit_project` runs `lemmafit init` (lays down Replay.dfy + skills the DafnyAgent
  reads/verifies against); `compile_dafny_to_ts` appends a standard `AppCore` wrapper to each
  verified module and runs the bundled `dafny2js` to emit a TS client (best-effort). Fixed a
  path bug — dafny2js needs absolute paths when run with `cwd` set.
- **Certification = formal verification rate.** For this stack the Dafny proof IS the
  certification: `metrics['dafny']` reports verified/total + per-feature rounds; `--certify` adds
  the Dafny→TS compile stage. `write_run_report` gained Dafny-verification + TS-compile sections.
- **Runnable output completed.** The compile step now does LemmaFit's full 3-step chain so the
  output is genuinely runnable, not just an adapter: `dafny translate js` → copy to
  `src/dafny/<mod>.cjs` (the compiled verified logic) → `dafny2js --client` → `src/dafny/<mod>.ts`
  (typed adapter importing the .cjs). `scaffold_lemmafit_project` also runs `npm install`
  (best-effort) so a `--certify` run leaves a project you can `npm run dev` directly. Verified the
  4 DineOut features' `.cjs` load cleanly in Node.
- **End-to-end run (DineOut, `--stack lemmafit --certify`, gpt-4.1):** ran the full pipeline —
  **4/10 features formally verified** (4.1, 4.2, 4.5, 4.9) and **4/4 verified → compiled to
  TypeScript** clients via dafny2js; 276k tokens, $0.81, auto-logged to API_USAGE.md (gpt-4.1
  priced correctly). The mutating features that fail (4.3/4.4/4.6/4.7/4.8/4.10) need more
  proof-tactic scaffolding or rounds — the known map-comprehension proof difficulty.

### Added (Phase 3 — Dafny agent + token logging)
- **Stage-3 `DafnyAgent`.** Productionizes the validated spike into a reusable agent:
  [dafny/agent.py](src/cleanroom/agents/dafny/agent.py) `DafnyAgent.generate(ir)` casts each feature's
  FRs into a Dafny `Domain` state machine (one `Action` per FR; BehavioralContract → Inv / guards /
  postcondition lemmas) and runs the generate→`verify_dafny`→revise loop (system prompt = LemmaFit's
  shipped skills + abstract Domain interface + Dafny syntax cheat-sheet; default gpt-4.1). Spec-derived
  only (never reads tests). Schema [dafny/schema/dafny.py](src/cleanroom/agents/dafny/schema/dafny.py).
  Offline tests (fake LLM + real Dafny verifier) [tests/test_dafny_agent.py](tests/test_dafny_agent.py):
  verifies round 1; revises to round 2; reports unverified after budget. Full suite 47 passing.
- **Token logging.** Instrumented `scripts/lemmafit_dafny_spike.py` to auto-append usage to
  API_USAGE.md; added gpt-4o/gpt-4.1 prices + prefix matching to
  [cost.py](src/cleanroom/utils/cost.py); logged the five earlier spikes as `spike-estimate` rows
  (~100k tokens; cost caveat noted in API_USAGE.md).

### Discovery (Phase 0)
- **Installed and inspected LemmaFit** (`npm install -g lemmafit`; `lemmafit init`). Findings that
  shape the build: it is a **Dafny Replay/Redux state machine** (`type Model`, `datatype Action`,
  `predicate Inv`, `Init`/`Apply`/`Normalize`, lemmas `InitSatisfiesInv`/`StepPreservesInv`),
  driven **SPEC.yaml-first** (structured entries: id/req_id/title/group/layer/type/property/module/
  verifiable/guarantee_type/state), compiled to a TS API via `lemmafit add <Name> --target ...`, and
  verified by a daemon. React+TypeScript **greenfield only**, **effect-free only**, Claude-Code-
  oriented. Implication: each FR becomes an `Action`; the BehavioralContract maps to SPEC.yaml
  (precondition→precondition entry, response/postcondition→postcondition entry + ensures lemma).

### Verified (Stage-3 LLM feasibility spike)
- **An LLM can author verifying Dafny via the verify-loop — with a capable model.** Built
  [scripts/lemmafit_dafny_spike.py](scripts/lemmafit_dafny_spike.py): seeds the model with
  LemmaFit's shipped skills + the abstract `Domain` interface, generates a state machine for one
  feature from its spec contracts only (cleanroom), runs `verify_dafny`, and feeds proof errors
  back ≤5 rounds. Results on DineOut FR 4.1: **gpt-4o-mini FAILED** (stuck on a Dafny syntax error,
  0 rounds of progress — too weak); **gpt-4o VERIFIED in 4 rounds** (errors shrank 1→1→1→0 as it
  used the real Dafny feedback). Conclusion: the TypeScript/LemmaFit track is feasible but
  **requires a strong model (gpt-4o class)** — the pipeline's gpt-4o-mini default cannot author
  Dafny. (Caveat: FR 4.1 is a read-only action so its `Apply` is trivial; a mutating feature is the
  next, harder signal.)
- **Mutating-feature spike (FR 4.10 manage-menu, gpt-4o) — graded result.** First run looped on a
  Dafny map-syntax parse error (`gets expected`); adding a **Dafny syntax cheat-sheet** to the prompt
  (map update `m[k:=v]`, removal `m-{k}`, comprehension `map k | k in m && P :: m[k]`, datatype
  records) **fixed all syntax errors** → `5 verified`. But it then stalled on **proof** obligations
  (`function precondition could not be proved` ×8, oscillating across 6 rounds): proving how a
  map-comprehension `Normalize` interacts with map updates needs helper lemmas gpt-4o doesn't write.
  Conclusion: feasibility is **graded by feature complexity** — read-only/simple `Apply` verifies;
  **mutating + map-state features exceed gpt-4o within 6 rounds** and need a stronger reasoning model,
  proof-tactic/helper-lemma scaffolding in the prompt, or an `assumed`-axiom fallback. Syntax issues
  are promptable; map-comprehension proofs are the real wall.
- **Same mutating feature with gpt-4.1 — VERIFIED in 2 rounds.** The proof wall is a model-capability
  issue: gpt-4.1 authored a genuine CRUD state machine for FR 4.10 (`Model = map<string, MenuItem>`,
  Add/Edit/Delete actions with real map updates, an invariant tying keys to item names + non-negative
  prices, a map-comprehension `Normalize`, and a **biconditional postcondition lemma**
  `AddItem_Postcondition`) that Dafny accepts. Verdict for the LemmaFit/TS pivot: **feasible end to
  end with gpt-4.1** — the chain (LemmaFit skills + Domain interface + Dafny syntax cheat-sheet +
  `verify_dafny` revise loop) produces verifying Dafny for both read-only and mutating CRUD features.
  Model requirement is firm: gpt-4o-mini (pipeline default) and gpt-4o are insufficient for mutating
  features; **Stage 3 needs gpt-4.1-class**.

### Added
- **Feasibility spike + Dafny verify adapter (Phase 1/4 de-risk, token-free).** Why: the whole
  pivot hinges on producing Dafny that actually verifies — validate that before building the LLM
  agent. How: scaffolded a real project (`lemmafit init outputs/lemmafit_dineout` + `npm install`,
  which downloads Dafny 4.11 to `~/.lemmafit/.dafny`); confirmed synchronous verification works;
  **hand-authored `PlaceOrder.dfy`** mapping DineOut FR 4.1 to a state machine (`Model`/`Action`/
  `Apply`/`Inv` + `InitSatisfiesInv`/`StepPreservesInv` + a domain postcondition lemma
  `AddDishGrowsOrder`) — **verifies, 10 verified / 0 errors**. Built the reusable Stage-4 core
  [dafny_verify.py](src/cleanroom/utils/dafny_verify.py) (`verify_dafny()` locates the binary, runs
  `dafny verify`, parses pass/fail + error locations to feed the revise loop). Tests:
  [tests/test_dafny_verify.py](tests/test_dafny_verify.py). Confirms the FR→Action→Apply→ensures-lemma
  mapping yields verifiable Dafny; the open risk is now only whether the LLM can author it (Stage 3).
- **SPEC.yaml generator (Phase 1 start).** Why: LemmaFit's first step is SPEC.yaml; our spec stage
  already extracts the needed pre/post/response per FR. How: new
  [lemmafit_spec.py](src/cleanroom/utils/lemmafit_spec.py) `build_spec_yaml(ir)` /
  `build_spec_entries(ir)` emit one `precondition` + one `postcondition` entry per FR (postcondition
  falls back to the response), with a per-feature Dafny `module` name, `depends_on` linked from
  prerequisite FRs, and `state: DRAFT` (the Dafny stage formalizes `property` and flips to
  ADDRESSED). Deterministic, spec-derived (never reads tests/code) → isolation holds. Tests:
  [tests/test_lemmafit_spec.py](tests/test_lemmafit_spec.py). Full suite 42 passing.

## 2026-06-21 — Pin the entity identifier in the contract (Code/Test agree on the key)

### Added
- **Step 1 — `entity_identifier` on the planning contract.** Why: with the two-phase oracle, the
  Test Agent seeded staff by `name` while the Code Agent looked them up by `id`, so edit/delete
  still failed ("ID required" / "not found") — the contract never pinned the entity's key, so the
  two agents diverged (same family as the 4.4 type mismatch). How: added `entity_identifier` to
  `FRPlan` and `Contract` ([planning/schema/plan.py](src/cleanroom/agents/planning/schema/plan.py)):
  the single field that uniquely keys a persisted entity for lookup (e.g. `id`/`name`), empty for
  stateless FRs. The planner LLM produces it
  ([plan_feature.j2](src/cleanroom/agents/planning/prompts/plan_feature.j2) — "pick a key the
  stimulus actually provides on edit/delete"); the agent threads it into every `Contract`.

### Changed
- **Step 2 — Both agents key off it.** Why: code and tests must use the same field. How: the Code
  Agent passes `entity_identifier` into [generate_code.j2](src/cleanroom/agents/code/prompts/generate_code.j2)
  and the revision prompt (fastapi: "look up/store the entity by its `<field>`; don't require an
  identifier the caller doesn't send"); `requirement_for_prompt`
  ([contracts.py](src/cleanroom/utils/contracts.py)) surfaces it to
  [generate_tests.j2](src/cleanroom/agents/test/prompts/generate_tests.j2), whose SETUP rule now
  says the seed call and the main call MUST share the same identifier value. Template tests updated;
  full suite 38 passing.

## 2026-06-21 — Fix FastAPI boot crash: unify same-table models

### Fixed
- **Step 1 — Collapse differently-named models that map to the same table.** Why: a regenerated
  DineOut run crashed every case at boot with `ArgumentError: Trying to redefine primary-key column
  'name' as a non-primary-key column` (pass@1 0.2 → 0.0). Two isolated FRs modeled the `dishes`
  table incompatibly — `DishModel(id PK, name, quantity)` vs `Dish(name PK, classification)` — and
  `extend_existing=True` tried to merge them. `_dedupe_models` only collapses same-CLASS-NAME
  redefinitions, so this slipped through. How: new `_unify_models_by_table` in
  [packager.py](src/cleanroom/utils/packager.py) picks one canonical class per table (prefer the
  `models` layer, then the richest definition), gives it the UNION of all columns with a single
  primary key (`id` if any def has one, else the first declared PK; others demoted), and rewrites
  every other same-table class into an import alias of the canonical. Wired in after
  `_dedupe_models`. Re-certifying the existing code: boot restored, case rate 0.0 → **0.625**.
  Regression test: [tests/test_packager_models.py](tests/test_packager_models.py). Full suite 38 passing.

## 2026-06-20 — Two-phase (seed-then-act) FastAPI certification oracle

### Added
- **Step 1 — Spec-level `setup` on each test case.** Why: the FastAPI cert oracle did a single
  POST against a freshly-created EMPTY database, so stateful happy-paths (edit/delete/cancel/read an
  existing entity) were unpassable and error-cases passed spuriously (everything 404'd before the
  real check ran). How: added `setup_json` to `TestCase`
  ([test/schema/tests.py](src/cleanroom/agents/test/schema/tests.py)) — a JSON array of Arrange
  calls, each `{"inputs": <body>, "route"?: <route>}`, that create the precondition state through
  the API. It is spec-level (API calls with spec-derived inputs), so the cleanroom holds — no table
  or column names ever appear.
- **Step 2 — Two-phase HTTP oracle.** Why: replay the Arrange calls before the Act call against the
  same persistent sqlite file. How: `_HTTP_RUNNER_SCRIPT`/`run_case_http`
  ([evaluation/runner.py](src/cleanroom/agents/evaluation/runner.py)) take a 6th `setup_json` arg,
  POST each setup step in order (default route = the FR's own endpoint), and fail the case at Arrange
  if any setup step returns ≥400; then do the Act POST and assert as before. Verified on the REAL
  generated `manage_staff_records`: "edit existing staff" goes 404→pass, and "delete missing id"
  now 404s for the right reason (data exists, id absent) instead of spuriously.

### Changed
- **Step 3 — Test Agent emits setup.** Why: the agent (spec-only) must declare the Arrange calls.
  How: [generate_tests.j2](src/cleanroom/agents/test/prompts/generate_tests.j2) instructs (fastapi
  only) to populate `setup_json` with create/add calls using the SAME identifiers the main inputs
  reference, to leave it empty for pure-create / state-as-input cases, and to NOT seed an entity a
  "not found" case looks up; the fastapi `pytest_source` replays setup before the main POST.

### Tests
- **Step 4 — Two-phase oracle tests.** New cases in
  [tests/test_fastapi_oracle.py](tests/test_fastapi_oracle.py): a CRUD endpoint's stateful happy-path
  fails without setup and passes with it, and a failing Arrange step is reported as `setup step 0`.
  Full suite 37 passing.

## 2026-06-20 — Deterministic CrossHair verification (python stack)

### Added
- **Step 1 — CrossHair symbolic verifier as a deterministic verdict source.** Why: the
  verification step should not depend on an LLM — CrossHair checks generated code against a
  spec-derived contract by symbolic execution (Z3), with no tests and no model in the loop.
  How: new [crosshair_verify.py](src/cleanroom/agents/verification/crosshair_verify.py) exposes
  `crosshair_verdicts(ir, code, only_fr_ids)` returning the same `ContractVerdict` shape as the
  executable verifier. For each `python`-stack FR it synthesizes a PEP 316 contract from the
  planning signature (a `post:` asserting the declared return type + `raises: ValueError` when
  `error_mode == 'raise'`), injects it into the function's docstring, and runs `crosshair check
  --analysis_kind=PEP316`. It reports two failure kinds: a return of the wrong type, and any
  UNDECLARED crash (KeyError/TypeError/IndexError/…) on some input.
- **Step 2 — Counterexamples abstracted to spec level (isolation-preserving).** Why: a CrossHair
  counterexample carries concrete failing inputs, which must never reach the Code Agent. How:
  `_abstract()` maps each counterexample to a `ContractViolation` describing only the violated
  property and failure kind (exception type / wrong return type), discarding the concrete
  argument values — so the revise loop stays spec-level like the LLM/executable verifiers.

### Changed
- **Step 3 — Wired CrossHair into both verify loops.** Why: every place code is generated and
  revised should get the symbolic check. How: [loop.py](src/cleanroom/agents/verification/loop.py)
  merges `crosshair_verdicts` via `merge_verdicts` in `generate_and_verify` (alongside the LLM +
  executable verdicts) and in `generate_with_executable_fixes` (the no-LLM deterministic path used
  by default for `--certify` on the python stack and by the CertificationAgent per-sample loop).
  `run_pipeline.py` prints whether CrossHair is active for the deterministic fix loop.
- **Step 4 — Gating + graceful degradation.** Why: CrossHair can only symbolically execute pure
  Python, and the solver may be missing. How: `crosshair_verdicts` returns `{}` on the `fastapi`
  stack (DB/HTTP code it cannot analyze) and when the `crosshair`/z3 tool is unavailable, so the
  pipeline never blocks on it. `_z3_env()` auto-discovers a libz3 matching the interpreter (e.g. a
  Homebrew build) when the bundled wheel's architecture differs.
- **Step 6 — Unified the two verify loops into one.** Why: after CrossHair, `generate_and_verify`
  and `generate_with_executable_fixes` shared the same deterministic core and revise loop, differing
  only by the LLM reviewer — duplicated logic that had to be edited twice (e.g. to add CrossHair).
  How: deleted `generate_with_executable_fixes`; `generate_and_verify(ir, code_agent, verifier=None,
  max_rounds=2)` now takes an optional `verifier` (`None` ⇒ token-free deterministic path:
  executable + crosshair only). Updated callers in `run_pipeline.py` and
  [evaluation/agent.py](src/cleanroom/agents/evaluation/agent.py) to call it with `verifier=None`
  and take `[0]`. No behavior change; full suite 35 passing.

### Dependencies
- **Step 5 — Added `crosshair-tool`** (`uv add crosshair-tool`), which pulls `z3-solver`. On this
  x86_64 (Rosetta) interpreter the bundled arm64 z3 wheel mismatches; the verifier falls back to
  the Homebrew x86_64 `libz3` at `/usr/local/opt/z3/lib` via `Z3_LIBRARY_PATH` auto-discovery.

## 2026-06-20 — Auto stack selection + FastAPI HTTP path + slimmer contract

### Removed
- **Step 1 — Dropped `current_state`, `new_state`, `state_invariant` from the behavioral contract.**
  Why: the state/invariant fields bloated the contract and the LLM filled them with vague
  prose that added little over precondition/postcondition. How: removed the fields from
  `BehavioralContract` and `FRContract` in
  [src/cleanroom/agents/spec_agent/schema/ir.py](src/cleanroom/agents/spec_agent/schema/ir.py),
  the matching bullets in [write_contract.j2](src/cleanroom/agents/spec_agent/prompts/write_contract.j2),
  both contract constructions in [spec_agent/agent.py](src/cleanroom/agents/spec_agent/agent.py),
  and the "State transition"/"Invariant" Notes blocks in `_compose_docstring`
  ([planning/agent.py](src/cleanroom/agents/planning/agent.py)). Updated `tests/test_planning_contracts.py`.

### Added
- **Step 2 — Deterministic target-stack classifier.** Why: stateless SRSs (video search) want
  pure functions; stateful CRUD SRSs (DineOut) need a real DB-backed web app — picking the
  wrong one produced fake in-memory state and hardcoded data. How: new
  [src/cleanroom/utils/stack_select.py](src/cleanroom/utils/stack_select.py) votes over
  spec-derived requirement text + preconditions and returns `(stack, reason)`. Verified:
  video search → python (29% stateful), DineOut → fastapi (80%).
- **Step 3 — `--stack auto` (now the default).** Why: select per SRS unless pinned. How:
  `run_pipeline.py` resolves the stack right after contract synthesis, stores `ir["stack"]`,
  and prints the decision; explicit `--stack python|fastapi` overrides.
- **Step 4 — FastAPI HTTP certification oracle.** Why: certifying web-stack code with the
  pure-function oracle was impossible (the original DineOut failure). How: `run_case_http` +
  `route_from_file_path` in [evaluation/runner.py](src/cleanroom/agents/evaluation/runner.py)
  assemble the runnable app and drive it via `TestClient` in a subprocess (200 JSON body for
  `eq`, 4xx for `raises`); `CertificationAgent` selects the oracle by stack and lays samples
  out via `build_runnable_package` for fastapi. New `tests/test_fastapi_oracle.py`.

### Changed
- **Step 5 — FastAPI codegen now emits real HTTP responses + errors.** Why: produce
  app-usable code with no hardcoding/fake state. How: the fastapi branch of
  [generate_code.j2](src/cleanroom/agents/code/prompts/generate_code.j2) (and the revision
  prompt) mandates DB-backed reads/writes, `@router.post("")` with `Body(...)` params,
  JSON return on success, and `HTTPException(4xx)` on failure; `_compose_docstring` emits
  `Raises: HTTPException` for the fastapi stack.

### Fixed
- **Step 6 — FastAPI/SQLAlchemy now installed (root cause #1).** Why: the cert subprocess
  raised `ModuleNotFoundError: fastapi`. How: `uv add fastapi sqlalchemy uvicorn httpx`.
- **Step 7 — Test Agent is now stack-aware (was emitting "vanilla" Python tests for FastAPI).**
  Why: the generated `pytest_source` imported routes flat and called them directly with
  `pytest.raises(ValueError)` — uncallable against the assembled FastAPI app. How: `TestAgent`
  takes `stack`; [generate_tests.j2](src/cleanroom/agents/test/prompts/generate_tests.j2) now
  emits a `TestClient` module that POSTs to the route and asserts `status_code`/`json()`
  (4xx for failures) on fastapi, plain function calls on python; threaded `stack` from
  run_pipeline stage 5 and the `CertificationAgent` fallback.
- **Step 8 — `requirement_for_prompt` now supplies the behavioral-contract fields.** Why: the
  test prompt referenced `r.stimulus`/`precondition`/`response`/`postcondition` and the route,
  none of which were provided — a latent `StrictUndefined` crash in the test stage. How: pulled
  them from `plan['contract']` and added a deterministic `route` (`route_for`) in
  [contracts.py](src/cleanroom/utils/contracts.py), mirroring `evaluation.runner.route_from_file_path`.
- **Step 9 — Packager repairs the two most common FastAPI boot failures.** Why: the assembled
  DineOut app crashed at boot — `NameError: Integer` (Code Agent used a SQLAlchemy/FastAPI name
  it forgot to import) and `InvalidRequestError: Table 'orders' is already defined` (isolated FRs
  declare the same table under different class names). How: added `_ensure_known_imports` (adds/merges
  any referenced-but-unimported well-known fastapi/sqlalchemy/app symbol) and
  `_allow_table_redefinition` (injects `__table_args__ = {"extend_existing": True}` into each model
  declaring a `__tablename__`) to [packager.py](src/cleanroom/utils/packager.py); both are mechanical
  (imports/fixed attribute only, never logic), so isolation holds.
- **Step 10 — Fixed `_ensure_sqlalchemy_imports` NameError in the packager write loop.** Why: the
  build loop called the old name `_ensure_sqlalchemy_imports`, which no longer exists — every
  `build_runnable_package` (and the second boot test) crashed before writing a file. How: renamed
  the call to `_ensure_known_imports` at [packager.py](src/cleanroom/utils/packager.py).
- **Step 11 — FastAPI codegen now uses `Body(..., embed=True)` on every parameter.** Why: with a
  single plain `Body(...)` param FastAPI treats the whole request body as that value, so the HTTP
  oracle's dict-keyed POST (`{"param": value}`) returned 422 for single-parameter endpoints. How:
  changed both [generate_code.j2](src/cleanroom/agents/code/prompts/generate_code.j2) and
  [generate_code_revision.j2](src/cleanroom/agents/code/prompts/generate_code_revision.j2) to mandate
  `embed=True`, making the body `{"<param>": <value>, ...}` for any parameter count. Verified by a
  synthetic single-param endpoint returning `200` through `build_runnable_package` + `TestClient`.

---

## 2026-06-16 — Remove stub LLM mode

### Removed
- **Step 1 — Deleted all stub LLM classes and flags.** Why: always running with real tokens;
  stubs added dead code and confusing `--stub-llm` / `--no-llm` CLI flags. How: removed
  `StubSpecLLM`, `StubDepLLM`, `StubPlanLLM`, `_PROMPT_REQ`, all hint/verb constants, and the
  `--stub-llm` / `--no-llm` args from `run_pipeline.py`. `run()` no longer takes `use_llm`,
  `spec_llm`, `plan_llm`, `dep_llm` params.
- **Step 2 — Simplified `main()`.** Why: clean entry point — just check for API key and run.
  How: `main()` now errors immediately if `OPENAI_API_KEY` is missing instead of silently
  falling back to stubs. `run()` signature is `(srs_path, output_dir, certify, samples)`.

---

## 2026-06-16 — Planning + Code Agent pipeline fixes

### Fixed
- **Step 1 — Always include Returns in docstrings.** Why: contracts with `-> None`
  signatures had no Returns section, making the docstring incomplete for the Code
  Agent. How: added `_infer_return_type(signature)` helper in
  [src/cleanroom/agents/planning/agent.py](src/cleanroom/agents/planning/agent.py);
  `_compose_docstring` now accepts the signature and falls back to inferring the
  return type annotation when the LLM returned an empty `returns` field.

- **Step 2 — Fixed `file_path` inconsistency between Planning and Code agents.**
  Why: `_file_path` was returning `outputs/{project}/code/models/func.py` (hardcoded
  prefix, pluralised layer) but `CodeAgent.write_files` was ignoring that path and
  reconstructing using the raw `mvc_layer` string (`model`, not `models`), so the
  path in the contract never matched the actual file on disk. How: changed
  `_file_path` in `planning/agent.py` to return a clean relative path
  `{layer_dir}/{func}.py` (e.g. `models/func.py`); changed `CodeAgent.write_files`
  in `code/agent.py` to use `output_dir / f.path` directly instead of
  reconstructing. Removed now-unused `project` variable from `plan()`.

### Verified
- **Step 3 — Confirmed Code Agent reads `planning.contracts`** (not the legacy
  `increment_plan`). The code at `code/agent.py:46` already does
  `(ir.get("planning") or {}).get("contracts")`. Updated the CHANGELOG baseline
  note below to reflect this.

---

## 2026-06-16 — Richer Google-style docstrings in Planning contracts

Goal: make each FR contract's docstring contain **summary + Args + Returns +
Constraints + Notes/Prerequisites** (Google style), instead of just a summary
with an NFR list. The LLM supplies the prose (summary, per-arg/return
descriptions); the section structure, NFR Constraints, and prerequisite Notes
stay deterministic.

### Changed
- **Step 1 — Extended the planner schema.** Why: the LLM now needs to return
  structured arg/return descriptions, not one flat string. How: in
  [src/cleanroom/agents/planning/schema/plan.py](src/cleanroom/agents/planning/schema/plan.py)
  added an `ArgDoc` model (`name`, `description`) and replaced `FRPlan.docstring`
  with `summary`, `args: list[ArgDoc]`, and `returns: str`. `Contract` is
  unchanged (still stores the final composed `docstring` string).
- **Step 2 — Updated the design prompt.** Why: tell the model to produce a
  summary, one `args` entry per signature parameter, and a `returns` phrase — and
  to NOT write Constraints/Notes itself (those are added deterministically). How:
  edited [src/cleanroom/agents/planning/prompts/plan_feature.j2](src/cleanroom/agents/planning/prompts/plan_feature.j2).
- **Step 3 — Rewrote `_compose_docstring`.** Why: assemble the Google-style
  docstring with `Args:` / `Returns:` / `Constraints:` / `Notes:` sections, each
  omitted when empty. How: in
  [src/cleanroom/agents/planning/agent.py](src/cleanroom/agents/planning/agent.py)
  rewrote `_compose_docstring(summary, args, returns, nfrs, prereq_notes)` and
  changed the NFR line format to `- <category>: <text>`.
- **Step 4 — Added deterministic prerequisite Notes.** Why: surface FR
  prerequisites in the docstring, referencing each by its designed function name +
  req id (e.g. `Prerequisite: create_lab_test_request (req 2.2.6.6) must have run
  first.`). How: new `_prereq_notes(prereq_ids, designs)` helper in `agent.py`,
  built from the inner `fr_edges`; wired into the `plan()` contract loop.
- **Step 5 — Updated the stub planner LLM.** Why: keep token-free `--stub-llm`
  runs working against the new `FRPlan` shape. How: `StubPlanLLM` in
  [run_pipeline.py](run_pipeline.py) now emits `summary` + `args` + `returns`.

### Verified
- **Step 6 — Ran the front pipeline token-free** (`uv run python run_pipeline.py
  "data/srs/2005 - phin.xml" --stub-llm`): completed, 0 tokens. Spot-checked the
  output `*_planning.json` — docstrings render all sections, including a
  `Prerequisite: ... (req X) must have run first.` Notes block (from `fr_edges`)
  and a `Constraints:` block (from a feature's NFRs).

## 2026-06-16 — Start the changelog

### Docs
- **Step 1 — Created `CHANGELOG.md`.** Why: to document every future change
  step by step in one clear, chronological place. How: added this file at the
  project root alongside `README.md`.
- **Step 2 — Recorded the current baseline (below)** so future entries have a
  reference point for what already existed before logging began.

### Baseline (state of the project when the changelog was started)
This is *not* a change — it is a snapshot of what already existed, summarized
from `README.md` and the existing code:

- **Front pipeline restructured and tested** (stages 1–3 wired in
  `run_pipeline.py`):
  - **[1] Spec** (`src/cleanroom/agents/spec_agent/`) — deterministic XML parse
    + per-feature FR/NFR classification.
  - **[2] Dependency** (`src/cleanroom/agents/dependency/`) — nested graph:
    deterministic outer feature DAG + inner per-FR graph, optional LLM semantic
    edges.
  - **[3] Planning** (`src/cleanroom/agents/planning/`) — one contract per FR
    (signature + docstring + MVC layer + file path + prerequisites).
- **Stages 4–6 exist and are wired** onto `planning.contracts` (`code/`, `test/`,
  `certification/`). `run_pipeline.py` runs them on real-LLM runs; stub runs stop
  after Planning.
- **Isolation guarantee** between Code and Test agents is enforced structurally.

## 2026-06-29 — Fix Shoten FR subsection split (srs_reader)

- **Bug**: `_IEEE_SUBSEC` required whitespace after the section number
  (`\d+\.\d+...\.?\s+`). Shoten's PDF exported two titles as `4.12.View Delivery
  Status` / `4.13.View Account Purchase History` (dot, **no space**), so they were
  not recognized as feature markers. Their `REQ-*` paragraphs were absorbed into
  `4.11 Update Account Information` → only 15 features, with 4.11 wrongly carrying 9
  reqs; features 4.12 and 4.13 were missing.
- **Fix**: separator now accepts a dot OR whitespace:
  `^(\d+\.\d+(?:\.\d+)*)(?:\.\s*|\s+)(.+)$`. Shoten now yields **17 features /
  54 reqs** (4.11/4.12/4.13 each 3 reqs).
- **Verified text-level (not just counts)** against the raw XML for the 5 audited SRS:
  Trading 6/6, G16 5/5, Shoten all 53 source `REQ-N` sentences + 1 feature-intro
  prose, foodsaver all 37 use-case description clauses match source verbatim.
- **Regression**: all other SRS unchanged (cctns 7, gamma 6, video-search 7, Human 2,
  dineout 10/26, kinmail 13). Branch only affects Tagged-PDF IEEE-830 docs.
- **Follow-up**: Shoten experiment-matrix runs predate this and used 15 features —
  re-run to refresh `experiment_metrics.csv` if Shoten numbers are reported.
