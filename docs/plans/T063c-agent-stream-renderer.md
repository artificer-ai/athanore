# T063c — Agent stream renderer

**Task.** `docs/v1/17-serial-task-plan.md` § `### T063c`.
**Specs.** `docs/v1/10-frontend.md` §Agent stream;
`docs/v1/05-agents.md` §Chunk kinds (the mapping source).

## What this task is

The transcript: an agent's output as it arrives, appended chunk by chunk
rather than refetched.

## What this task is not

- No polling and no full refetch on every chunk — that is the mistake
  this task exists to avoid, and T060's `appendStream` is the mechanism.
- No custom-element registry yet; T071 generalises the table this
  registers into.

## Steps

1. `<ath-agent-stream>` as a React component registered in the
   custom-element table.
2. The focused task is the most recent in-flight task of the run, with
   an override from the task drawer.
3. Virtualised `StreamBlock`s mapping chunk kinds: `notice → system`,
   `text → assistant`, `thought → assistant, dimmed and collapsible`,
   `tool_call` / `tool_result → tool`.
4. A blinking caret while `live`.
5. Appends driven by `task.stream` with `after=seq`.

## Verification

Vitest:

- block mapping per kind;
- **a `task.stream` event fetches `after=` and does not refetch the
  whole transcript** — assert the request, not just the rendered
  output;
- the caret shows only while live.

## Done

- Tests pass.
- `**Status.** Done.` on `### T063c`, in the same commit.

## Files

```
web/src/panes/kinds/AgentStream.tsx
web/src/**/__tests__/**
docs/v1/17-serial-task-plan.md
```
