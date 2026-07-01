# Methodology

## Goal

Our goal is to take a natural-language **Software Requirements Specification (SRS)** and turn it
into a working application whose every feature carries an *honest* statement of how far it has been
verified — formally proved where the logic permits it, statistically tested where it does not, and
explicitly marked uncertified where neither succeeds.

The problem we are really attacking is not "can a language model write code" — it plainly can. It
is that the usual way of *measuring* such code is circular. In a conventional agentic loop the model
writes code, runs the tests, sees the failures, and rewrites the code until the tests pass. The
implementation ends up shaped by the very tests used to judge it, so a high pass rate certifies
almost nothing. We set out to build a pipeline in which the score means what it says. Everything
below follows from that single commitment.

The design rests on three principles that we return to throughout:

- **Clean-room isolation.** Code and tests are each derived independently from the specification and
  never from each other. They are brought together exactly once, at scoring time, after both are
  frozen.
- **Prove-or-test, labelled honestly.** Pure logic is formally verified; effectful logic is tested
  with pass@k; and no feature is allowed to claim a guarantee it has not earned.
- **Deterministic-first construction.** The structural backbone of the system — requirement
  identifiers, parsing, ordering, file paths — is plain deterministic code. The language model is
  used only for interpretation, and never owns an identifier.

The pipeline is a plain sequential composition of stages. There is no orchestration framework and no
hidden control flow: each stage reads a shared **Intermediate Representation (IR)** — a single JSON
document — and writes an enriched version of it. The IR is therefore both the data bus and the
complete audit trail of a run. The atomic unit of work everywhere is the **functional requirement
(FR)**; a proved feature certifies all of its FRs, and every metric we report is computed at FR
granularity.

---

## Grounding: Cleanroom Software Engineering

The design is not ad hoc. It is a deliberate adaptation of **Cleanroom Software Engineering** — the
discipline introduced by Mills, Dyer, and Linger at IBM — to a setting in which the developers and
testers are language-model agents rather than people. The name "cleanroom" is borrowed from
semiconductor manufacturing, where the emphasis is on *preventing* contamination rather than removing
it after the fact; classical Cleanroom carries that idea into software as defect *prevention* over
defect *removal*. Three tenets define it, and each maps directly onto a mechanism in our pipeline.

**1. Specification before code, in a box-structured form.** Cleanroom develops software from a precise
specification that describes, for each stimulus history, the required response — the "black box" view.
Our behavioural contracts (stimulus, precondition, response, postcondition) are exactly this black-box
specification, authored once per requirement and frozen before any code or test exists. Every later
agent reasons from that contract, never from prose alone.

**2. Development by verification, not by debugging.** The defining rule of Cleanroom is that
developers do **not** unit-test or debug their own code. They establish correctness by *verification*
— reasoning that the implementation realizes its specification — and they are organizationally
separated from the team that executes the software. Our pipeline takes this rule literally and makes
it structural. The code agent never sees a test, never runs one, and has no feedback path from
execution; where a feature's logic is pure, "verification" is not informal review but a *machine-checked
formal proof* in Dafny. This is Cleanroom's "no debugging against tests" discipline, enforced by
construction and strengthened from human review to a verifier.

**3. Certification by statistical testing, performed independently.** In Cleanroom, testing is not a
debugging activity to find and fix defects; it is a separate *certification* activity that runs the
finished software against an independent test model to certify its quality. Our certification stage is
precisely this: an independent, code-blind test agent derives the cases, and an executable oracle
scores the frozen code against them using pass@k — a statistical estimate — feeding nothing back into
development. Testing here measures; it never repairs.

The correspondence is summarized below.

| Cleanroom Software Engineering | This work (agentic realization) |
|---|---|
| Black-box / box-structured specification | Behavioural contracts (stimulus → response), frozen per FR |
| Developers verify, never debug against tests | Code agent is test-blind by construction; pure logic is *formally proved* in Dafny |
| Separation of development and certification teams | Structural isolation: code and test agents cannot reach each other's artifacts |
| Statistical usage-based certification of quality | pass@k via an independent executable oracle; no feedback to generation |
| Defect prevention over defect removal | Proof prevents whole classes of defect; testing certifies, it does not patch |

