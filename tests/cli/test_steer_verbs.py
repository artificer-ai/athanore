"""The verbs that change something, against a live server (T054a, 11 §Verbs).

The write half of the MVP's `test_cli_entry.py`. One rule shapes every
test here: **assert the effect, not the exit code**. A verb that returned
0 and changed nothing is a verb that does not work, so what each test
checks is the state the API reports afterwards — through `Api`, a plain
`httpx` client, never through a second CLI call. Reading a change back
through the client that made it would only prove the client agrees with
itself.

Two things get more than one test each, because they are where the
mistakes are:

- **`answer`**, which has to pick between an option id, some text and a
  JSON object from arguments that look identical on a command line. The
  request's own mode decides, and each of the three is checked by what
  the *node body* was handed — the run's output — rather than by what was
  posted;
- **the refusals**, which must be the server's sentence and not one the
  CLI invented (11 §Exit codes' 1). The 409 test asks the API for the
  message first and then looks for that exact sentence on stderr.
"""

from __future__ import annotations

import io
import json
from typing import Any

import httpx
import pytest

from athanore.cli.output import EXIT_API_ERROR, EXIT_OK, EXIT_USAGE
from athanore.server import Server
from tests.cli.conftest import Api, Cli, flat, until


async def answered_output(api: Api, run: str) -> Any:
    """The value a run returned once its question was answered.

    The node body returns what ``human_input`` gave it, so the run's
    output *is* what the CLI's answer decoded to — which is the only
    place the difference between an option id, a string and an object is
    visible.
    """

    await until(lambda: api.is_status(run, "completed"), what=f"run {run} to finish")
    return (await api.run(run))["output"]


async def task_at(api: Api, run: str, node: str) -> dict[str, Any]:
    """The newest attempt of ``node`` in ``run``."""

    tasks = [task for task in (await api.run(run))["tasks"] if task["node"] == node]
    assert tasks, f"run {run} has no attempt of {node}"
    return tasks[-1]


async def count_at(api: Api, run: str, node: str) -> int:
    """How many attempts of ``node`` the run has."""

    return len([t for t in (await api.run(run))["tasks"] if t["node"] == node])


# --------------------------------------------------------------------------
# answer: one argument, three shapes
# --------------------------------------------------------------------------


async def test_answer_sends_text_for_a_text_request(cli: Cli, api: Api) -> None:
    """The words are joined and reach the body as the string typed."""

    view = await api.one_request("ask_text")
    result = await cli.run("answer", str(view["id"]), "looks", "good", "to", "me")
    assert result.code == EXIT_OK
    assert await answered_output(api, view["run_id"]) == "looks good to me"


async def test_answer_does_not_retype_a_text_answer_that_looks_like_json(
    cli: Cli, api: Api
) -> None:
    """A text question answered `{"ok": true}` must not send a dict (17 §T054a).

    The mode is what the resolution turns on, so a `text` request gets
    the characters that were typed — which is also the only way the CLI
    can express an answer that happens to look like an object.
    """

    view = await api.one_request("ask_text")
    result = await cli.run("answer", str(view["id"]), '{"ok": true}')
    assert result.code == EXIT_OK
    assert await answered_output(api, view["run_id"]) == '{"ok": true}'


async def test_answer_sends_an_option_id_for_an_options_request(
    cli: Cli, api: Api
) -> None:
    """An `options` request is answered with the id it offered."""

    view = await api.one_request("ask_plain")
    result = await cli.run("answer", str(view["id"]), "approve")
    assert result.code == EXIT_OK
    assert await answered_output(api, view["run_id"]) == "approve"


async def test_answer_sends_an_object_for_a_form_request(cli: Cli, api: Api) -> None:
    """A `form` request takes JSON, and the body gets the validated model."""

    view = await api.one_request("ask_form")
    result = await cli.run("answer", str(view["id"]), '{"verdict": "ship"}')
    assert result.code == EXIT_OK
    assert await answered_output(api, view["run_id"]) == {"verdict": "ship"}


