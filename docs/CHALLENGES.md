# Challenges — Building the Agentic Cleanroom Pipeline

A record of the real problems hit while building this clean-room, spec-driven code-generation
pipeline (Spec → Dependency → Planning → Proof → Code → Test → Certification → Recovery), why each
one happened, and how it was resolved. Roughly in the order they surfaced. (The early entries
reference a standalone Verification/verify→revise loop that was later removed once certification
became the executable oracle and the recovery loop took over feedback.)

---

## 1. Requirement text never reached the Test Agent (silent data-plumbing bug)

- **Symptom:** the Test Agent produced generic "search endpoint" cases and stapled requirement
  IDs onto them by position, unrelated to the actual requirements. Feature 3.1 certified at
  pass@3 = 0.000.
- **Root cause:** `feature_units` read `r.get("description")`, but the functional-requirement
  field is `text`. Every requirement reached the prompt with an **empty** body, so the model
  only saw the feature *name* and invented plausible tests.
- **Fix:** read `r.get("text") or r.get("description")`, and enrich each requirement with its
  behavioral contract so the oracle is grounded in the spec, not guessed.
- **Lesson:** a one-line field-name mismatch can masquerade as "the LLM is bad at tests." Check
  the data the model actually receives before blaming the prompt.

## 2. Tests invented oracle specifics the spec never stated

- **Symptom:** cases asserted HTTP 400 on empty input, a `{'links': [...]}` shape, dedup,
  trimming — none of it in the requirements.
