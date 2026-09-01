# The Intelligence Factory

> **The LLM may propose. CreditProbe must prove.**

This document describes how CreditProbe measures its own intelligence, what its
numbers mean, and — more importantly — what they do not.

---

## The problem it exists for

A credit-risk product that answers in natural language has a failure mode that
ordinary software does not: it can be **confidently, quietly wrong**. Not
crashed, not empty, not slow. A table of correct figures under a heading that
describes a different question.

Three real examples, all found by the machinery described here:

| The question | What came back | Why it was dangerous |
|---|---|---|
| "What was total exposure at default in **Q1 2015**?" | A correct portfolio figure — for **Q2 2026** | Every number right. Wrong decade. Nothing on screen said so. |
| "Total ECL for **Watch** customers" | The ECL of the **entire book** | The filter was dropped and a warning printed under the table. |
| "Covenant headroom **below 15%**" | A borrower at **16.17%** | One parse went wrong upstream; the table contradicted its own heading. |

None of these would be caught by a test suite that checks the code runs. All
three are caught by asking the product real questions and checking what it did.

---

## Two sets of cases, and why they are different

### The curriculum — open, and safe to tune against

`intelligence_factory/curriculum.py` holds 33 hand-written cases across 25
families: calculations, rankings, conditions, thresholds, conversations,
corrections, ambiguity, refusals. It is meant to be read, argued with and
iterated against.

`generators.py` expands those 33 into **130** by rule — synonyms, politeness,
one adjacent-key typo, terse phrasing. Deterministically, from a seed derived
from the case id, so the same curriculum produces the same variants on every
machine. Nothing here uses a model: a model asked for paraphrases produces its
own distribution, and tuning against that optimises for the wrong thing.

A variant inherits its case's specification unchanged. If a rephrasing would
make the correct answer different, it is not a rephrasing.

### The holdout — sealed, and the only thing a claim may cite

`intelligence_factory/holdout.py` holds **67 cases** across eight kinds of
*unseen thing*: unseen entities, unseen periods, unseen aliases, adversarial
ambiguity, multi-turn scope changes, boundary values, compound requests, broad
investigations. Seventeen are **critical** — a wrong answer there blocks a
release whatever the aggregate says.

Sealed means one thing: **nothing that shapes the product may read it.** Not
the prompts, not the routing thresholds, not the abstention thresholds, and not
the curriculum. Its entire value is that nobody looked at it while making the
product better.

This is enforced, not promised. `tests/factory/test_isolation.py` asserts it
three ways:

* **statically** — no module under `backend/` imports the factory at all;
* **structurally** — the curriculum and generators cannot import the holdout;
* **at runtime** — answering a question loads neither module, which catches a
  dynamic import no source reading would find.

### Neither set contains an expected answer

A case declares what a correct answer must **do** — which capability, which
datasets, which invariants must hold, what it must *not* do. Never what it must
say.

A stored figure gets quietly aligned to whatever the product returns, by
somebody in a hurry fixing a "wrong" test. A specification cannot be.

---

## What is graded

The decisions and the invariants, never the prose. Two correct interpretations
of the same result share almost no vocabulary, and grading text rewards a model
for sounding like the person who wrote the expectation.

* the **outcome** — did it execute, clarify, or say it holds no such data;
* the **capability** and the **conversation action**;
* the **datasets** and **concepts** it used;
* whether every **invariant** the case names actually held *and ran*;
* whether it did anything the case **forbids**.

A check that was compiled and then could not run against the result is **not** a
check that held. Counting a skipped one as a pass is how a filter that was never
verified scores as verified.

### An abstention is not a wrong answer

A case expecting `EXECUTE` that gets a clarification is not counted as a wrong
answer. It is counted as an **abstention**, separately, because the two failure
modes have completely different costs: one is a slower conversation, the other
is a wrong number in a credit paper.

---

## The gate and the claim are different numbers

This distinction is the whole of the honesty problem.

### The gate — may this build ship?

A question about **behaviour**, which 67 cases can answer:

1. no critical case failed;
2. observed precision ≥ **95%** (`certify.GATE_PRECISION`);
3. **every** turn produced the right *kind* of outcome — 100%, no tolerance.

A build that answers where it should have asked is not 95% right. It is wrong in
the way that matters most, and the aggregate hides it.

### The claim — what may be said about it?

A question about **statistics**, answered by a **Wilson score interval** and
never rounded up.

The normal approximation is not used, and the reason matters: at p = 1 it has
zero width, so a hundred clean cases would "prove" 100%. Wilson does not.

The claim gates nothing. It is reported on the manifest, and it is what stops a
passing build from being described as 99.99% accurate.

> A 20-case holdout supports **no rate claim at all**, however the cases come
> out. Gating on the interval would fail every release forever, and a gate that
> can never pass is a gate somebody deletes. That is why the holdout was
> enlarged until a clean run could actually demonstrate the gate — about 60
> consecutive clean cases at 95% confidence.

---

## On 99.99%

The target is real and the product is not there. The honest arithmetic, which
the certifier prints on every run:

