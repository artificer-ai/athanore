// Load the athanore pi extension and report, or call, its tools.
//
// The extension is a pi module: it exports a factory that pi hands an
// `ExtensionAPI` to, and everything it does happens inside that call. So
// the smallest honest harness is the smallest `ExtensionAPI` — one that
// records what was registered — and node itself, which strips the types
// (>= 22.6) and resolves nothing the extension does not import.
//
// It is driven by `examples/tests/test_pi_extension.py`:
//
//     node probe_extension.mjs <extension.ts>                 # the tools
//     node probe_extension.mjs <extension.ts> <tool> <json>   # call one
//
// stdout is JSON and nothing else, so the caller can parse it.

import { pathToFileURL } from "node:url"

const [target, toolName, rawArguments] = process.argv.slice(2)
if (!target) {
  process.stderr.write("usage: probe_extension.mjs <extension.ts> [tool] [json]\n")
  process.exit(2)
}

const tools = []
const notifications = []
const handlers = new Map()

// The surface the extension actually uses. Anything it reaches for that
// is not here is a change worth failing on, not one to stub out blindly.
const pi = {
  registerTool(tool) {
    tools.push(tool)
  },
  on(event, handler) {
    handlers.set(event, handler)
  },
}

const extension = await import(pathToFileURL(target).href)
await extension.default(pi)

const sessionStart = handlers.get("session_start")
if (sessionStart) {
  await sessionStart(
    { type: "session_start", reason: "startup" },
    { ui: { notify: (message, level) => notifications.push({ message, level }) } },
  )
}

const registered = tools.map((tool) => ({
  name: tool.name,
  label: tool.label,
  description: tool.description,
  parameters: tool.parameters,
}))

if (!toolName) {
  process.stdout.write(JSON.stringify({ tools: registered, notifications }))
  process.exit(0)
}

const tool = tools.find((candidate) => candidate.name === toolName)
if (!tool) {
  process.stdout.write(JSON.stringify({ error: `no tool named ${toolName}` }))
  process.exit(1)
}

try {
  const result = await tool.execute("call-1", JSON.parse(rawArguments ?? "{}"))
  process.stdout.write(JSON.stringify({ result }))
} catch (error) {
  process.stdout.write(JSON.stringify({ error: String(error && error.message) }))
}
