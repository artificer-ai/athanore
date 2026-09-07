# `examples/pi` — the pi adapter

Everything about [pi](https://github.com/earendil-works/pi) that
athanore itself must not know. The package ships no vendor knowledge
(02 §Small core, D14): what to spawn, how an agent reaches its task, and
where a run's cost can be read from are all facts about pi, and they
live here.

```python
from pi import PiAgent

class Reviewer(PiAgent):
    system_prompt = "You review one branch and answer with a verdict."
    output_model = Review
    model = "openrouter/qwen/qwen3.8-max"
```

Three lines in `agent.py` are the whole of "this seat is pi":

| | |
|---|---|
| `command = ["npx", "-y", "pi-acp@0.0.33"]` | the ACP adapter, pinned rather than floating (12 §Supply chain) |
| `tooling = "native"` | the tier below |
| `stats_provider = PiSessionStats()` | cost and truncation, read from pi's session JSONL (D27) |

## The `native` tier

An agent needs four things: read its task, append to the work log,
submit a result, ask the operator. 05 §Tooling tiers delivers them
three ways, all of them over the one agent HTTP API of 08:

- **`mcp`** — athanore's own MCP server, handed over on `session/new`.
  Chosen automatically when the agent's `initialize` response advertises
  `mcpCapabilities.http`.
- **`native`** — the agent's own harness registers the tools. That is
  this directory's `extensions/athanore.ts`.
- **`http`** — the fallback: curl lines in the prompt, with the task
  token in a header line the model can read.

pi takes the middle one, and it has to be *declared*: pi-acp 0.0.33
advertises `mcpCapabilities: {http: false, sse: false}` and pi 0.84 has
no MCP client (verified 2026-09-05), so `tooling="auto"` would negotiate
its way down to `http` and put the task token back in the prompt.

**That is what the tier is for.** In `native`, athanore exports
`ATHANORE_TASK_URL` and `ATHANORE_TASK_TOKEN` to the subprocess
(19 §Environment), the extension reads them from the environment, and
the token never appears in anything the model sees — so it never reaches
the model provider (12 §Task tokens). The prompt carries the tool names
instead:

> You have these tools for your task: get_task (read it), append_log
> (your deliverable), submit_result (your structured result, when one is
> required), ask_operator and wait_answer (only if you genuinely need
> something from the human operator — sparingly).

## `extensions/athanore.ts`

Five tools, registered with `pi.registerTool()`, each one a call to the
agent HTTP API:

| Tool | Call |
|---|---|
| `get_task` | `GET {base}` — title, description and the full work log |
| `append_log` | `POST {base}/log` |
| `submit_result` | `POST {base}/submit` |
| `ask_operator` | `POST {base}/ask` (403 unless the seat sets `ask_policy="http"`) |
| `wait_answer` | `GET {base}/requests/{id}?wait=` |

`{base}` is `ATHANORE_TASK_URL`, which athanore sets to
`{public_url}/api/agent/tasks/{task_id}`. The token goes in the
`X-Athanore-Token` header and nowhere else — never in a query parameter,
a body or a URL.

`submit_result`'s input schema **is** the node's `output_model` schema:
the extension reads it from `output_schema` on the `GET {base}` response
(08) at startup, so pi shows the model the required shape as a tool
definition rather than as prose. A task that declares no model gets a
permissive object; the endpoint is the validator either way, and its 422
— errors plus schema — comes back as the tool's error text so the model
can fix the submission inside the same turn.

### Installing it

pi auto-discovers `~/.pi/agent/extensions/*.ts`. The dev stack mounts
this directory there for every service (`compose.yaml`), so an agent
dispatched with `./scripts/agent.sh pi` has the tools, and an edit to the
extension is live in the next run with no rebuild. Elsewhere, copy or
symlink the file:

```sh
ln -s "$PWD/examples/pi/extensions/athanore.ts" ~/.pi/agent/extensions/
```

To try it by hand against a running athanore, inside the dev stack — where
the mount already puts it on the discovery path:

```sh
ATHANORE_TASK_URL=http://127.0.0.1:4002/api/agent/tasks/12 \
ATHANORE_TASK_TOKEN=… pi
```

To point a run at one particular copy of the file instead, pass `-ne`
alongside `-e`: loading a discovered extension and an explicit one that
register the same tool names is an error, and pi refuses to start.

```sh
ATHANORE_TASK_URL=… ATHANORE_TASK_TOKEN=… \
  pi -ne -e examples/pi/extensions/athanore.ts
```

## `stats.py`

pi writes a session JSONL under `~/.pi/agent/sessions`
(`$PI_CODING_AGENT_DIR/sessions` when that is set). `PiSessionStats`
reads it for the two things no protocol carries: what the session cost,
and whether its final turn was cut off at the model's output cap — which
is how a run that spent its whole budget inside a reasoning block is
reported `failed (truncated)` rather than silently empty (05 §Truncation
detection).

Token counts come from ACP when the adapter sends them and from this
file otherwise. Nothing is zero-filled: a counter that is not in the
file is left out of the `[stats]` line, and a `$0.0000` appears only
when a message actually reported one.

## Tests

```sh
./scripts/dev.sh "uv run pytest -q examples"
```

`test_pi_stats.py` covers the session reader, `test_pi_extension.py` the
extension (its tools, the endpoints they call, and a `pi -e` smoke that
is skipped where pi is not installed), and `test_pi_agent.py` the seat
itself.