Two honest points of departure from classical Cleanroom. First, classical Cleanroom relies on
*human* functional verification; we replace it, for pure logic, with mechanical proof — a strictly
stronger guarantee — while conceding that effectful logic cannot be proved and must fall back to the
statistical tier. Second, Cleanroom forbids developer debugging outright; we permit a single,
*bounded and disclosed* relaxation in the recovery phase, where a feature that has already failed both
proof and certification may be regenerated with test feedback — and we label any such feature
distinctly so the breach is never hidden. With those two qualifications, the pipeline is a faithful,
automated instantiation of the Cleanroom method.

---

## What we are targeting

Three capabilities sit at the centre of automated software construction — writing the code,
verifying it, and testing it — and the contribution of this work is a different stance on each. We
describe each in turn, in each case contrasting the common practice with what we do and why it
matters.

### 1. Code generation

**Common practice.** Code is generated inside a feedback loop driven by test results. The model
writes an implementation, the harness runs the tests, and failures are fed back for repair. The
implementation is, in effect, a function of the test outcomes.

**Our approach.** We generate code as a *pure function of the specification*, with no path by which
test information can ever reach the generator. This is enforced structurally rather than by
instruction: the code agent's only input is the specification-derived contract, no method it exposes
accepts a test-related argument, there is no test-driven retry loop, and it never imports the test
agent or reads the generated tests — even though those tests sit in the same IR it is handed. Code
is produced one functional requirement at a time, each call scoped to that requirement's own
contract plus the *signatures* (not the bodies) of its prerequisites, rather than from the whole
specification in a single shot or from an open-ended agent scratchpad.

**Why it is different, and why it matters.** The point is not that the code is better — it is that
the code is generated *blind to its own examination*. That is the precondition for the test score to
mean anything at all. Where most systems have one generation path and one inflated number, we keep
distinct, separately labelled paths (clean-room code; a thin adapter over already-proved logic; and,
only in a contained recovery phase, a deliberately test-informed regeneration), so the provenance of
every shipped feature is recoverable.

### 2. Verification

**Common practice.** "Verification" in LLM code work almost always means *testing* — running unit
tests, or asking another model to judge. Where formal methods do appear, they tend to be an offline
exercise: a hand-written specification is proved in isolation, disconnected from the code that
actually runs.

**Our approach.** We make formal proof a first-class certification tier *inside* the pipeline, and we
ship the thing we prove. Where a feature's logic can be expressed as a pure state machine, it is cast
into Dafny as a machine that refines a small, already-verified kernel, and the proof obligation is
precise: the machine can never reach a state that violates its invariant. The model authors the
Dafny; the real Dafny verifier discharges it; and on failure the *concrete* verifier diagnostics are
fed back, mapped to specific proof tactics, for a bounded number of revision rounds. A proved feature
is then compiled to native code, and on the database-backed (web) stacks the application calls *that
compiled core* through a thin adapter. The verification is therefore of the logic that executes, not
of a parallel sketch.

**Why it is different, and why it matters.** Two things distinguish this from "we also ran a prover."
First, proof governs deployment: the proved core is what ships, closing the usual gap between a
verified specification and the unverified code that runs beside it. Second, the proof/test boundary
is explicit and audited. Because Dafny is effect-free, only pure logic is provable; database and HTTP
behaviour are routed to the test tier rather than waved through. An obligation that cannot be
discharged may pass only through an explicit, auditable assumption (`assume {:axiom}`), and the
feature is then labelled as proved *subject to* that assumption. Nothing silently claims soundness.

### 3. Test generation

**Common practice.** Tests are written *from the code*, to cover what was actually implemented, or
co-evolved with it. Either way the tests are contaminated by the implementation, so passing them
demonstrates internal consistency rather than correctness against the requirement.

