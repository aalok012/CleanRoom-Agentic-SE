# Dafny Verification — Full Workflow

How a feature goes from a spec contract to a **mathematically proved** (or honestly-failed) Dafny
module, covering both the *inner* mechanism (how Dafny actually proves things) and the *outer*
pipeline (how the `DafnyAgent` drives it).

---

## 1. What "verification" means here

Dafny **never runs the code**. Verification is a *proof*, checked at compile time by an automated
theorem prover, that a property holds for **all possible inputs** — not a test that checks a few
concrete cases. Passing means "it is logically impossible to violate this property," which is a
categorically stronger guarantee than any number of passing tests.

---

## 2. The inner mechanism — how Dafny proves

```
 your .dfy (code + specs)
        │
        ▼
   Dafny front-end          resolve types, desugar, infer proof obligations
        │
        ▼
   Boogie  (intermediate verification language)
        │   computes the WEAKEST PRECONDITION of each postcondition
        ▼
   Verification Conditions (VCs)   logical formulas: "preconds ⟹ postcond holds after body"
        │
        ▼
   Z3  (SMT solver)         tries to prove each VC
        │
        ├─ proves ¬VC is UNSATISFIABLE  → no counterexample exists → VC holds for ALL inputs → ✅
        └─ finds a model of ¬VC          → that's a counterexample → ❌ "could not be proved"
```

**Key idea — proof by refutation.** To prove a verification condition `P`, Z3 *assumes its negation*
`¬P` ("the postcondition is violated while the preconditions hold") and searches for any variable
assignment that satisfies it. If it proves `¬P` is unsatisfiable, then `P` is true for every input.
If it finds a satisfying assignment, that's the counterexample and the obligation fails.

So Dafny verifies a property by **trying to break it and proving it can't be broken**, symbolically,
over the entire (usually infinite) input space.

---

## 3. What *our* pipeline proves — inductive invariant safety

Every feature refines the abstract `Domain` in
[`Replay.dfy`](../src/cleanroom/agents/dafny/kernel/Replay.dfy):

```dafny
ghost predicate Inv(m: Model)                 // the safety property — "always true"
function Init(): Model                         // start state
function Apply(m, a): Model  requires Inv(m)   // one transition
function Normalize(m): Model                   // repair
lemma InitSatisfiesInv()    ensures Inv(Init())                     // BASE CASE
lemma StepPreservesInv(m, a) requires Inv(m)
                             ensures Inv(Normalize(Apply(m, a)))    // INDUCTIVE STEP
```

The two lemmas are an **induction proof over the sequence of actions**:

- **Base case** `InitSatisfiesInv` — the initial state is safe.
- **Inductive step** `StepPreservesInv` — from any safe state, *any* action lands in a safe state.

