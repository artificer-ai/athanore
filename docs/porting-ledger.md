# Porting ledger

The MVP's test suite is v1's acceptance harness (14). Every file below is
ported to the v1 layout by the task named, and the rule is **ported test =
deleted old test**: a row is ticked in the same commit that deletes the
MVP file, so "MVP tests still running against MVP code" only ever goes
down.

Source is `tests/` in the MVP checkout. Targets are the v1 paths named by
`docs/v1/17-serial-task-plan.md`.

| ✓ | MVP test | v1 target | Task |
|---|---|---|---|
| ☐ | `test_graph.py` | `tests/graph/test_builder.py` | T019 |
| ☐ | `test_edit_run.py` | `tests/engine/test_ops_basic.py`, `tests/api/test_runs_api.py` | T027a, T044a |
| ☐ | `test_pause.py` | `tests/engine/test_ops_basic.py`, `tests/api/test_runs_api.py` | T027a, T044a |
| ☐ | `test_run_log.py` | `tests/engine/test_ops_basic.py`, `tests/api/test_runs_api.py` | T027a, T044a |
| ☐ | `test_management.py` | `tests/engine/test_ops_tasks.py`, `tests/api/test_runs_api.py` | T027b, T044a |
| ☐ | `test_deterministic.py` | `tests/engine/test_behaviours.py` | T028 |
| ☐ | `test_fanout.py` | `tests/engine/test_behaviours.py` | T028 |
| ☐ | `test_priority.py` | `tests/engine/test_behaviours.py`, `tests/api/test_runs_api.py` | T028, T044a |
| ☐ | `test_worker_pools.py` | `tests/engine/test_behaviours.py` | T028 |
| ☐ | `test_qa_gate.py` | `tests/engine/test_behaviours.py` | T028 |
| ☐ | `test_requests.py` | `tests/requests/test_service.py` | T031 |
| ☐ | `test_permissions.py` | `tests/agents/test_policies.py`, `tests/agents/test_acp_outcomes.py` | T038, T039a |
| ☐ | `test_elicitation.py` | `tests/agents/test_policies.py`, `tests/agents/test_acp_outcomes.py` | T038, T039a |
| ☐ | `test_acp_stats.py` | `tests/agents/test_acp_outcomes.py` | T039a |
| ☐ | `test_submissions.py` | `tests/agents/test_acp_outcomes.py`, `tests/api/test_agent_api.py` | T039a, T045 |
| ☐ | `test_agents.py` | `tests/agents/test_acp_outcomes.py`, `tests/agents/` (remainder) | T039a, T040 |
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
| ☐ | `tests/conftest.py` | `tests/conftest.py` (engine fixture), `tests/store/conftest.py` | T028 |
| ☐ | `tests/fake_acp.py` | `athanore/testing/` `FakeACPAgent` (`tests/testing/test_fake_acp.py`) | T039a |
| ☐ | `tests/smoke_acp.py` | `ATHANORE_SMOKE`-gated smoke test | T077 |
