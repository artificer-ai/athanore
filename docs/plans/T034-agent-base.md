# T034 — Agent base: `Agent`, `AgentResult`, prompt assembly

**Task.** `docs/v1/17-serial-task-plan.md` § `### T034`.
**Specs.** `docs/v1/05-agents.md` §Agent and §AgentResult;
**`docs/v1/19-agent-prompts.md` — the prompt blocks, byte for byte**;
`docs/v1/12-security.md` §Task tokens.
**Reference.** v0's `tests/test_agents.py` prompt assertions.

## What this task is

The agent façade's base class and, more importantly, the prompt
assembly. `AGENTS.md`: agent prompts are inlined text, and the kickoff,
ask, submission and repair blocks are **byte-exact per 19** — the fake
ACP agent parses them, so a stray word breaks the test agent.

## What this task is not

- No ACP. T037 writes `acp.py`; this class's `run()` raises
  `NotImplementedError`.
- No templates, ever. Prompt text lives on the class.
- No policy handling (T035, T038) beyond recording `ask_policy` on the
  context.

## Steps

1. `class AgentError(Exception)`; `@dataclass class AgentResult` with
   05's fields and an `ok` property; `class Agent` with 05's class
   attributes and `async run(prompt="")`.
2. `render_prompt(prompt, ctx) -> str`, assembling exactly:
   the system prompt, `---`, `## Your assignment`, `---`, `## Your task`
   (with the `curl -H "X-Athanore-Token: {token}"
   {api_base}/api/agent/tasks/{id}` lines), `## Asking the operator`
   **only** when `ask_policy == "http"`, and `## Submitting your result`
   **only** with an `output_model` (the `POST …/submit` curl plus
   `json.dumps(model_json_schema(), indent=2)`).
   Outside a task context the task section is omitted, with a warning.
3. `declare(ctx)` — an async context manager setting `ctx.output_model`,
   `ctx.ask_policy` and `ctx.last_rejection = None`, restoring the
   previous values on exit so nested agents do not clobber each other.

## Careful

The token appears **only** in a header. No `?token=`, no `_token` query
parameter, nowhere in a URL — a token in a URL ends up in logs
(`AGENTS.md` §Local first, 12 §Task tokens). The test asserts its
absence across the whole rendered prompt.

## Verification

`tests/agents/test_prompt.py`, porting v0's assertions:

- each section present or absent according to config;
- the token appears in the header form only;
- neither `?token=` nor `_token` appears anywhere in the prompt;
- the blocks match 19 byte for byte — compare against the document's
  text, not against a copy you retyped.

## Done

- Tests pass; prompt text matches 19 exactly.
- `**Status.** Done.` on `### T034`, in the same commit.

## Files

```
athanore/agents/base.py
tests/agents/test_prompt.py
docs/v1/17-serial-task-plan.md
```
