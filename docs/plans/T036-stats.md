# T036 — Stats: provider protocol and the entry recorder

**Task.** `docs/v1/17-serial-task-plan.md` § `### T036`.
**Specs.** `docs/v1/05-agents.md` §Stats; `docs/v1/15-decisions.md` D27,
D46; `AGENTS.md` §Architecture rules — "stats and status never zero-fill
or estimate; unknown is omitted".
**Reference.** v0's `build_acp_usage` and its stats formatter.

## What this task is

Token counts and cost, recorded honestly. Every field is optional, and
an unknown one is absent rather than zero — a `0` here is a lie that
propagates into every summary that sums it.

## What this task is not

- No session-file parsing — T039 moves that.
- No provider implementation (pi, Claude): those live in `examples/`,
  because nothing in `athanore/` may depend on a vendor
  (`AGENTS.md` §Small core). This task defines the **Protocol**.
- `record_entry` never raises into a node body.

## Steps

1. `class SessionStats(BaseModel)` — `model`, `input_tokens`,
   `output_tokens`, `cost`, all optional.
2. `class SessionStatsProvider(Protocol)` — `stats(session_id, cwd)` and
   `final_stop_reason(session_id, cwd)`.
3. `usage_from_acp(usage) -> dict | None` (port `build_acp_usage`), and
   `merge_usage(acp, provider)` — **ACP wins for tokens, the provider
   supplies cost**. Two sources disagreeing is normal; the precedence is
   not a judgement call to make per call site.
4. `build_entry(*, node, attempt, status, model, usage, tool_calls,
   duration_s, session_id, repair_turns) -> dict`, omitting unknowns.
5. `format_stats_line(entry) -> str` (port).
6. `async def record_entry(ctx, entry)`: one uow →
   `log.append(engine, kind=stats, …)`, `tasks.set_stats`, emit
   `agent.stats`. Guarded so a second call within the same `run()` is a
   no-op, and it never raises — a stats failure must not fail a task
   that succeeded.

## Verification

`tests/agents/test_stats_unit.py`, porting the pure parts of v0's
`test_stats.py`:

- `build_entry` omits unknown fields entirely (assert the key is absent,
  not that it is `None`);
- `merge_usage` precedence both ways round;
- the formatter's output shape;
- `record_entry` twice writes one row;
- `record_entry` with a store that raises logs and returns.

## Done

- Tests pass; no zero-filling anywhere.
- `**Status.** Done.` on `### T036`, in the same commit.

## Files

```
athanore/agents/stats.py
tests/agents/test_stats_unit.py
docs/v1/17-serial-task-plan.md
```
