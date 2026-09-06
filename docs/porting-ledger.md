# Porting ledger

The MVP's test suite is v1's acceptance harness (14). Every file below is
ported to the v1 layout by the task named, and the rule is **ported test =
ticked row** (D65): nothing is deleted, because the MVP is a separate
checkout that this repository never writes to. A row is ticked in the
commit that lands its v1 test, so what is left unticked is what v1 has
not yet covered.

Source is `tests/` in the MVP checkout. Targets are the v1 paths named by
`docs/v1/17-serial-task-plan.md`.

| ✓ | MVP test | v1 target | Task |
|---|---|---|---|
| ☑ | `test_graph.py` | `tests/graph/test_builder.py` | T019 |
| ☑ | `test_edit_run.py` | `tests/engine/test_ops_basic.py` (the store and edit assertions, done); `tests/api/test_runs_api.py` still carries the `PATCH` half | T027a, T044a |
| ☑ | `test_pause.py` | `tests/engine/test_ops_basic.py` (pause blocks the next claim, resume dispatches, the invalid transitions as `Conflict`, done); `tests/api/test_runs_api.py` still carries the 404/409 half | T027a, T044a |
| ☑ | `test_run_log.py` | `tests/engine/test_ops_basic.py` (author, node and the empty-text refusal, done); `tests/api/test_runs_api.py` still carries the request-body half | T027a, T044a |
| ☑ | `test_management.py` | `tests/engine/test_ops_tasks.py` (rerun, retry, move, cancel and delete, done); `tests/api/test_runs_api.py` still carries the HTTP half, and v0's `swap-priority` is `reorder` there | T027b, T044a |
| ☑ | `test_deterministic.py` | `tests/engine/test_behaviours.py` | T028 |
| ☑ | `test_fanout.py` | `tests/engine/test_behaviours.py` | T028 |
| ☑ | `test_priority.py` | `tests/store/test_claim.py` (the ordering assertions) and `tests/engine/test_behaviours.py` (the same order through `task.started`, done); `tests/api/test_runs_api.py` still carries the API half | T015a, T028, T044a |
| ☑ | `test_worker_pools.py` | `tests/engine/test_behaviours.py` (dedicated, shared, default and zero-capacity pools, and what `Engine.register` refuses; the two registrations v0 refused and v1 allows are pinned there and recorded in D112) | T028 |
| ☑ | `test_qa_gate.py` | `tests/engine/test_behaviours.py` (the loop-backs, with the MVP's `MockAgent` stages as plain bodies — agents are Phase 2) | T028 |
| ☑ | `test_requests.py` | `tests/requests/test_service.py` (the modes, the four refusals, keyed answers under two waiters, `reopen` and the wake-up guard, done); `tests/requests/test_human_input.py` and `test_human_input_replay.py` carry `human_input` end to end — the three modes, the released slot and the ordinal replay v0 had no equivalent of (done); the answer endpoint and the CLI `answer` verb are the surfaces above the service and are carried by their own tasks | T031, T033, T044a, T054a |
| ☐ | `test_permissions.py` | `tests/agents/test_policies.py`, `tests/agents/test_acp_outcomes.py` | T038, T039a |
| ☐ | `test_elicitation.py` | `tests/agents/test_policies.py`, `tests/agents/test_acp_outcomes.py` | T038, T039a |
| ☐ | `test_acp_stats.py` | `tests/agents/test_acp_outcomes.py` | T039a |
| ☐ | `test_submissions.py` | `tests/agents/test_acp_outcomes.py`, `tests/api/test_agent_api.py` | T039a, T045 |
| ☐ | `test_agents.py` | `tests/agents/test_prompt.py` carries the prompt assertions (the inlined `system_prompt`, the assignment section and its separator, and the blocks of 19 present or absent by config — v0's `template=` cases go with the feature, 05, and its `model` assertions belong to `ACPAgent`; done); `tests/agents/test_acp_outcomes.py` and `tests/agents/` (remainder) carry the rest | T034, T039a, T040 |
| ☐ | `test_stats.py` | `tests/agents/test_stats_unit.py`, `examples/tests/test_pi_stats.py` | T036, T040 |
| ☐ | `test_stats_workflow.py` | `tests/agents/` | T040 |
| ☐ | `test_ask.py` | `tests/api/test_agent_api.py` | T045 |
| ☐ | `test_web_serve.py` | `tests/api/test_static.py` | T047 |
| ☐ | `test_cli_entry.py` | `tests/cli/test_inspect_verbs.py`, `tests/cli/test_steer_verbs.py` | T054, T054a |
| ☐ | `test_e2e.py` | `tests/api/test_e2e.py` | T055 |
| ☐ | `test_api_surface.py` | `tests/api/test_e2e.py` | T055 |
| ☐ | `test_tui.py` | **retired** — the TUI is deleted with the MVP wire API (D13) | T055 |
| ☐ | `test_gamedev.py` | `examples/tests/test_gamedev.py` | T075 |

Support files, ported or deleted alongside the tests they serve:

| ✓ | MVP file | v1 target | Task |
|---|---|---|---|
| ☑ | `tests/conftest.py` | `tests/engine/conftest.py` (`start_engine`, `run_to_completion`; **not** `tests/conftest.py`, where `engine` is shadowed — D112), `tests/store/conftest.py` | T028 |
| ☐ | `tests/fake_acp.py` | `athanore/testing/` `FakeACPAgent` (`tests/testing/test_fake_acp.py`) | T039a |
| ☐ | `tests/smoke_acp.py` | `ATHANORE_SMOKE`-gated smoke test | T077 |