async def test_answer_prints_the_answer_it_recorded(cli: Cli, api: Api) -> None:
    """The response is the updated `RequestView` (08 §Requests)."""

    view = await api.one_request("ask_text")
    answered = await cli.json("answer", str(view["id"]), "yes please")
    assert answered["id"] == view["id"]
    assert answered["answer"] == "yes please"
    assert answered["answered_by"] == "user"
    assert answered["pending"] is False


async def test_a_form_answer_that_is_not_an_object_is_the_servers_refusal(
    cli: Cli, api: Api
) -> None:
    """The CLI does not second-guess the schema; the request service does."""

    view = await api.one_request("ask_form")
    result = await cli.run("answer", str(view["id"]), "ship it")
    assert result.code == EXIT_API_ERROR
    assert "must be an object" in flat(result.err)
    # And the request is still there to answer properly.
    assert [request["id"] for request in await api.requests()] == [view["id"]]


async def test_an_option_that_was_not_offered_is_the_servers_refusal(
    cli: Cli, api: Api
) -> None:
    """`invalid_option` is 06 §Errors', and the message lists what is offered."""

    view = await api.one_request("ask_plain")
    result = await cli.run("answer", str(view["id"]), "maybe")
    assert result.code == EXIT_API_ERROR
    said = flat(result.err)
    assert "'maybe' is not an option" in said
    assert "approve" in said


# --------------------------------------------------------------------------
# permit and deny
# --------------------------------------------------------------------------


async def test_permit_picks_the_allow_kind_whatever_the_order(
    cli: Cli, api: Api
) -> None:
    """The agent lists rejection first; `permit` must still allow (20 §Finding 1)."""

    view = await api.one_request("ask_options")
    assert view["options"][0]["kind"] == "reject_once"

    result = await cli.run("permit", str(view["id"]))
    assert result.code == EXIT_OK
    assert await answered_output(api, view["run_id"]) == "yes"


async def test_deny_picks_the_reject_kind(cli: Cli, api: Api) -> None:
    """`deny` is the same call under the other preference order."""

    view = await api.one_request("ask_options")
    result = await cli.run("deny", str(view["id"]))
    assert result.code == EXIT_OK
    assert await answered_output(api, view["run_id"]) == "no"


async def test_permit_with_an_option_id_uses_that_option(cli: Cli, api: Api) -> None:
    """An explicit id is sent as it stands; the server owns the list."""

    view = await api.one_request("ask_options")
    result = await cli.run("permit", str(view["id"]), "yes-always")
    assert result.code == EXIT_OK
    assert await answered_output(api, view["run_id"]) == "yes-always"


async def test_permit_of_a_request_that_is_not_a_choice_says_so(
    cli: Cli, api: Api
) -> None:
    """The one refusal the server has no equivalent of, so the CLI words it."""

    view = await api.one_request("ask_text")
    result = await cli.run("permit", str(view["id"]))
    assert result.code == EXIT_API_ERROR
    said = flat(result.err)
    assert "is a `text` request" in said
    assert f"athanore answer {view['id']}" in said
    assert (await api.requests())[0]["pending"] is True


async def test_permit_of_options_with_no_allow_kind_says_what_is_offered(
    cli: Cli, api: Api
) -> None:
    """`human_input(options=["approve", "reject"])` carries no kinds at all."""

    view = await api.one_request("ask_plain")
    result = await cli.run("permit", str(view["id"]))
    assert result.code == EXIT_API_ERROR
    said = flat(result.err)
    assert "no option of kind allow_once or allow_always" in said
    assert "approve" in said and "reject" in said


# --------------------------------------------------------------------------
# pause, resume, cancel
# --------------------------------------------------------------------------


async def test_pause_and_resume_move_a_run_through_its_state_machine(
    cli: Cli, api: Api
) -> None:
    """Both are visible through the API, which is where the run state lives."""

    run = await api.submit("parked", "Held open")
    await until(lambda: api.is_status(run, "running"), what="the run to start")

    assert (await cli.run("pause", run)).code == EXIT_OK
    assert await api.status(run) == "paused"

    assert (await cli.run("resume", run)).code == EXIT_OK
    assert await api.status(run) == "running"


