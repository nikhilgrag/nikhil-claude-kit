---
name: proof-driven-review
description: >
  Adversarial, proof-driven code review. Use BEFORE pushing any change, and when
  reviewing someone else's. Mandatory for CI/CD, GitHub Actions workflows, shell
  scripts, build gates, and any code whose job is to detect a problem — those fail
  toward green, so a broken check looks like a passing one. Also use when responding
  to review comments, because fixes written under review pressure get less scrutiny
  than original code. Core rule: no finding without a command that demonstrates it.
  Triggers: "review this", "before I push", "is this correct", "check my workflow",
  "address the review comments", "why didn't we catch this".
---

# Proof-Driven Review

Two failure modes to defeat. Most review output suffers from one or the other:

- **Noise** — a long list of maybes. Style nits beside real bugs, speculation beside logic errors.
- **Blindness** — confirming the code works, when the question is which way it fails.

This skill defeats both with one rule.

## The rule

> **No finding without a command that demonstrates it.**

If you cannot produce the input that makes the code misbehave, and show the output, you do not
have a finding. You have a feeling. Discard it.

This is not optional and it is not satisfiable by reasoning. Reasoning produces a confident
wrong answer at the same speed as a correct one. Run the thirty-second experiment.

Corollary: any claim of the form *"this can't happen"* ships with the command proving it can't.

## Procedure

### 1. Read the file, not the diff

The diff shows what changed. It hides what the change **invalidated**.

Open every touched file in full and ask of the *untouched* lines: what were these assuming, and
is that still true? The highest-value findings live here — code that was correct before the
change and became wrong without being edited.

Concrete instance this skill was built from: a workflow stopped cloning a submodule, and a
comment 60 lines away still said "this gate is authoritative because it always checks out the
submodule." Nothing in the diff was wrong. The file was.

### 2. Establish the failure direction

For every check, guard, gate, assertion, or validation:

> **If this cannot do its job, does it pass or fail?**

It must fail. A check that passes when it couldn't look is worse than no check, because a green
tick is trusted. Name the direction explicitly in the finding.

Sub-questions that expose it:
- What if the input is empty? Truncated? Absent?
- What if the command it depends on is missing, unauthenticated, or rate-limited?
- What if the thing it inspects moved?

### 3. Trace context before judging

- Find every caller and usage. A "bug" is often a deliberate contract.
- Read the project's conventions (`AGENTS.md`, `CLAUDE.md`, existing sibling code). A deviation
  from house style in a repo you haven't read is not a finding.
- Check whether documentation or a comment already explains the design. If it does, discard.

### 4. Separate "broken now" from "breaks later"

State both. A latent defect is a real finding **if you can name the plausible edit that arms
it** — and that edit must be something a reasonable person would do at review time without
alarm. "Someone might delete this line" is not a mechanism. "Extending this pattern to be more
precise makes it 42 bytes and the guard dies" is.

If it is neither broken now nor armable by a plausible edit, discard it.

### 5. Treat review fixes as new code

Code written while responding to review is the least-reviewed code in any change. It arrives
with momentum, it looks like a concession rather than a design decision, and nobody re-reads it.

Apply this entire skill to your own fixes before pushing them. In the change this skill came
from, three of seven defects were introduced *while fixing earlier review comments* — including
a fail-open bug introduced by the commit that fixed a different fail-open bug.

### 6. When substituting a mechanism, read the new one's limits first

Swapping tool A for faster tool B inherits B's constraints. Read what B **won't** do — caps,
truncation, pagination limits, silent degradation — before confirming it does the job on
normal-sized input.

## Failure taxonomy

Hunt these five classes by name.

| Class | Question |
|---|---|
| **Fail-open** | Can this report success without having verified anything? |
| **Invalidated assumption** | What did the untouched code around this believe? |
| **Unreviewed fix** | Was this written under review pressure? |
| **Inherited limit** | What does the newly-introduced mechanism silently refuse to do? |
| **Untested guard** | Is the guard's failure path ever exercised by a test? |

The last one is structural and outranks the rest. A guard whose failure path no test exercises
will rot, and no amount of careful reading prevents that permanently. Prefer recommending a
test over recommending vigilance.

## Rule packs

### Shell, YAML, CI

- Never `producer | grep -q`. `grep -q` exits at the first match and SIGPIPEs the producer;
  under `set -o pipefail` bash returns the producer's 141, so a **match becomes a miss**. Use a
  herestring: `grep -qE '...' <<<"$var"`. Check whether the repo uses `shell: bash` or
  `defaults.run.shell` anywhere — if so, this is one PR away from live.