**Our approach.** Tests are a pure function of the specification — the exact mirror image of code
generation. The test agent reads only specification-derived material — the features, their
requirements, and the planned interface (signatures and behavioural contracts) that was authored
before any code existed; it never imports any code module and never reads the generated code, even
though that key is present in the IR it receives. It produces a structured, machine-checkable set of `(inputs, expected)` cases derived from
the behavioural contract — including the failure and error modes — and these structured cases, not
any human-readable test file, are what the executable oracle runs. Scoring therefore does not depend
on the generated code's module names or import structure.

**Why it is different, and why it matters.** Because the tests are written without ever seeing the
implementation, they constitute a genuinely independent oracle. This is the symmetric other half of
clean-room isolation: it is what licenses pass@k as a real measurement rather than a restatement of
what the code already does.

Taken together, these are not three separate ideas but one mechanism seen from three sides:
independently derived code and tests, a proof tier that ships what it verifies, and a single honest
scale on which the two kinds of evidence can be read side by side.

---

## The pipeline, stage by stage

### Stage 1 — Specification extraction and contracts

The first stage turns the SRS into structured features, and it does so in two deliberately separated
phases. The first phase is purely deterministic: a section-aware reader walks the document, assigns
each node a stable identifier, and groups the functional requirements into features, ignoring
narrative and non-functional sections entirely. Real specifications are messy and inconsistent, so
the reader supports several document conventions and selects the right one in cascade. Keeping the
model out of this phase is what guarantees that identifiers, requirement text, and grouping can never
drift, be dropped, or be invented.

Only in the second phase does the language model enter, to write a **behavioural contract** for each
requirement — a design-by-contract tuple of stimulus, precondition, response, and postcondition —
one structured call per feature. The model supplies the contract fields; the requirement identifier
is always carried over verbatim from the parser. These contracts are the shared semantic anchor that
every later stage reads from.

### Stage 2 — Dependency analysis

The second stage works out build-order dependencies, both between features and among the
requirements within a feature. We want to be precise about what this stage does in practice rather
than in principle. The mechanism supports two sources of edges: a deterministic detector over
explicit cross-references ("requirement A says *see section B*"), and an optional, constrained
language-model pass that infers prerequisites the prose implies but never states outright — typically
the "operate-on depends on create" pattern, where one requirement edits or cancels an entity that
another first creates.