- **Root cause:** with empty requirement text (#1), the model filled the vacuum; the prompt
  also didn't forbid inventing codes/shapes.
- **Fix:** derive `expected` strictly from the contract's response/postcondition; forbid invented
  codes/shapes; failure cases only when a real precondition exists.

## 3. Clean-room interface drift (the structural tax of isolation)

- **Symptom:** Test Agent guessed `/torrent_search` + `{'links'}`; Code Agent guessed
  `/search_torrents` + a bare list. The strict judge failed the mismatch.
- **Root cause:** isolation means the two agents never agree on an interface unless both anchor
  to a **shared, spec-derived contract**.
- **Fix:** both anchor to the planner's contract (signature/file path), spec-only, so isolation
  holds while interfaces line up.

## 4. The framework (Flask) was fighting the benchmark

- **Symptom:** handlers like `def search_torrents(query: str)` — Flask never passes `query`;
  another used `request` without importing it (`NameError`).
- **Root cause:** forcing a plain function signature into an HTTP handler, plus a huge
  disagreement surface (URL, method, status code, JSON shape, app wiring).
- **Decision:** the goal is a **clean-room code-gen benchmark**, so the target moved from Flask
  to **plain, framework-free Python** (later a FastAPI option). pass@k is designed for pure
  functions; the web layer was noise.
- **Aftershock:** `run_pipeline.py` still defaulted `--stack flask`, so a "both features" run was
  accidentally Flask and reintroduced every issue above. Defaults must match intent.

## 5. The judge graded blind — then crashed

- **Symptom:** unreliable verdicts; after #1, certification threw `UndefinedError`.
- **Root cause:** `judge_feature.j2` printed `{{ r.description }}`, always empty — the judge saw
  only requirement IDs. Renaming the field to `text` turned the empty key undefined, and
  `StrictUndefined` crashed.
- **Fix:** judge prompt renders the real requirement text plus contract clauses — the same
  grounding tests use.

## 6. The behavioral contract was too heavy

- **Symptom:** "sort by clicking column headers" was certified against code that raised "results
  must already be displayed"; functions depended on prior state a black-box call can't set up.
- **Root cause:** the 7-field design-by-contract pushed the planner/code toward **stateful**
  designs and let the model manufacture prior-state preconditions from vague one-liners.
- **Fix:** slimmed to a **pure-function** contract (`stimulus, precondition, response,
  postcondition`) and reframed `precondition` to constrain **inputs**, not prior state.

## 7. pass@k is all-or-nothing — and binary at n = k

- **Symptom:** "16 passed / 5 failed" but the score read pass@3 = 0.000, then 1.000 with failures
  still present.
- **Root cause:** pass@k counts a *sample* only if it passes **every** case; at **n = k** it's
  binary (1.0 once one sample passes everything, else 0.0) — no gradient.
- **Fix:** added a continuous **case pass rate** alongside pass@k, with an explanatory note, and
  the guidance to run **n > k**.

## 8. Duplicate requirements collide across features

- **Symptom:** with two features, 3.2's "no results message" verified as "no implementation
  shown," though the function existed.
- **Root cause:** the same requirement appears in 3.1 and 3.2; the planner derives the file path
  from the function name, so both map to one file and clobber each other.
- **Fix direction:** namespace file paths by feature, or dedupe identical cross-feature
  requirements. The planner prompt now also pushes **distinct function names** per requirement.

## 9. The oracle itself was too weak (the EvalPlus lesson)

- **Symptom:** suspected false positives — thin, plausible implementations passing a lenient LLM
  judge with few NL cases.
- **Root cause:** the judge was **inspection, not execution** (weaker than HumanEval), with low
  coverage.
- **Fix:** pivoted certification to an **executable oracle** — structured cases carry
  `inputs_json`/`expected_json`, and an **isolated subprocess** imports the candidate and runs
  them, scoring per FR. The LLM judge is now a fallback. Requires the JSON-serializable
  plain-Python discipline so functions are importable and callable.

## 10. Self-verification buys almost nothing — independence is the point

- **Problem:** having the Code Agent check its own work shares its blind spots and rationalizes
  mistakes.
- **Design:** a **separate, adversarial Verification Agent** with its own prompt and a **cold
  read**; it **never executes** the code (else it's a tester); it returns **spec-level
  contract-clause violations only** (never test cases), which the Code Agent uses to revise in a
  **bounded loop**.
- **Integration trap:** certification regenerates **n independent samples** and ignores the
  pipeline artifact — so the verify→revise loop had to be a **shared helper used inside the
  certification sample loop** too, or pass@k never moves.
- **Cost:** ≈ n × contracts × rounds × 2 calls; mitigated by per-contract granularity,
  re-verifying only changed files, capped rounds, and opt-in `--verify`.

## 11. The oracle became circular — the Test Agent was copying the answer key

- **Symptom:** scores looked strong but couldn't be trusted; nothing the code was graded on was
  independent of what it was built from.
- **Root cause:** the planner emits a canonical `example_inputs_json` → `expected_return_json`;
  the Code Agent is **shown that exact I/O** and (for the `python` stack) revised in an
  executable-fix loop **until it passes that I/O**; and the Test Agent was instructed to **copy
  the same I/O verbatim** ("never invent inputs or extra cases"). Certification then scored the
  code on those copied cases. So: planner writes `fn(X)==Y` → coder is told `fn(X)==Y` and
  revised until true → scorer checks `fn(X)==Y`. The test set was a single point — the exact one
  the coder was trained on. pass@k measured memorization, not correctness (the EvalPlus
  false-positive problem, now structurally guaranteed).
- **Why it happened:** an over-correction. Earlier the Test Agent invented *mismatched* I/O the
  code couldn't satisfy (#1–#3); forcing an exact copy fixed alignment but deleted all
  independent testing power. The Test Agent became a courier, not a designer.
- **Fix:** `generate_tests.j2` now keeps the canonical case as a single **anchor** (the shown
  example, like a HumanEval docstring example) and additionally requires **2–4 INDEPENDENT cases
  per requirement** that the Test Agent designs itself from the requirement + contract (boundary
  values, empties, alternate valid inputs, extra precondition violations), with expected outputs
  derived from the contract — inputs the coder never saw. A confidence rule discourages guessed
  expectations (which would fail correct code). Now the score measures generalization.
- **Open tension:** independent LLM-derived expectations can be wrong → false negatives. The
  anchor case stays reliable; the independent cases trade some precision for real signal. The
  honest long-term fix is property-based or reference-solution oracles, not a single LLM's
  guess at expected outputs.

## 12. Proof covers the logic, not the running program (the adapter gap)

- **Symptom:** a feature was PROVED in Dafny and shipped green, yet its FastAPI adapter called
  `M.from_json`/`M.to_json` — functions that don't exist in the marshalling shim — and persisted
  the Model under a different DB key per feature, so the proven cross-action invariants never held
  at runtime.
- **Root cause:** Dafny is **effect-free** — it proves pure logic and `dafny translate` emits only
  the executable functions (the invariant and all lemmas are *erased*). The HTTP/DB/marshalling
  glue that connects the proven core to the world is **outside the proof**, and proved features are
  **skipped by certification**, so the glue is never executed by any oracle. A green proof was being
  read as if it covered the endpoint.
- **Fix direction:** keep proof for the logic, but stop treating it as certification of the *wiring*
  — run at least a boot/one-call smoke (or full pass@k) on proved-feature adapters; or generate the
  glue deterministically from the introspectable compiled core instead of by LLM. Documented as the
  adapter-glue gap.
- **Lesson:** a formal guarantee only covers what it formalizes. The proof certified the algorithm;
  nothing certified that the deployed program runs that algorithm on the right shared state.

## 13. Going multi-language (Python + Java) without smuggling in Python bias

- **Symptom:** adding a `--language java` target, it would have "worked" while quietly assuming
  Python everywhere: the planner told Java runs "plain Python", the Code Agent's adapter/recovery
  prompts were hardcoded Python, the Java codegen prompt was a thin afterthought, and the test
  schema field was literally named `pytest_source` while holding a JUnit class.
- **Root cause:** the pipeline grew up single-language, so language/stack assumptions were scattered
  inline (template names, `if stack == 'fastapi' … else (python)` branches, Python-named schema
  fields) rather than behind one seam.
- **Fix:** a `LanguageTarget` abstraction (`src/cleanroom/targets/`) owns every language-specific
  choice — codegen/test template, packaging, and the executable oracle — and the agents dispatch
  through it. The Java target *explicitly refuses* the Python-only adapter/recovery prompts
  (`NotImplementedError`) instead of silently falling back; the planning signature was reframed as a
  **canonical interface in Python syntax** that codegen translates per language; and Python-named
  fields/branches were generalized (`pytest_source → test_source`, a Java branch in planning, a
  per-target `raises` exception).
- **Where it's honest about its limits:** the Java oracle is a `javac` **compile-check**, not
  per-case JUnit execution — a real but partial signal — and it degrades gracefully without a JDK,
  mirroring how the proof tier skips without a `dafny` binary.
- **Lesson:** "supports language X" is easy to fake by bolting X onto a Python-shaped pipeline. Real
  support means a single seam where every language decision lives, and making unsupported paths fail
  *loudly* rather than silently doing the wrong (Python) thing.

---

## Cross-cutting lessons

- **Determinism where it's cheap.** IDs, file paths, dependency order, docstring assembly are
  plain code; the LLM does only genuine interpretation. Most "model" bugs were deterministic
  plumbing bugs (#1, #5, #8).
- **Isolation must be enforced structurally, not by intention.** Every agent's reachable inputs
  are constrained (Code never reads tests; the verifier never reads `generated_tests` and never
  executes). Feedback channels are shaped so they *can't* leak the wrong information.
- **Independence is the source of signal.** A reviewer that shares the author's context (#10) or
  an oracle that shares the author's inputs (#11) both collapse to rubber-stamps. Quality comes
  from a cold, separate view.
- **Match the metric to the artifact.** pass@k assumes pure functions and executed tests; every
  step away (web framework, LLM judge, n = k, copied oracle) degraded the signal. Realigning the
  artifact (plain Python) and the oracle (independent, executed cases) made the score mean
  something.
- **Defaults are part of the design.** A stale `--stack flask` default silently undid a major
  decision. Intent that isn't the default gets forgotten under time pressure.
- **Watch for over-corrections.** Fixing "tests invent garbage" by "tests copy the answer" traded
  one failure mode for a worse, quieter one (#11). Aim for the middle, not the opposite extreme.
- **A guarantee only covers what it formalizes.** Proof certified the logic, not the deployed
  endpoint (#12); "supports Java" can be faked by bolting it onto a Python-shaped pipeline (#13).
  Be explicit about the boundary of every guarantee, and make unsupported paths fail loudly.
