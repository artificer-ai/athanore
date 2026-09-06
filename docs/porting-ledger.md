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
| ☑ | `test_permissions.py` | `tests/agents/test_policies.py` (the policy assertions: reject-first ordering under `auto_allow`, `auto_deny`, a policy that cannot be honoured, the `ask` request and its options, the engine-authored timeout answer, the bounded tool-call summary, done); `tests/agents/test_acp_outcomes.py` and `tests/agents/test_tooling.py` carry the round trip over the ACP wire — reject-first resolved to `allow_once` and answered to the agent, a filesystem permission opening a request and blocking the turn, and the count of denials in the stats entry (done) | T038, T039a, T039b |
| ☑ | `test_elicitation.py` | `tests/agents/test_policies.py` (the form request and its registered validator, the accept, and the declines — policy, URL mode, no schema, no context, timeout — done; the MVP's `test_schema_validator` is `tests/requests/test_validators.py`'s from T030); `tests/agents/test_acp_outcomes.py` carries the end-to-end elicitation over ACP — the form bridged to a request, answered by the operator, and the `accept` that reached the agent; and the URL mode declined without one (done) | T038, T039a |
| ☑ | `test_acp_stats.py` | `tests/agents/test_acp_outcomes.py` (one entry per `run()` on each of the five exits — success, refusal, timeout, no-submission, shutdown-cancel — the ACP `usage` path, the provider's cost and model, truncation through `FakeStatsProvider`, and the unknowns that are omitted rather than zeroed; the builders and the `[stats]` line itself are `tests/agents/test_stats_unit.py`'s from T036, done) | T036, T039a |
| ☐ | `test_submissions.py` | `tests/agents/test_acp_outcomes.py` carries the repair loop over the ACP wire — the same session, `max_repair_turns` as a budget, the rejected payload quoted back, and the second submission winning (done); `tests/api/test_agent_api.py` still carries the endpoint half, which is the 422 and its schema | T039a, T045 |
| ☐ | `test_agents.py` | `tests/agents/test_prompt.py` carries the prompt assertions (the inlined `system_prompt`, the assignment section and its separator, and the blocks of 19 present or absent by config — v0's `template=` cases go with the feature, 05, and its `model` assertions belong to `ACPAgent`; done); `tests/agents/test_acp_lifecycle.py` carries the session over a real subprocess — the handshake, config options by category, the env scrub and the allowlist, `agent_command`, and permissions by kind (done); `tests/agents/` (remainder) carries the vendor-shaped rest | T034, T039, T039a, T040 |
| ☐ | `test_stats.py` | `tests/agents/test_stats_unit.py` carries the pure parts — the ACP usage read, the merge precedence, the entry's omissions and 18's payload, the formatted line, and recording the entry to its three destinations (done); `examples/tests/test_pi_stats.py` still carries the session-file half, which is pi's knowledge and stays out of the package (D27) | T036, T040 |
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
| ☑ | `tests/fake_acp.py` | `athanore/testing/fake_acp.py`, driven by `tests/testing/test_fake_acp.py` against a raw ACP client: v0's argv flags became the JSON scenario vocabulary of 13 §Fakes, and every key of it is exercised. T039a's "`tests/fake_acp.py` deleted" has nothing left to delete — v1 never had one (D65) | T037 |
| ☐ | `tests/smoke_acp.py` | `ATHANORE_SMOKE`-gated smoke test | T077 |