On the real specifications we study, the deterministic detector finds essentially nothing: these
documents simply do not encode their inter-requirement dependencies as machine-readable references.
Their orderings live in the *meaning* of the text ("once the order is placed", "the previously stored
result"), which a structural parser cannot recover. The dependency edges that matter are therefore
discovered by the constrained model pass. Crucially, that pass is *bounded by the deterministic
backbone*: every identifier it returns is validated against the parser's set, so it may reorder and
relate requirements but can never invent or rename one. The single load-bearing output of this stage
is the per-requirement prerequisite list, which later surfaces a prerequisite's signature into the
dependent requirement's code-generation prompt so that intra-feature references bind correctly.

### Stage 3 — Planning

Planning attaches implementation metadata to each behavioural contract, producing one **implementation
contract** per requirement. It walks the requirements in dependency order and records a concrete
function signature and an architectural-layer classification (both interpreted by the model) together
with a docstring, a file path, and the prerequisite list (all assembled deterministically). The
docstring in particular is composed by code from the behavioural contract, with preconditions and
postconditions surfaced as explicit guarantees; the model contributes only the per-argument
descriptions that bind to the signature it authored.

This stage is quietly the linchpin of the whole design. Because the code agent and the test agent
will each consume this single, specification-derived contract — and nothing originating from the
other side — isolation is achieved structurally rather than by asking the agents to behave. The two
sides agree only insofar as they anchor to the same frozen contract.

### Stage 4a — The verification track

Before any application code is written, the pipeline attempts to prove each feature whose logic is
pure. This is the agentic counterpart of Cleanroom's *development by verification*: rather than
establishing correctness by debugging against tests, we establish it by proof. The feature's
requirements are cast into a Dafny state machine — a concrete state type, one
action per requirement, an invariant, and initialise/transition functions — that refines an
in-repository, already-verified replay/redux kernel. The two obligations the kernel imposes,
"initialisation satisfies the invariant" and "every step preserves it", are what "verified" means
here. The agent runs a generate–verify–revise loop, feeding the verifier's concrete errors back as
targeted proof hints rather than retrying blindly, and a feature is accepted only when the verifier
reports zero errors. Proved features are then compiled to native code so that, on the web stacks,
the application can ship the verified core directly.

Because Dafny is effect-free, this track can only reach pure model-layer logic; anything touching a
database, the network, or I/O is left for the test tier by design. The escape hatch for an
obligation the model cannot discharge is an explicit assumption, and a feature that relies on one is
labelled accordingly, so the proof tier never overstates its coverage.

### Stage 4 — Code generation

The code agent now synthesises one source file per implementation contract, each in a single call
scoped to that requirement's contract and the signatures of its prerequisites. As described above, it
is built so that test information is structurally unreachable. For a feature the proof tier has
already verified, the agent does not re-implement the logic on the database-backed (web) stacks: it
emits a thin adapter that imports the compiled core, persists the verified state, and invokes the
proved transition, so the logic that ships for those features is the verified Dafny rather than a
re-creation of it. (On the plain stacks the proof tier is verification-only and every feature is
generated normally.) A separate compiler-directed
repair path exists for the statically typed targets, but it receives compiler diagnostics only —
never test cases — so it does not breach isolation.

### Stage 5 — Test generation

In parallel with the same frozen contract, the test agent derives black-box test cases from the
specification alone, one call per feature, reading only specification-derived material — the
requirements together with the planned interface (signatures and behavioural contracts), which was
authored before any code existed. It produces both a structured set of input/expected cases — the canonical, code-independent oracle the
certifier executes — and a human-readable test module for inspection. It never reads the generated
code, and scoring is performed against the structured cases so that it is unaffected by any incidental
mismatch in the readable module's bindings.

### Stage 6 — Certification

Certification is the one and only place where specification-derived code and specification-derived
tests are brought together, and it happens only after both are frozen. In the Cleanroom sense this is
*certification, not debugging*: it measures quality and feeds nothing back into development. We adopt
the standard pass@k estimator, with the functional requirement as the scoring unit and
results macro-averaged across requirements. Each structured case is executed against a candidate
sample in an isolated subprocess through a target-appropriate oracle, and a sample is credited for a
requirement only if all of that requirement's cases pass. Features already certified by the proof
tier are excluded from statistical testing, since proof is their certification.

### Stage 6b — Recovery, and why it stays honest

For features that remain unproved and fail pass@1, an optional, bounded recovery phase applies an
escalating last resort: it first re-attempts the proof with a larger round budget, and only if that
fails does it regenerate the code *with* the failing cases supplied as feedback, before re-certifying
against the unchanged test suite. This is the single point in the entire pipeline where generation is
allowed to see test data, and it occurs only after a feature has already failed both the proof track
and the clean-room first pass. The relaxation is contained and, crucially, *disclosed*: every feature
ends with a terminal label recording exactly how it was certified — proved, proved during recovery,
tested in clean-room conditions, tested after test-informed repair, or left uncertified — so the
headline numbers can always be read alongside the provenance of the features that produced them.

---

## What we report

Every run ends with a small set of FR-granular metrics: a **verification pass ratio** (the fraction
of requirements discharged by proof), a **test-case pass rate**, and a combined **PassVer@1** — the
fraction of requirements certified either by proof or by passing pass@1, taken as a deduplicated
union over the two tiers. Alongside these we record the average number of verify–revise iterations,
the average test-track iterations, token usage, and wall-clock time. Reporting proof and statistical
certification inside one FR-granular framework lets the formally verified and the merely tested parts
of an application be compared on a common scale while keeping their epistemic status firmly distinct —
which, in the end, is the entire point of the system.
