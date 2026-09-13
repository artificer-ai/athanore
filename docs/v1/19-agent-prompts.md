# 19 — Agent prompt text (normative)

The prompt an agent receives is behaviour: small models are sensitive to
its wording, and every example workflow was tuned against the MVP's
text. v1 carries that text verbatim except for the two changes 05 and 12
require: agent routes live under `/api/agent/`, and the token travels only
in the `X-Athanore-Token` header. Tests assert these blocks byte for byte
(13 §Agent façade).

Placeholders: `{base}` = `{api_base}/api/agent/tasks/{task_id}`,
`{token}` = the task token, `{title}` = the run title quoted, or empty.

## Assembly

```
<system_prompt>                       (class attribute, stripped)

---

## Your assignment

<prompt argument>                     (omitted with its separator when empty)

---

## Your task                          (omitted outside a task context)
<kickoff core>
<tier block>                          (mcp/native: tool list; http: curl lines)
<ask instructions>                    (http tier only, when ask_policy == "http")
<submission instructions>             (http tier only, when output_model is set)
```

With no `system_prompt` the prompt argument is sent alone, followed by
the task sections. Sections are joined with a blank line. On the `none`
tier (05 §Tooling tiers, D271) the task sections are omitted exactly as
they are outside a task context — the agent gets the system prompt and
the assignment, and nothing that names a task, a token or a tool.

## Kickoff (tool-agnostic core)

Sent in every tier. It names the four capabilities without saying how
they are reached; the tier block below it says how.

```
## Your task

Work on task {task_id}{title} — stage "{node}" of workflow "{workflow}" (run {run_id}).

Start by reading your task: the title, description, and the FULL work log — deliverables and notes from every earlier stage and attempt. Your own deliverable MUST be appended to the run's work log before you finish — the next stage reads this same log.
```

### Tier block: `mcp` and `native`

```
You have these tools for your task: get_task (read it), append_log (your deliverable), submit_result (your structured result, when one is required), ask_operator and wait_answer (only if you genuinely need something from the human operator — sparingly).
```

With `output_model` set, the submission instructions below are replaced
by one line: `When you have finished, call submit_result; its schema is
the tool's input schema.` The ask instructions are omitted (the tool
description carries them) and `ask_operator` is absent from the tool list
unless `ask_policy == "http"`.

### Tier block: `http` (the MVP's curl text)

Follows the core directly; together they read exactly as the MVP's
kickoff did.

```
Read your task with:
curl -sS {base} -H 'X-Athanore-Token: {token}'

Append your deliverable with:
curl -sS -X POST {base}/log -H 'Content-Type: application/json' -H 'X-Athanore-Token: {token}' -d '{"text": "<text>"}'
```

## Ask instructions (`ask_policy="http"`)

```
If you genuinely need something from the human operator (a decision, a missing detail), you may ask — sparingly:
curl -sS -X POST {base}/ask -H 'Content-Type: application/json' -H 'X-Athanore-Token: {token}' -d '{"prompt": "<your question>"}'
Add "options": ["a", "b"] for a pick-one question. The response carries a request_id. Then wait for the answer, repeating until it says "answered": true:
curl -sS '{base}/requests/<request_id>?wait=60' -H 'X-Athanore-Token: {token}'
Continue only once you have the answer.
```

## Submission instructions (`output_model` set)

```
When you have finished, you MUST submit your structured result by running exactly this (replacing <json> with your JSON result):
curl -sS -X POST {base}/submit -H 'Content-Type: application/json' -H 'X-Athanore-Token: {token}' -d '<json>'
The JSON must conform to this schema:
{schema}
```

`{schema}` is `json.dumps(output_model.model_json_schema(), indent=2)`.

## Repair turn (same session, up to `max_repair_turns`)

When the last submission was rejected:

```
Your turn ended, but no valid structured result was received for this task — your last submission was rejected with these validation errors:
{errors as JSON, indent=2}
Rejected payload:
{payload as JSON, first 2000 characters}
.
Do not redo the work. Fix the result and submit it now.
<submission instructions>
```

When nothing was submitted:

```
Your turn ended, but no valid structured result was received for this task (nothing was submitted).
Do not redo the work. Fix the result and submit it now.
<submission instructions>
```

## Environment handed to the subprocess

`ATHANORE_TASK_URL={base}` and `ATHANORE_TASK_TOKEN={token}` are exported
so an adapter that can read its environment may keep the token out of
the transcript; the prompt still carries the curl lines because most
harnesses cannot. Neither is exported on the `none` tier.

## Rules

- The token appears only in `-H 'X-Athanore-Token: …'`. Never as a query
  parameter, never in a JSON body, never in a URL.
- The word `curl` and the exact flag order are part of the contract: the
  examples' `.claude/settings.local.json` allow-rules and the MVP's
  smoke tests match on them.
- Changing any block is a decision (15) and a minor release.