async def test_cancel_ends_the_run_and_says_what_it_stopped(cli: Cli, api: Api) -> None:
    """The `note` names the attempts that were killed (08 §Runs)."""

    run = await api.submit("parked", "Held open")
    await until(lambda: api.is_status(run, "running"), what="the run to start")

    result = await cli.run("cancel", run)
    assert result.code == EXIT_OK
    assert "1 attempt cancelled" in flat(result.out)
    assert await api.status(run) == "cancelled"


async def test_a_conflict_is_exit_one_with_the_servers_own_message(
    cli: Cli, api: Api, server: Server
) -> None:
    """11 §Exit codes' 1: the sentence the API wrote, not one invented here."""

    run = await api.completed("demo", "Build the thing")
    async with httpx.AsyncClient(base_url=server.url) as http:
        refusal = await http.post(f"/api/runs/{run}/pause")
    assert refusal.status_code == 409
    sentence = refusal.json()["error"]

    result = await cli.run("pause", run)
    assert result.code == EXIT_API_ERROR
    assert sentence in flat(result.err)


# --------------------------------------------------------------------------
# rm
# --------------------------------------------------------------------------


async def test_rm_deletes_the_run_with_yes(cli: Cli, api: Api) -> None:
    """`--yes` is the answer a script gives to the confirmation."""

    run = await api.completed("demo", "Build the thing")
    result = await cli.run("rm", run, "--yes")
    assert result.code == EXIT_OK
    assert run in result.out

    with pytest.raises(httpx.HTTPStatusError) as refused:
        await api.run(run)
    assert refused.value.response.status_code == 404


