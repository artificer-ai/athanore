# Runs, retries and capacity

A run is one execution of one workflow. Submitting one creates the run
and a task at the start node; from there the engine dispatches tasks
against explicit capacity, retries what fails, and gives you verbs for
everything it cannot decide by itself.

## Submitting

```sh
athanore submit feature_build "Add the export button" "Notes for the run"
```

The same thing over HTTP is a `POST` to the workflow's runs collection,
and from a plugin action it is `ctx.ops.submit(...)`. A new run is
`queued`, not `running`: waiting for a slot is a state you can see, and
the first claim of one of its tasks is what flips it.

## Pools and capacity

A pool is a named concurrency cap, and a workflow is registered on
exactly one:

```python
from athanore import Pool, Server

from myproject.flows import feature_build, gamedev


def main() -> None:
    server = Server()
    server.register(feature_build, Pool("local", 1))
    server.register(gamedev, Pool("cloud", 8))
    server.serve()
```

Or, if you serve from the command line, in `athanore.toml` beside the
database:

```toml
[pools]
local = 1
cloud = 8

[workflows]
feature_build = { pool = "local" }
gamedev = { pool = "cloud" }
```

There is no lending between pools: capacity reserved for `local` stays
reserved even when `local` is idle. A pool with a capacity of zero parks
its workflows — they queue and never dispatch, which is a way to hold
work without cancelling it. A workflow nothing binds runs on the default
pool, sized by `workers`.

A task's pool follows its run's workflow and never changes.

## Dispatch order

Within a pool, the order is:

1. the run's position in the list — which is what `athanore position`
   changes, so promoting a run promotes all of its work;
2. inside a run, nodes given an explicit `priority` first, in that
   order;
3. then downstream nodes before upstream ones, so a run in flight
   finishes rather than widening;
4. then newest first.

A retry keeps its original creation time, so a node that keeps failing
cannot keep jumping the queue.

## Retries and dead-letter

When a body raises, the attempt is marked failed and the failure is
appended to the work log. If the exception is retryable and the node has
attempts left, another one is queued with the same payload; when they run
out, the task is dead-lettered and the run is marked failed.

`retries` is per node, defaulting to the server's `max_retries`.
`GraphError` and `NonRetryable` skip retrying entirely — see
[Writing a workflow](workflows.md#rule-3-the-exception-is-the-failure-policy).

Two branches of one fan-out can fail together. The first verdict is the
run's; the second records its own task events without overwriting it.

## Steering a run

Every one of these is transactional and emits an event, and each has a
command-line verb, an HTTP endpoint and a plugin operation:

- **pause** stops a run dispatching; tasks already in flight finish.
  **resume** lets it dispatch again.
- **cancel** ends the run and everything under it, cancelling in-flight
  attempts and killing their agent subprocesses.
- **delete** cancels and then removes the run and all of its rows.
- **rerun** queues a fresh task at a node you name, with that node's last
  payload; for a join node it replays the arrivals it had.
- **retry** queues another attempt of a task that is not currently
  runnable.
- **move** cancels a task and queues one at another node with the same
  payload. Moving *into* a join node is refused, because it would bypass
  the arrival accounting.
- **position** moves a run up, down, or to an index in the dispatch list.
- **edit** changes a run's title or description.

Moving or retrying keeps the payload, which under a fan-out is the
branch's identity.

## After a restart

There is no separate recovery mode to run. On start, every task that was
in progress or waiting is reset to ready and an event lists them; runs
whose workflow is not registered on this server are left alone and marked
so, and never dispatch.

An attempt that was interrupted re-executes from the beginning, so agent
work wants to be roughly idempotent — and a body parked on a question
re-attaches to the request it already opened rather than asking again.

A graceful stop leaves the store in exactly the same state as a crash:
interrupted rows are not written to, because `cancelled` is reserved for
what an operator meant.

## Draining

There is no drain mode: agent attempts run for hours, and waiting for
them is not a shutdown. The operator's drain is to pause every run and
wait for the in-flight task count on the health endpoint to reach zero.
That count is literally in-progress tasks — a waiting task holds no slot
and needs a person rather than time, so counting it would mean a drain
that never finished while one question sat unanswered.

## Watching

```sh
athanore ls --watch          # the run table, live
athanore logs <run> -f       # a run's events, followed
athanore stream <task> -f    # one task's agent transcript
```

All three follow the server-sent event stream and remember the last
event they saw, so a dropped connection resumes rather than replaying
from zero. The same stream is what the browser interface uses; see
[Driving the API](http-api.md).

## Next

- [Writing a plugin](plugins.md) — your own panes and buttons on these
  runs.
- [Events](../reference/events.md) — every event name and what it
  carries.
