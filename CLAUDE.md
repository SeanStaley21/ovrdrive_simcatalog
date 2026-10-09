# OVRDrive Sim Catalog — Claude Code Operating Manual

## Reporting
- **Show results at the end of every completed task / change.**
- After each bounded phase of work, output a short handoff to the terminal, without being asked:
  **Did / Open / Next**.

## Worktree isolation
Any change to a file that could end up in a commit — code, data, docs, anything — happens in its
own `git worktree`, every session. A shared checkout has a single HEAD, index, and working tree,
so committing there blocks the developer from continuing to work in the repo and would collide
with a concurrent session. Prefer the Agent tool with `isolation: "worktree"` when spawning
sub-agents that write. Pure read-only work (research, exploration, reviewing a diff) in the main
checkout is fine; the moment any file is being written, it happens in a worktree.

## The workflow
- **PR Reviews:** When asked to review a PR, audit code changes, or execute a code review (e.g., using `/code-review`), strictly follow the review process, sub-agent roles, and auditing directives outlined in `agents-pr.md`.
- **Development:** For any software engineering, architecture, or coding tasks, you MUST consult and strictly follow the multi-agent protocol outlined in `agents-dev.md`. Do NOT bypass the phase gates or sub-agent delegation pipeline specified in that file.
- **Non-coding** (research, testing, etc.): no worktree needed, but make no code changes and
  make no assumptions.

If you are not sure which workflow applies, ask.

## Planning
- Write a plan when a slice of scope is stable: state what will be built, call out assumptions,
  and identify decision points.
- **Execute in bounded phases.** Do not expand scope beyond the current phase.
- **Surface decisions rather than assume.** If requirements are unresolved or in conflict, flag
  it instead of guessing.

## Your role (Claude Code)
- **Model policy:** Never use Fable or Haiku. Opus is used only for planning and reviewing; Sonnet is used for everything else (orchestration, implementation, exploration, research). Always set the sub-agent `model` explicitly.
- Plan when scope stabilizes, then execute, and document what you did.
- Keep the system tidy without being asked: update any docs your change makes stale, and output
  the handoff at the end of a state-changing session. That is part of the job, not the user's
  reminder to give.

## Coding guardrails — always apply these
- **Never log a secret.** No passwords, connection strings, API keys or tokens in any log
  record, at any level — including indirectly, via a caught error's `message`. Log the
  identifier, never the value.
- **Code comments describe the code as it stands today** — never the process that produced it,
  and never what it deliberately doesn't do. No ticket numbers, no review-finding codes, no
  "fixed after review" / "a prior version did X" narrative (that belongs in the commit message),
  no provenance ("copied from …"), no counts or figures that must be kept in step with the code.
  Exception: documenting a third-party API's actual behavior has nowhere else to live and is fine.
- No premature abstractions.
- No future-proofing unless explicitly asked for.
- No refactoring code outside the current task scope.
- Working over perfect.
- Clarity over cleverness.
- Simple direct solutions first.
- Follow DRY (Do not repeat yourself), YAGNI (You ain't gonna need it), and KISS (Keep it simple, stupid).

## Role summary
- **Developer (using Claude)** — direction, decisions, phase approval; final call on scope and
  shipping.
- **Claude Code** — planning, execution, documentation.
