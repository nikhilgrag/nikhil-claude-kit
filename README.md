# nikhil-claude-kit

Personal Claude Code kit. One skill and one hook, aimed at a single class of bug:
**code whose job is to detect a problem, and which fails toward green.**

A CI check that passes when it couldn't actually look is worse than no check, because
a green tick is trusted. This kit exists to catch that before pushing.

## Install

```
/plugin marketplace add nikhilgrag/nikhil-claude-kit
/plugin install review-kit@nikhil-claude-kit
```

## What's in it

### `proof-driven-review` skill

Adversarial review with one non-negotiable rule:

> **No finding without a command that demonstrates it.**

If you can't produce the input that makes the code misbehave and show the output, it isn't
a finding. Reasoning produces a confident wrong answer at the same speed as a correct one.

It also enforces:

- **Read the file, not the diff.** The diff shows what changed; it hides what the change
  *invalidated*. The best findings are in code that was correct before and became wrong
  without being edited.
- **Establish the failure direction.** For every guard: if this can't do its job, does it
  pass or fail? It must fail.
- **Treat review fixes as new code.** Code written under review pressure is the least-reviewed
  code in any change.
- **Read a new mechanism's limits before its features** when swapping tool A for tool B.

Plus rule packs for shell/YAML/CI, Python, and tests — each derived from a real defect, with
the mechanism spelled out rather than stated as a preference.

### Pre-push reminder hook

Fires on `git push` / `git commit`, and only when the diff touches `.github/**`, `*.yml`,
`*.sh`, `Makefile`, or `*.bazel`. Names the files and asks for a review pass.

Advisory, not blocking — it always exits 0. A bug in a reminder must never block real work.
That's a deliberate direction choice: the skill's "fail closed" rule is about *guards*, where
a false green is the danger. Different failure economics, different direction.

## One manual step per machine

Skill descriptions only *advise* activation. To make it fire reliably, add to
`~/.claude/CLAUDE.md`:

```markdown
- Invoke the `proof-driven-review` skill before pushing or committing any change
  to CI/CD, GitHub Actions workflows, shell scripts, or build gates — and before
  pushing fixes written in response to review comments. Review the final files,
  not the diff.
```

## Origin

Distilled from fourteen review findings on a single CI pull request, plus an honest account
of why the author's own review missed them. Every rule in the shell/Python/test packs traces
to a defect that actually shipped, not to a style preference.

Known gap: no C++, ROS 2, or CUDA rule packs yet. Those get added when there are real findings
to derive them from — inventing them up front is how a review skill degenerates into noise.

## License

MIT
