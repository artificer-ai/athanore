/**
 * athanore's four capabilities as pi tools — the `native` tooling tier.
 *
 * 05 §Tooling tiers gives an agent four things: read its task, append to
 * the work log, submit a result, ask the operator. The `http` tier puts
 * them in the prompt as curl lines with the task token inline; `mcp`
 * hands them over as an MCP server. pi has neither an MCP client nor a
 * reason to shell out, so it gets the third tier: this extension, which
 * registers the same five tools against the same agent HTTP API of 08
 * (D63).
 *
 * The token never reaches the model. `ATHANORE_TASK_URL` and
 * `ATHANORE_TASK_TOKEN` are exported to the subprocess by the façade
 * (19 §Environment), read here, and sent in the `X-Athanore-Token`
 * header — never as a query parameter, never in a body, never in a URL
 * (12 §Task tokens). A prompt in this tier therefore carries no curl and
 * no credential, which is the whole point of the tier.
 *
 * Install: pi auto-discovers `~/.pi/agent/extensions/*.ts`, and
 * `compose.yaml` mounts this directory there for every service. To try
 * it against a running athanore by hand:
 *
 *     ATHANORE_TASK_URL=http://127.0.0.1:4002/api/agent/tasks/12 \
 *     ATHANORE_TASK_TOKEN=… pi -e examples/pi/extensions/athanore.ts
 *
 * See `examples/pi/README.md` for the tier, and 19 for the prompt text
 * these descriptions are taken from: the model's instructions and its
 * tools have to agree, so the wording is 19's, not a paraphrase.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent"

/** One tool's JSON Schema, exactly as the API and the model see it. */
type Schema = Record<string, unknown>

/** What `execute` hands back to pi (`AgentToolResult`). */
type ToolResult = { content: { type: "text"; text: string }[]; details: unknown }

/**
 * `registerTool` wants a TypeBox `TSchema`. At run time that is a plain
 * JSON Schema object plus a symbol TypeScript uses for parameter
 * inference, and nothing here can use the inference: `submit_result`'s
 * schema is the node's `output_model` and is not known until it has been
 * fetched. So the schemas below are written as plain JSON Schema and
 * cross over through this one cast rather than importing typebox — which
 * also keeps this file loadable by anything that can strip types.
 */
type PiTool = Parameters<ExtensionAPI["registerTool"]>[0]

/** How long a tool call waits for athanore before giving up, in ms. */
const REQUEST_TIMEOUT_MS = 130_000

/**
 * The submission schema used when the task declares no `output_model`,
 * or when the schema could not be read. Permissive on purpose: the
 * endpoint is the validator (08 §Agent-facing), and a guessed schema
 * here would reject payloads athanore would have accepted.
 */
const ANY_OBJECT: Schema = { type: "object", additionalProperties: true }

/** 19's own wording, so the tools and the prompt say the same thing. */
const DESCRIPTIONS = {
  get_task:
    "Read your task: the title, description, and the FULL work log — " +
    "deliverables and notes from every earlier stage and attempt.",
  append_log:
    "Append your deliverable to the run's work log. Your own deliverable " +
    "MUST be appended before you finish — the next stage reads this same log.",
  submit_result:
    "Submit your structured result for this task. The result must conform " +
    "to this tool's input schema.",
  ask_operator:
    "Ask the human operator for something you genuinely need (a decision, " +
    "a missing detail) — sparingly. Pass options for a pick-one question. " +
    "Returns a request_id; wait for the answer with wait_answer, and " +
    "continue only once you have it.",
  wait_answer:
    "Wait for the operator's answer to a request you opened, repeating " +
    'until it says "answered": true. Continue only once you have the answer.',
} as const

/**
 * The task API, or an explanation of why there is none.
 *
 * Read per call rather than once: pi may be started before the
 * environment names a task, and a tool that failed for the life of the
 * process because of the order two things happened in is a worse failure
 * than one that says what is missing.
 */
function endpoint(): { base: string; token: string } {
  const base = process.env.ATHANORE_TASK_URL
  const token = process.env.ATHANORE_TASK_TOKEN
  if (!base || !token) {
    throw new Error(
      "athanore: ATHANORE_TASK_URL / ATHANORE_TASK_TOKEN are not set, so this " +
        "pi is not running against a task. Start it from an athanore workflow.",
    )
  }
  return { base: base.replace(/\/+$/, ""), token }
}

/**
 * One call to the agent HTTP API, with the token in the one place it is
 * allowed to be.
 *
 * A non-2xx throws, which is how pi marks a tool result as an error: the
 * body is kept in the message because it is the useful part — the 422
 * from `/submit` carries the validation errors and the schema, and that
 * is exactly what the model needs to fix its submission in this same
 * turn (05 §Submissions).
 */
