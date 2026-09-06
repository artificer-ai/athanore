# T054a — CLI steer verbs

**Task.** `docs/v1/17-serial-task-plan.md` § `### T054a`.
**Specs.** `docs/v1/11-cli.md` §Steer verbs; `docs/v1/06-requests.md`
§Modes (what `answer` has to send for each).
**Reference.** v0's `tests/test_cli_entry.py` (write half) — ledger row
ticked here.

## What this task is

The half of the CLI that changes something, including the one verb with
real argument ambiguity: `answer`.

## What this task is not

- No new API endpoints. Every verb is one call.
- No client-side state machine: preconditions live in `Ops` and surface
  as 409s.

## Steps

1. `answer <req> <option-id | text | json>` — the resolution order:
   JSON when the argument parses as an object, an option id when the
   request's mode is `options`, otherwise text. Get this wrong and an
   operator answering `{"ok": true}` to a text question sends a dict.
2. `permit [option]`, `deny`, `pause`, `resume`, `cancel`,
   `rm` (confirm unless `--yes`), `rerun`, `retry`, `move`,
   `set-status`, `edit [--title --description]`,
   `position up|down|<index>`.

## Verification

`tests/cli/test_steer_verbs.py`:

- each verb changes state **visible through the API** — assert the
  effect, not the exit code;
- `answer` picks the right body shape for each of the three modes;
- exit code 1 with the API's `error` message on a 409 — the message the
  server sent, not one the CLI invented.

## Done

- Tests pass; ledger row for `test_cli_entry.py` ticked.
- `**Status.** Done.` on `### T054a`, in the same commit.

## Files

```
athanore/cli/steer.py
tests/cli/test_steer_verbs.py
docs/porting-ledger.md
docs/v1/17-serial-task-plan.md
```