async def test_rm_asks_first_and_a_no_deletes_nothing(
    cli: Cli, api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The confirmation is the guard; answering it `n` leaves the run alone."""

    monkeypatch.setattr("sys.stdin", io.StringIO("n\n"))
    run = await api.completed("demo", "Build the thing")

    result = await cli.run("rm", run)
    assert result.code == EXIT_API_ERROR
    assert "Delete run" in result.out
    assert (await api.run(run))["id"] == run


async def test_rm_asks_first_and_a_yes_deletes(
    cli: Cli, api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    """And answering it `y` is the same deletion `--yes` performs."""

    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
    run = await api.completed("demo", "Build the thing")

    assert (await cli.run("rm", run)).code == EXIT_OK
    with pytest.raises(httpx.HTTPStatusError) as refused:
        await api.run(run)
    assert refused.value.response.status_code == 404


# --------------------------------------------------------------------------
# rerun, retry, move, set-status
# --------------------------------------------------------------------------


async def test_rerun_queues_a_fresh_attempt_of_a_node(cli: Cli, api: Api) -> None:
    """The whole run goes on from there; the answer is the new task's id."""

    run = await api.completed("demo", "Build the thing")
    before = await count_at(api, run, "review")

    queued = await cli.json("rerun", run, "review")
    assert queued["task_id"] > 0
    task = await api.task(queued["task_id"])
    assert task["node"] == "review"
    assert await count_at(api, run, "review") == before + 1


async def test_retry_queues_another_attempt_of_a_task(cli: Cli, api: Api) -> None:
    """A task that has stopped gets attempt n+1 of the same node."""

    run = await api.completed("demo", "Build the thing")
    done = await task_at(api, run, "review")

    queued = await cli.json("retry", str(done["id"]))
    retried = await api.task(queued["task_id"])
    assert retried["node"] == "review"
    assert retried["attempt"] == done["attempt"] + 1


async def test_move_re_routes_a_tasks_work_to_another_node(cli: Cli, api: Api) -> None:
    """The work lands at the named node, in a new attempt (08 §Tasks)."""

    run = await api.completed("demo", "Build the thing")
    plan = await task_at(api, run, "plan")
    before = await count_at(api, run, "review")

    moved = await cli.json("move", str(plan["id"]), "review")
    assert (await api.task(moved["task_id"]))["node"] == "review"
    assert await count_at(api, run, "review") == before + 1


async def test_move_to_a_node_that_does_not_exist_is_the_api_error(
    cli: Cli, api: Api
) -> None:
    """`unknown_node` is the server's, and so is the sentence."""

    run = await api.completed("demo", "Build the thing")
    plan = await task_at(api, run, "plan")

    result = await cli.run("move", str(plan["id"]), "nowhere")
    assert result.code == EXIT_API_ERROR
    assert "nowhere" in flat(result.err)


async def test_set_status_writes_one_of_the_three_an_operator_may_set(
    cli: Cli, api: Api
) -> None:
    """08 §Tasks: `ready`, `cancelled`, `dead_letter`, and nothing else."""

    run = await api.completed("demo", "Build the thing")
    task = await task_at(api, run, "review")

    result = await cli.run("set-status", str(task["id"]), "dead_letter")
    assert result.code == EXIT_OK
    assert (await api.task(task["id"]))["status"] == "dead_letter"


async def test_set_status_refuses_a_status_that_is_not_an_operators(
    cli: Cli, api: Api
) -> None:
    """A fourth status is a usage error (2), refused before anything is sent."""

    run = await api.completed("demo", "Build the thing")
    task = await task_at(api, run, "review")

    result = await cli.run("set-status", str(task["id"]), "done")
    assert result.code == EXIT_USAGE
    assert (await api.task(task["id"]))["status"] == "done"


# --------------------------------------------------------------------------
# edit and position
# --------------------------------------------------------------------------


async def test_edit_writes_the_fields_it_is_given(cli: Cli, api: Api) -> None:
    """A field the command line does not name is left alone."""

    run = await api.completed("demo", "Build the thing", "with care")

    assert (await cli.run("edit", run, "--title", "Renamed")).code == EXIT_OK
    detail = await api.run(run)
    assert detail["title"] == "Renamed"
    assert detail["description"] == "with care"

    await cli.run("edit", run, "--description", "and then some")
    detail = await api.run(run)
    assert detail["title"] == "Renamed"
    assert detail["description"] == "and then some"


async def test_edit_json_is_the_run_detail_the_api_answered_with(
    cli: Cli, api: Api
) -> None:
    """`--json` is the wire contract, not the two fields the table shows."""

    run = await api.completed("demo", "Build the thing")
    detail = await cli.json("edit", run, "--title", "Renamed")
    assert detail["title"] == "Renamed"
    assert [task["node"] for task in detail["tasks"]] == ["plan", "review"]


async def test_position_swaps_with_a_neighbour_and_moves_to_an_index(
    cli: Cli, api: Api
) -> None:
    """`up`, `down` and a zero-based index, as D57 defines them."""

    runs = [await api.submit("parked", f"Held {n}") for n in range(3)]
    assert await _positions(api, runs) == [1, 2, 3]

    assert (await cli.run("position", runs[2], "up")).code == EXIT_OK
    assert await _positions(api, runs) == [1, 3, 2]

    assert (await cli.run("position", runs[0], "down")).code == EXIT_OK
    assert await _positions(api, runs) == [2, 3, 1]

    # Zero-based: `0` is the top of the list, whatever it held before.
    moved = await cli.json("position", runs[0], "0")
    assert moved == {"position": 1}
    assert await _positions(api, runs) == [1, 3, 2]


async def test_position_refuses_a_word_that_is_not_a_direction(cli: Cli) -> None:
    """Neither `up`, `down` nor a number is a usage error (11 §Exit codes)."""

    result = await cli.run("position", "01SOMETHING", "sideways")
    assert result.code == EXIT_USAGE
    assert "sideways" in flat(result.err)


async def _positions(api: Api, runs: list[str]) -> list[int]:
    """Where each of ``runs`` sits in the dispatch list, in submission order."""

    listed = {run["id"]: run["position"] for run in await api.get("/api/runs")}
    return [listed[run] for run in runs]


# --------------------------------------------------------------------------
# The shape of what a steering verb prints
# --------------------------------------------------------------------------


async def test_json_output_is_the_api_response_unchanged(
    cli: Cli, api: Api, server: Server
) -> None:
    """A steering verb's `--json` is what the endpoint answered, key for key."""

    run = await api.submit("parked", "Held open")
    await until(lambda: api.is_status(run, "running"), what="the run to start")

    printed = await cli.json("pause", run)
    async with httpx.AsyncClient(base_url=server.url) as http:
        # The same endpoint on a run that is already paused refuses, so
        # the shape is checked against what `Ok` serialises to instead.
        assert (await http.post(f"/api/runs/{run}/pause")).status_code == 409
    assert printed == json.loads('{"ok": true, "note": null}')