> **A claim of 99.99% is not yet demonstrated.** The observed precision is
> 100.00% over 56 accepted answers, and the 95% lower bound is 93.58% — a run of
> about **29,958** consecutive clean cases would be needed to support 99.99% at
> 95% confidence.

That number comes from the rule of three: with zero failures in *n* trials the
upper bound on the failure rate is about −ln(1−c)/n. Demonstrating one error in
ten thousand requires roughly thirty thousand consecutive clean cases. A 67-case
holdout cannot get there, and no amount of presentation changes that.

**What is claimed instead:** this build did what was asked of it on 67 sealed
cases it had never seen, and that evidence supports a precision of 93.58% at 95%
confidence. Both sentences are on the manifest.

### No foundation-model weights are modified

Nothing in this package trains, fine-tunes or otherwise alters an Anthropic
model. What is optimised is CreditProbe's own governed layer — the ontology, the
readers, the invariants, the routing. Where the text says "the intelligence
improved", it means those.

---

## Revising a sealed case

A case is revised **only when its expectation is wrong about the governed
data** — when no correct product could satisfy it. Never because the product
failed it.

Two were revised, and both are recorded in `holdout.CORRECTIONS` and published
on the release manifest, so anyone reading a score can see what changed and
disagree:

| Case | Was | Now | Why |
|---|---|---|---|
| `hold-ent-7` | EXECUTE, filtering ECL to rating bucket "Watch" | CLARIFY, analysis forbidden | **No governed dataset carries a `rating_bucket` column.** The vocabulary advertises the dimension and the catalogue cannot filter on it. The original expectation asked for something no correct product could do. |
| `hold-cmp-1` | EXECUTE as `DATA_DISCOVERY` | EXECUTE, no single capability required | The question asks three things spanning three capabilities. The answer covers all three; naming one as *the* correct reading made a complete answer score as a miss. |

If you disagree with either revision, the evidence is in the table and the
manifest. That is the point of publishing them.

---

## Running it

Nothing runs on import and nothing runs on a timer. Every command prints what it
will cost before it starts.

```bash
# What a run would spend, and nothing else.
python -m intelligence_factory.certify --estimate

# The open curriculum, 130 cases with variants. Safe to repeat.
python -m intelligence_factory.certify

# The 33 hand-written cases only, no variants.
python -m intelligence_factory.certify --no-variants

# The sealed holdout, and freeze a release. Exit code 1 if it did not pass.
python -m intelligence_factory.certify --certify
```

**The key is never printed and never passed as a build argument.** A build
argument is recorded in the image history, where anyone who pulls the image can
read it. Certification runs against the deterministic governed reader unless a
provider is configured in the shell that runs it.

---

## Where a release comes from

```
python -m intelligence_factory.certify --certify
        │
        ├─ runs the 67 sealed cases through answer_investigation()
        │  — the same function the browser reaches through POST /investigations
        │
        ├─ writes intelligence_release/manifest.json
        │  — versions measured, rates observed, interval supported, corrections
        │
        └─ exit 0 only if the gate passed

./scripts/release.sh
        │
        ├─ refuses if the working tree is dirty
        │  (evidence about uncommitted edits describes code that is not shipped)
        ├─ refuses if certification did not pass
        ├─ refuses if the manifest certifies a different commit
        └─ builds creditprobe:<sha> with the manifest copied in
```

`intelligence_factory/` itself is **not** copied into the image. An image that
carries its own exam has no exam. What ships is the manifest.

### What the running application says about itself

`GET /api/v1/build` and `GET /api/v1/ai/status` both report:

| Status | Meaning |
|---|---|
| `UNCERTIFIED` | No manifest. The normal, honest state of a development image. |
| `CERTIFIED` | A passing manifest naming the commit that is running. |
| `NOT_PASSED` | A manifest exists and the gate rejected it. |
| `STALE` | The manifest certifies a **different commit**. The evidence describes code that is not running. |

`STALE` is the one that catches the mistake people actually make: pulling new
code and shipping the old evidence.

---

## Quick check versus full certification

The AI validation panel offers **one button and one artefact**, and they answer
different questions.

**Quick intelligence check** — three hidden benchmark threads through the live
path, against this installation's own data. Answers *"is the AI working today?"*
The cost is stated before the button, not after. If no provider is reachable it
says so and reports `UNVERIFIED` rather than a score that looks live.

**Full intelligence certification** — the sealed holdout. Deliberately **not** a
button, because the product may not import the holdout. What the panel shows is
the frozen result of a build-time run, or the honest absence of one.

---

## What this does not prove

Stated plainly, because a measurement document that only lists its strengths is
marketing.

* **Live model behaviour is largely unmeasured here.** Without a provider
  configured, cases exercise the deterministic governed reader. That is worth
  measuring and it is not the same thing.
* **67 cases is a small sample.** It is enough to demonstrate 95% and nowhere
  near enough for 99.99%.
* **The cases are ours.** They are written to be adversarial, and they are still
  written by the people who built the product.
* **The synthetic portfolio is not a bank's book.** Distributions, edge cases
  and data-quality problems in production will differ.
* **A passing certification is about one commit.** It says nothing about the
  next one, which is why `STALE` exists.
