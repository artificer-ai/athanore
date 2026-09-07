"""The read-only verbs, against a live server (T054, 11 §Verbs).

The read half of the MVP's `test_cli_entry.py`, which asserted that a
command routed. That is not the interesting question any more: v1's
verbs each render a real API response, so what is asserted here is what
an operator reads on their terminal and what a script reads out of
`--json` — the same call twice, from the same server.

Every verb appears in both forms for that reason. The table is checked
for what it projects (a joined node list, an age, the suffix on a
workflow this server no longer has) and `--json` for being the API's own
shape, key for key, so the two cannot drift into two contracts.

The three following verbs (`ls --watch`, `logs -f`, `stream -f`) are the
part no single response can test. Each is started as a real invocation in
a thread, waited for until it is genuinely subscribed to the event
stream, and only then given something to see. Everything around them —
the setup and the polling — goes through `Api` rather than through a
second CLI call, because `capsys` is one buffer and a CLI call made mid
follow would drain the follower's output into somebody else's assertion.
"""

from __future__ import annotations

import asyncio
import socket
import webbrowser

import pytest

from athanore.cli import inspect, main
from athanore.cli.output import EXIT_API_ERROR, EXIT_OK, EXIT_UNREACHABLE, EXIT_USAGE
from athanore.server import Server
from tests.cli.conftest import (
    AFTER_ANSWER,
    PROMPT,
    Api,
    Cli,
    flat,
    listening,
    until,
)

#: A ULID-shaped id of no run, for the 404s.
ABSENT_RUN = "01NOTAREALRUNID0000000000"


def dead_url() -> str:
    """A loopback URL with nothing listening on it.

    A socket is bound to find a free port and then closed, which is the
    only way to name a port that is certainly nobody's.
    """

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}"


# --------------------------------------------------------------------------
# submit
# --------------------------------------------------------------------------


async def test_submit_queues_a_run_and_prints_its_id(cli: Cli, api: Api) -> None:
    """`submit` is `POST /api/workflows/{name}/runs` and its answer."""

    result = await cli.run("submit", "demo", "Build the thing", "with care")
    assert result.code == EXIT_OK
    assert "run_id:" in result.out

    created = await cli.json("submit", "demo", "Build another", "carefully")
    assert set(created) == {"run_id"}
    detail = await api.run(created["run_id"])
    assert detail["title"] == "Build another"
    assert detail["description"] == "carefully"


async def test_submit_of_an_unknown_workflow_reports_the_api_error(cli: Cli) -> None:
    """A 404 is exit 1 with the sentence the server wrote (11 §Exit codes)."""

    result = await cli.run("submit", "ghost", "nowhere")
    assert result.code == EXIT_API_ERROR
    assert "ghost" in flat(result.err)


# --------------------------------------------------------------------------
# ls
# --------------------------------------------------------------------------


async def test_ls_lists_runs_in_dispatch_order(cli: Cli, api: Api) -> None:
    """The table is the run list, in the order the scheduler will claim."""

    first = await api.completed("demo", "First")
    second = await api.completed("demo", "Second")

    result = await cli.run("ls")
    assert result.code == EXIT_OK
    assert "WORKFLOW" in result.out and "TITLE" in result.out
    assert result.out.index(first) < result.out.index(second)

    listed = await cli.json("ls")
    # The API shape, unprojected: a script reads `current_nodes` and
    # `pending_requests`, which the table joins and counts.
    assert [run["id"] for run in listed] == [first, second]
    assert "current_nodes" in listed[0] and "pending_requests" in listed[0]


async def test_ls_filters_by_status_and_by_workflow(cli: Cli, api: Api) -> None:
    """`--status` and `--workflow` are the API's own query parameters."""

    done = await api.completed("demo", "Finished")
    parked = await api.submit("parked", "Held open")
    await until(
        lambda: api.is_status(parked, "running"), what="the parked run to start"
    )

    completed = await cli.json("ls", "--status", "completed")
    assert [run["id"] for run in completed] == [done]

    of_parked = await cli.json("ls", "--workflow", "parked")
    assert [run["id"] for run in of_parked] == [parked]