Discharge both and you've proven, by induction, that **every state the system can ever reach
satisfies `Inv`**, for *every* possible sequence of operations. (e.g. "no add/edit/delete sequence
can ever produce a menu item with an empty name or negative price.") The `forall m, a` in the step
lemma means Z3 proves it for *every* model and action — by reasoning, not enumeration.

---

## 4. Where it fails — the proof walls

Z3 is automated but **not omniscient**. The gap between *what is true* and *what Z3 can prove
automatically* is the "proof wall." The two we hit most:

- **Map/set comprehension postconditions** — a `Normalize` that returns
  `map k | k in m && P(m[k]) :: m[k]` with `ensures Inv(result)`. Obvious to a human, but Z3 can't
  auto-conclude "for all surviving keys, `P` holds." Fix: bind the result and
  `assert forall k | k in result :: P(result[k]);` (or a helper lemma).
- **Map/seq lookup preconditions** — `m[k]` without first establishing `k in m` →
  "function precondition could not be proved." Fix: `assert k in m;` before the lookup.

These need *proof scaffolding* (asserts / lemmas), which is the genuinely hard part of getting an LLM
to write verifying Dafny. (More *rounds* don't help once the error plateaus — better tactics do.)

The escape hatch: `assume {:axiom} P;` tells Z3 to *take `P` as given*. Verification passes, but the
obligation is now an **assumption**, recorded and surfaced as `PROVED [N assumed axiom(s)]` — never
silent.

---

## 5. The pipeline workflow — how the `DafnyAgent` drives it

Stage 4a of the pipeline ([`run_pipeline.py`](../run_pipeline.py), opt-in `--prove`). Model: **gpt-4.1**.

```
for each feature (from the planning contracts):

  ┌─ build the SYSTEM prompt once (DafnyAgent._build_system) ───────────────────┐
  │   DAFNY_REF        — syntax cheat-sheet (prevents closeparen/rbrace errors)  │
  │   dafny-patterns   — state-machine pattern + common mistakes (vendored)      │
  │   dafny-proofs     — proof-maximizing workflow (vendored)                    │
  │   Domain interface — the exact abstract module to refine (from Replay.dfy)   │
  └──────────────────────────────────────────────────────────────────────────────┘
                │
                ▼
     FEATURE prompt = the feature's behavioral contracts (stimulus / precondition /
                       response / postcondition per FR) — spec only, never tests
                │
     ┌──────────▼─────────────────────────────────────────────────┐
     │  ROUND 1..max_rounds (default 6):                           │
     │    gpt-4.1 writes the FULL F<feat>.dfy module               │
     │       │                                                     │
     │       ▼                                                     │
     │    verify_dafny()  →  `dafny verify --allow-warnings`       │
     │       │   parse "finished with N verified, M errors"        │
     │       │   + extract_axioms()  (assume {:axiom} lines)       │
     │       ▼                                                     │
     │    M == 0 ?  ──yes──▶  PROVED ✅  (break)                   │
     │       │ no                                                  │
     │       ▼                                                     │
     │    feed errors back + a TARGETED hint (_targeted_hint):     │
     │      "precondition…"  → assert k in m before the lookup     │
     │      "postcondition…" → bind result + assert forall …       │
     │      "…expected"      → no `let…in` in ensures; inline      │
     │       └──────────── revise, next round ───────────────────┘ │
     └────────────────────────────────────────────────────────────┘
                │
                ▼
     verdict: FeatureDafny{ verified, rounds, residual_errors, axioms }
```

Then, after all features:

```
proved features → compile_dafny()  →  `dafny translate py`  →  out/F<feat>-py/   (native, runnable)
                → ship as a thin FastAPI adapter over the compiled core (Code Agent)
unproved features → fall through to full code + pass@k (the test track)
```

Relevant code:
- prompt + loop: [`agents/dafny/agent.py`](../src/cleanroom/agents/dafny/agent.py)
- verdict parsing + axiom extraction: [`utils/dafny_verify.py`](../src/cleanroom/utils/dafny_verify.py)
- compile to native: [`utils/dafny_project.py`](../src/cleanroom/utils/dafny_project.py) (`compile_dafny`)
- vendored prompts: [`agents/dafny/skills/`](../src/cleanroom/agents/dafny/skills/) + the `DAFNY_REF` constant
- the kernel features refine: [`agents/dafny/kernel/Replay.dfy`](../src/cleanroom/agents/dafny/kernel/Replay.dfy)

---

## 6. End-to-end, in one picture

```
 SRS ─▶ Spec ─▶ Dependency ─▶ Planning ─▶ behavioral contract per FR
                                              │
                                              ▼  (--prove)
                              ┌──────── DafnyAgent ────────┐
                              │  gen → dafny verify → revise │   gpt-4.1 + Z3, ≤6 rounds
                              └──────────────┬──────────────┘
                                  PROVED ✅        unproved ❌
                                     │                │
                          dafny translate py     full code + pass@k
                                     │                │
                          FastAPI adapter over    (test track)
                          the compiled core
```

---

## 7. Honest limits

- **Verification only guarantees what you encode.** A weak/vacuous `Inv` can be proved while the
  behavior is still wrong — proof of a weak property ≠ correct behavior. (This is why pass@k on the
  proved features is a useful cross-check.)
- **Only the pure core is proved.** Dafny is effect-free: the adapter's DB/HTTP/marshalling glue is
  *not* verified. A bug there fails behavior even with a perfect proved core.
- **gpt-4.1 isn't perfectly deterministic** even at temperature 0, so the proved set wobbles a little
  run to run; the prompt is the dominant lever (see the vendored skills).
- **The prover plateaus.** Once a feature stalls at a stable error, more rounds don't help — it needs
  a better tactic, the axiom hatch, or a restructured (weaker, provable) postcondition.
