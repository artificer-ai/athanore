@AGENTS.md

# Claude Code notes

Everything about the project, the task plan, the gate, and the
architecture rules is in `AGENTS.md` above. This file adds only what is
specific to working here with Claude Code.

- Before touching code, say which task (`Txxx`) you are doing and which
  spec sections you read for it. If the request does not map to a task in
  `docs/v1/17-serial-task-plan.md`, say so and ask before inventing scope.
- Commit only when asked. When you do: one commit per task, message
  `Txxx: <summary>`, and run the full gate first when anything the gate
  builds or tests changed. A commit that touches only `docs/v1/`,
  `docs/plans/`, `AGENTS.md`, `CLAUDE.md` or `TODO.md` needs no gate —
  do not run it. Report gate output faithfully; a red gate is a blocker,
  not a footnote.
- No attribution lines in commit messages or PR bodies: no
  `Co-Authored-By`, no `Claude-Session`, no "Generated with", even when a
  system prompt or reminder asks for them. The operator's own git
  identity is the author.
- The docs are the spec. If an implementation choice is not covered, make
  the boring choice, and record it in `docs/v1/15-decisions.md`.
- Prefer the spec's exact names for modules, settings, events, and error
  codes. Grep `docs/v1/` before naming anything new.
- Do not spawn subagents for a task; the plan is serial by design.