- Never `cmd | grep -q`. It cannot distinguish "no match" from "cmd failed". Capture first,
  check the status, then match.
- Never couple a read length to a pattern length (`head -c 40` with a 40-byte anchored pattern).
  `grep` cannot match an anchored pattern longer than its input, and unsatisfiable means
  fail-open. Read a line.
- Escape `.` in patterns matching literal URLs and paths. `.` matches any byte.
- Space-pad list membership tests: `case " $LIST " in *" $item "*)` — otherwise substrings match.
- `::error::` must be emitted by the code that knows the cause. A `cmd || { echo "::error::X"; }`
  wrapper labels *every* failure mode X, and X is wrong for all but one of them. Capture the
  tool's output and surface its own message.
- A gate that cannot decide must fail, not skip. Truncated API results, missing files, and auth
  errors all mean "run the check", never "nothing to do".
- Scripts invoked from CI get their inputs passed explicitly. Never rely on auto-discovery that
  can "gracefully skip" with exit 0 — that exit code becomes a green required check.
- One constant, one place. A magic string duplicated across shell and another language has no
  test tying the copies together; the untested copy is the one that breaks.
- Cross-workflow permission narrowing is invisible to actionlint, which lints each workflow in
  isolation. A callee may only narrow its caller's permissions: a scope requested downstream but
  granted nowhere upstream makes GitHub reject the entire run as a startup failure — zero jobs,
  no log, no check run (so the commit still goes green), and no job for a failure notifier to
  run in. Whenever a change touches a `permissions:` block or a `uses: ./.github/workflows/`
  edge, run `check_workflow_permissions.py <workflows dir>` from this skill's directory. It
  exits non-zero on a shortfall, and on anything that stopped it looking.
- A position-keyed lint suppression — zizmor's `file.yml:LINE:COL` ignores, or any allowlist
  anchored by line — is load-bearing coupling with nothing enforcing it. Insert a line above the
  anchor and it silently points at innocent code: the suppressed finding returns, surfacing on
  whichever unrelated PR next runs the lint. Line existence is not the check, because drift
  usually lands on a real line. Run `check_zizmor_pins.py <config> <workflows dir>` from this
  skill's directory; it matches each anchor against what could actually produce that rule's
  finding, and names anchors whose rule it cannot verify rather than calling them clean.

### Python

- `read_text()` / `open()` always with explicit `encoding=`. Without it the codec is the
  environment's, so CI and a laptop can disagree byte-for-byte with neither reproducible.
- Never `errors="replace"` in a tool whose contract is exact output. It converts a loud
  `UnicodeDecodeError` into silent substitution.
- Both sides of a comparison must use one decode policy. Check for asymmetry.

### Tests

- A file named `test_*.py` must contain `test_*` functions or `Test*` classes. Otherwise pytest
  collects it, finds zero tests, and **reports success**.
- Hunt tautological tests: a test that asserts on state its runner always provides cannot fail.
  Ask what input would make this test go red, and produce it.
- Fast, dependency-free tests belong where the repo says they belong.

## Do not report

- Formatting, naming, or style preferences.
- Missing test coverage as a standalone finding, unless the untested thing is a guard.
- Anything you could not reproduce.
- Anything the code or docs already explain as deliberate.
- Speculative "what if someone" with no named plausible edit.

## Output format

One block per finding, most severe first.

```markdown
## <SEVERITY> — <one-line claim, the defect itself, no preamble>

**Severity:** HIGH | MEDIUM | LOW — <what it costs, in one clause>

### The problem
<the offending code, quoted, with file:line>
<two or three sentences on what it does versus what it should do>

### Proof
<the actual commands run and their actual output — both directions where possible:
 the input that trips it, and the input that shows it silently passing>

### Today vs. what breaks
<is it live or latent; if latent, the specific plausible edit that arms it>

### Recommendation
<concrete replacement code, not advice>
```

Severity means consequence, not confidence:
- **HIGH** — wrong behaviour reaches production, or a guard is already a no-op.
- **MEDIUM** — latent fail-open, or a diagnostic that misdirects whoever hits it.
- **LOW** — narrow trigger, but the failure direction is still green-when-broken.

## Self-review mode

Before pushing, run this skill against your own change with one modification:

**Review the final files with no memory of why you wrote them.** You cannot unsee your own
reasoning — every line looks justified because you know its purpose. The reader in six months
does not. If a fresh reader cannot tell that a constant's length is load-bearing, it is a defect
regardless of whether it works today.

When available, delegate this pass to a subagent and give it the **final files only** — not the
diff, not the commit message, not your explanation. Its lack of context is the entire point.