async function call(method: string, path: string, body?: unknown): Promise<string> {
  const { base, token } = endpoint()
  const headers: Record<string, string> = { "X-Athanore-Token": token }
  if (body !== undefined) headers["Content-Type"] = "application/json"
  const response = await fetch(`${base}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  })
  const text = await response.text()
  if (!response.ok) {
    throw new Error(`athanore ${method} ${path} failed (HTTP ${response.status}): ${text}`)
  }
  return text
}

/** A tool result carrying the API's own JSON response. */
function said(text: string): ToolResult {
  return { content: [{ type: "text", text }], details: { response: text } }
}

/**
 * The node's `output_model` schema, from `GET /api/agent/tasks/{id}`.
 *
 * 08 puts it on that response as `output_schema` precisely so this tier
 * can show it: pi's tool definition becomes the schema the endpoint will
 * validate against, and the model sees the requirement as a tool rather
 * than as prose. A task that declares no model, or an athanore that
 * cannot be reached yet, falls back to {@link ANY_OBJECT} — and the
 * reason is reported at session start rather than dropped.
 */
async function submissionSchema(): Promise<{ schema: Schema; problem?: string }> {
  // No task in the environment is not a failure: it is `pi` started by
  // hand with the extension loaded. The tools say so when one is called.
  if (!process.env.ATHANORE_TASK_URL || !process.env.ATHANORE_TASK_TOKEN) {
    return { schema: ANY_OBJECT }
  }
  try {
    const body: unknown = JSON.parse(await call("GET", ""))
    const declared =
      typeof body === "object" && body !== null
        ? (body as { output_schema?: unknown }).output_schema
        : undefined
    if (typeof declared === "object" && declared !== null) {
      return { schema: declared as Schema }
    }
    return { schema: ANY_OBJECT }
  } catch (error) {
    return {
      schema: ANY_OBJECT,
      problem: `athanore: the task's submission schema could not be read (${String(
        error,
      )}); submit_result accepts any object and the endpoint will validate it.`,
    }
  }
}

export default async function (pi: ExtensionAPI): Promise<void> {
  const { schema, problem } = await submissionSchema()

  if (problem) {
    pi.on("session_start", async (_event, ctx) => {
      ctx.ui.notify(problem, "warning")
    })
  }

  pi.registerTool({
    name: "get_task",
    label: "athanore task",
    description: DESCRIPTIONS.get_task,
    parameters: { type: "object", properties: {}, additionalProperties: false },
    async execute(): Promise<ToolResult> {
      return said(await call("GET", ""))
    },
  } as unknown as PiTool)

  pi.registerTool({
    name: "append_log",
    label: "athanore log",
    description: DESCRIPTIONS.append_log,
    parameters: {
      type: "object",
      properties: {
        text: { type: "string", description: "The entry to append, in full." },
      },
      required: ["text"],
      additionalProperties: false,
    },
    async execute(_id: string, params: { text: string }): Promise<ToolResult> {
      return said(await call("POST", "/log", { text: params.text }))
    },
  } as unknown as PiTool)

  pi.registerTool({
    name: "submit_result",
    label: "athanore submit",
    description: DESCRIPTIONS.submit_result,
    parameters: schema,
    async execute(_id: string, params: unknown): Promise<ToolResult> {
      return said(await call("POST", "/submit", params))
    },
  } as unknown as PiTool)

  pi.registerTool({
    name: "ask_operator",
    label: "athanore ask",
    description: DESCRIPTIONS.ask_operator,
    parameters: {
      type: "object",
      properties: {
        prompt: { type: "string", description: "The question, in one sentence." },
        options: {
          type: "array",
          items: { type: "string" },
          description: "Choices, for a pick-one question.",
        },
        schema: {
          type: "object",
          additionalProperties: true,
          description: "A JSON Schema, to ask for a filled-in form instead.",
        },
      },
      required: ["prompt"],
      additionalProperties: false,
    },
    async execute(
      _id: string,
      params: { prompt: string; options?: string[]; schema?: Schema },
    ): Promise<ToolResult> {
      const body: Record<string, unknown> = { prompt: params.prompt }
      if (params.options) body.options = params.options
      if (params.schema) body.schema = params.schema
      return said(await call("POST", "/ask", body))
    },
  } as unknown as PiTool)

  pi.registerTool({
    name: "wait_answer",
    label: "athanore wait",
    description: DESCRIPTIONS.wait_answer,
    parameters: {
      type: "object",
      properties: {
        request_id: {
          type: "string",
          description: "The request_id ask_operator returned.",
        },
        wait: {
          type: "integer",
          description: "Seconds to hold the connection open, at most 120.",
          minimum: 0,
          maximum: 120,
        },
      },
      required: ["request_id"],
      additionalProperties: false,
    },
    async execute(
      _id: string,
      params: { request_id: string; wait?: number },
    ): Promise<ToolResult> {
      const wait = Math.min(Math.max(params.wait ?? 60, 0), 120)
      const id = encodeURIComponent(params.request_id)
      return said(await call("GET", `/requests/${id}?wait=${wait}`))
    },
  } as unknown as PiTool)
}