async def test_ls_marks_a_run_this_server_cannot_dispatch(
    cli: Cli, server: Server
) -> None:
    """`unregistered` becomes a suffix on the workflow, not a lost fact (03)."""

    async with server.store.uow() as uow:
        ghost = await uow.runs.insert("ghost", "A run of a workflow that went away")

    result = await cli.run("ls")
    assert "ghost (unregistered)" in result.out
    listed = await cli.json("ls")
    row = next(run for run in listed if run["id"] == ghost.id)
    assert row["unregistered"] is True


async def test_ls_watch_redraws_when_a_run_changes(
    cli: Cli, api: Api, server: Server
) -> None:
    """`--watch` follows the SSE feed and draws the list again (17 §T054)."""

    before = len(server.bus.subscriptions)
    follower = cli.follower("ls", "--watch")
    await listening(server, before)

    run = await api.submit("demo", "Seen by the watcher")
    await until(lambda: api.is_status(run, "completed"), what="the new run to finish")
    # Ending the server ends the stream, and the reconnect then has
    # nowhere to go: 11 §Exit codes' 3.
    await server.stop()
    assert await follower == EXIT_UNREACHABLE

    printed = cli.capsys.readouterr().out
    assert "Seen by the watcher" in printed
    # Drawn more than once: the first draw could not have carried a run
    # that did not exist yet.
    assert printed.count("WORKFLOW") > 1


# --------------------------------------------------------------------------
# show
# --------------------------------------------------------------------------


async def test_show_prints_the_run_its_tasks_and_its_log(cli: Cli, api: Api) -> None:
    """11 §Verbs: `show <run>` is the run, its attempts and its work log."""

    run = await api.completed("demo", "Build the thing", "with care")
    result = await cli.run("show", run)
    assert result.code == EXIT_OK
    assert f"run {run}" in result.out
    assert "title: Build the thing" in result.out
    assert "description: with care" in result.out
    assert "output: shipped" in result.out
    # Both tables, each by a value only that table carries.
    assert "review" in result.out
    assert "planned it" in result.out

    detail = await cli.json("show", run)
    assert detail["id"] == run
    assert [task["node"] for task in detail["tasks"]] == ["plan", "review"]
    # The `RunDetail` with the work log added under `log`: every key the
    # API's own, and the two reads one object.
    assert [entry["text"] for entry in detail["log"]] == ["planned it"]


async def test_show_of_a_run_that_does_not_exist_is_the_api_error(cli: Cli) -> None:
    """Exit 1, with the message the server sent."""

    result = await cli.run("show", ABSENT_RUN)
    assert result.code == EXIT_API_ERROR
    assert "does not exist" in flat(result.err)


# --------------------------------------------------------------------------
# logs
# --------------------------------------------------------------------------


async def test_logs_prints_a_runs_stored_events(cli: Cli, api: Api) -> None:
    """The history, as a table of the envelopes 08 §Events fixes."""

    run = await api.completed("demo", "Build the thing")
    result = await cli.run("logs", run)
    assert result.code == EXIT_OK
    assert "run.created" in result.out
    assert "run.completed" in result.out

    events = await cli.json("logs", run)
    names = [event["name"] for event in events]
    assert names[0] == "run.created" and names[-1] == "run.completed"
    assert events[0]["run_id"] == run


async def test_logs_pages_through_a_history_longer_than_one_page(
    cli: Cli, api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A verb that printed one page would quietly lose a run's history."""

    run = await api.completed("demo", "Build the thing")
    whole = await api.events(run)
    assert len(whole) > 2

    monkeypatch.setattr(inspect, "PAGE", 2)
    paged = await cli.json("logs", run)
    assert [event["id"] for event in paged] == [event["id"] for event in whole]


async def test_logs_follow_prints_events_as_they_happen(
    cli: Cli, api: Api, server: Server
) -> None:
    """`-f` follows the run's SSE feed and prints what arrives on it."""

    run = await api.submit("parked", "Held open")
    await until(lambda: api.is_status(run, "running"), what="the parked run to start")

    before = len(server.bus.subscriptions)
    follower = cli.follower("logs", run, "-f")
    await listening(server, before)

    await api.post(f"/api/runs/{run}/log", {"text": "written while following"})
    await until(
        lambda: _seen(api, run, "log.appended"),
        what="the note to be stored as an event",
    )
    await server.stop()
    assert await follower == EXIT_UNREACHABLE

    printed = cli.capsys.readouterr().out
    assert "run.created" in printed  # the stored page it started from
    assert "log.appended" in printed  # and the event that happened after it


async def _seen(api: Api, run: str, name: str) -> bool:
    """Whether ``run`` has stored an event of that name yet."""

    return any(event["name"] == name for event in await api.events(run))


# --------------------------------------------------------------------------
# stream
# --------------------------------------------------------------------------


async def test_stream_prints_an_attempts_transcript(cli: Cli, api: Api) -> None:
    """The transcript is prose; only a kind that is not `text` is labelled."""

    run = await api.completed("demo", "Build the thing")
    task = (await api.run(run))["tasks"][0]["id"]

    result = await cli.run("stream", str(task))
    assert result.code == EXIT_OK
    assert "reading the task" in result.out
    assert "[thought] this looks easy" in result.out

    page = await cli.json("stream", str(task))
    assert [chunk["kind"] for chunk in page["chunks"]] == ["text", "thought"]
    assert page["last_seq"] == 2
    assert page["live"] is False


async def test_stream_pages_through_a_transcript_longer_than_one_page(
    cli: Cli, api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A verb that printed one page would quietly truncate a transcript."""

    run = await api.completed("demo", "Build the thing")
    task = (await api.run(run))["tasks"][0]["id"]
    whole = await api.get(f"/api/tasks/{task}/stream", limit=5000)
    assert len(whole["chunks"]) > 1

    monkeypatch.setattr(inspect, "PAGE", 1)
    paged = await cli.json("stream", str(task))
    # One `StreamOut`, however many pages it took to read it.
    assert [chunk["seq"] for chunk in paged["chunks"]] == [
        chunk["seq"] for chunk in whole["chunks"]
    ]
    assert paged["last_seq"] == whole["last_seq"]
    assert paged["live"] is False

    result = await cli.run("stream", str(task))
    assert result.code == EXIT_OK
    assert "reading the task" in result.out
    assert "[thought] this looks easy" in result.out


async def test_stream_follow_prints_a_flush_bigger_than_a_page(
    cli: Cli, api: Api, server: Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One `task.stream` event can announce more chunks than a page holds."""

    monkeypatch.setattr(inspect, "PAGE", 1)
    request = await api.one_request("chatty")
    task = int(request["task_id"])

    before = len(server.bus.subscriptions)
    follower = cli.follower("stream", str(task), "-f")
    await listening(server, before)

    await api.post(f"/api/requests/{request['id']}/answer", {"value": "carry on"})
    assert await follower == EXIT_OK

    printed = cli.capsys.readouterr().out
    # Every chunk of the one flush, not the first page of it.
    assert [text for text in AFTER_ANSWER if text in printed] == AFTER_ANSWER


async def test_stream_follow_ends_when_the_attempt_does(
    cli: Cli, api: Api, server: Server
) -> None:
    """A transcript that can no longer grow ends the follow, successfully."""

    request = await api.one_request("chatty")
    task = int(request["task_id"])

    before = len(server.bus.subscriptions)
    follower = cli.follower("stream", str(task), "-f")
    await listening(server, before)

    await api.post(f"/api/requests/{request['id']}/answer", {"value": "carry on"})
    assert await follower == EXIT_OK

    printed = cli.capsys.readouterr().out
    assert "first thing" in printed  # written before the follower attached
    assert "second thing" in printed  # and after the answer released the body


# --------------------------------------------------------------------------
# workflows
# --------------------------------------------------------------------------


async def test_workflows_shows_each_graph_and_its_pool(cli: Cli) -> None:
    """11 §Verbs: `workflows` is graphs plus pools."""

    result = await cli.run("workflows")
    assert result.code == EXIT_OK
    assert "demo  start=plan  pool=default 0/4" in result.out
    assert "parked  start=hold  pool=holding 0/2" in result.out
    # The graph itself: a node, and where it can go from there.
    assert "review" in result.out
    assert "(terminal)" in result.out

    listed = await cli.json("workflows")
    demo = next(wf for wf in listed if wf["name"] == "demo")
    assert demo["start"] == "plan"
    assert demo["pool"] == "default"
    assert demo["nodes"]["plan"]["edges"] == ["review"]


# --------------------------------------------------------------------------
# requests
# --------------------------------------------------------------------------


async def test_requests_lists_what_is_waiting_on_a_person(cli: Cli, api: Api) -> None:
    """The inbox, across every run, with the options an answer may name."""

    view = await api.one_request("ask_options")

    result = await cli.run("requests")
    assert result.code == EXIT_OK
    assert PROMPT in result.out
    assert str(view["id"]) in result.out
    assert "yes" in result.out and "no" in result.out

    listed = await cli.json("requests")
    assert [request["id"] for request in listed] == [view["id"]]
    assert listed[0]["mode"] == "options"
    assert listed[0]["pending"] is True


async def test_requests_of_one_run_is_that_runs_requests(cli: Cli, api: Api) -> None:
    """The optional positional is the API's `run` filter, not a client one."""

    first = await api.one_request("ask_text")
    await api.one_request("ask_options")
    assert len(await api.requests()) == 2

    listed = await cli.json("requests", str(first["run_id"]))
    assert [request["id"] for request in listed] == [first["id"]]


# --------------------------------------------------------------------------
# open
# --------------------------------------------------------------------------


async def test_open_points_a_browser_at_the_run(
    cli: Cli, api: Api, server: Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The SPA's linkable state is one route with `?run=` (10 §Routing)."""

    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)

    run = await api.completed("demo", "Build the thing")
    result = await cli.run("open", run)
    assert result.code == EXIT_OK
    assert opened == [f"{server.url}/?run={run}"]
    assert opened[0] in result.out

    opened.clear()
    assert await cli.json("open") == {"url": server.url}
    assert opened == [server.url]


async def test_open_refuses_a_run_that_does_not_exist(
    cli: Cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tab pointed at nothing is worse than the 404 the server already has."""

    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)

    result = await cli.run("open", ABSENT_RUN)
    assert result.code == EXIT_API_ERROR
    assert opened == []


# --------------------------------------------------------------------------
# The bare-workflow alias
# --------------------------------------------------------------------------


async def test_a_bare_workflow_name_submits_a_run(cli: Cli, api: Api) -> None:
    """`athanore demo "title"` is `athanore submit demo "title"` (11 §Verbs)."""

    created = await cli.json("demo", "Through the alias", "and its description")
    detail = await api.run(created["run_id"])
    assert detail["workflow"] == "demo"
    assert detail["title"] == "Through the alias"
    assert detail["description"] == "and its description"


async def test_a_verb_is_never_read_as_a_workflow(cli: Cli, api: Api) -> None:
    """The first half of the check: a reserved name is the verb it names."""

    await api.completed("demo", "Build the thing")
    result = await cli.run("ls")
    assert result.code == EXIT_OK
    assert "Build the thing" in result.out


async def test_a_word_that_is_neither_names_both_possibilities(cli: Cli) -> None:
    """The second half: a typo is a clean usage error, not a mystery 404."""

    result = await cli.run("dmeo", "Build the thing")
    assert result.code == EXIT_USAGE
    said = flat(result.err)
    assert "'dmeo' is not an athanore verb" in said
    assert "runs no workflow of that name" in said


async def test_the_alias_says_so_when_the_server_cannot_be_asked(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With no server, neither half of the check has been ruled out.

    Still exit 2 and not 3: the word did not resolve to a verb, which is
    a mistake in what was typed, and 3 belongs to a verb that resolved
    and then found nobody to ask (`tests/cli/test_client.py` pins the
    same code for an unknown verb).
    """

    code = await asyncio.to_thread(
        main, ["--url", dead_url(), "feature_build", "Build it"]
    )
    assert code == EXIT_USAGE
    said = flat(capsys.readouterr().err)
    assert "'feature_build' is not an athanore verb" in said
    assert "could not be asked whether it is a workflow" in said


# --------------------------------------------------------------------------
# The server that is not there, and the server with nothing on it
# --------------------------------------------------------------------------


async def test_a_server_that_is_not_there_is_exit_three(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """11 §Exit codes: 3 is "no server", and is not 1 ("the server said no")."""

    code = await asyncio.to_thread(main, ["--url", dead_url(), "ls"])
    assert code == EXIT_UNREACHABLE
    assert "Error:" in capsys.readouterr().err


async def test_nothing_to_show_is_still_json_and_still_a_table(cli: Cli) -> None:
    """An empty list is `[]`, so a script never special-cases "none"."""

    assert await cli.json("ls") == []
    assert await cli.json("requests") == []

    result = await cli.run("ls")
    # The headings still print: a verb that found nothing and a verb that
    # printed nothing must not look the same.
    assert result.code == EXIT_OK
    assert "WORKFLOW" in result.out
