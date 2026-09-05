# 20 — Carried findings from the MVP

05, 06, 12, and 15 cite `docs/bugs/claude-acp.md` and
`docs/design/permissions.md` for decisions the MVP learned the hard way.
Those files are git-ignored in the MVP repository (14 §Repository
changes, 15 open question 4), so the findings v1 depends on are folded
here and the other documents point at this one. Nothing below is new; it
is the evidence behind D10, D11, and the env-scrubbing rule in 12.

Source: integrating athanore 0.0.9 with
`@agentclientprotocol/claude-agent-acp` 0.70.0 (ACP Python SDK 0.12.1),
2026-08; verified fixed in the MVP and re-verified against pi-acp.

## Finding 1 — permission options must be chosen by `kind`, never by index

ACP models permission semantics in `PermissionOption.kind ∈ {allow_once,
allow_always, reject_once, reject_always}`; list order is unspecified.
`claude-agent-acp` lists rejection first:

```js
options: [
  { kind: "reject_once",  name: "Deny",         optionId: "reject" },
  { kind: "allow_once",   name: "Allow Once",   optionId: "allow" },
  { kind: "allow_always", name: "Always Allow", optionId: "allow_always" },
]
```

The MVP's original `options[0]` "auto-approve" therefore denied every tool
call, and the run still completed with `[stats] … ok`: nothing raised, no
retry, no dead-letter, no agent log line, and the truncation guard does
not cover it.

**Rules v1 keeps (D10):**

- `auto_allow` selects `allow_once`, then `allow_always`; `auto_deny`
  selects `reject_once`, then `reject_always`; `ask` shows the agent's
  options verbatim and lets the operator pick.
- Prefer `*_once`: in this adapter `allow_always` installs a whole-tool
  session rule (`addRules: [{toolName}]`) that silently disables per-call
  policy for the rest of the run.
- A policy that cannot be honoured (no option of the wanted kind) raises
  `AgentError`. Failing loudly beats reporting success.
- A run in which every permission was denied is almost certainly failed;
  the stats entry records `denied_permissions` when > 0 so the SPA can
  flag it (new in v1, cheap).

## Finding 2 — config options are resolved by `category`, ids are agent-specific

After `session/new`, claude-agent-acp advertised:

| id | category | values |
|---|---|---|
| `mode` | `mode` | `auto default acceptEdits plan dontAsk bypassPermissions` |
| `model` | `model` | `default opus[1m] claude-fable-5[1m] sonnet haiku` |
| `effort` | `thought_level` | `default low medium high xhigh max` |
| `fast` | `model_config` | `on off` |

pi-acp uses the id `thought_level` for the same category. The MVP sent
the pi id as if it were universal, the adapter rejected it, and a bare
`except: pass` hid the rejection.

**Rules v1 keeps (D11):** `ACPAgent.model` is set through the option whose
`category == "model"`, `ACPAgent.thinking` through `category ==
"thought_level"`, falling back to the ids `model` / `thought_level` when
the session advertises no categories. A rejected set is logged at
WARNING and written to the transcript as a `notice` chunk; it never
fails the run and is never silent.

## Finding 3 — the ACP client must be an extension point

The MVP's client class was defined inside `run()`, so changing the
permission policy meant forking 150 lines. v1 keeps the fix: a
module-level `ACPClient` referenced by `ACPAgent.client_class`, with the
policies as overridable methods (05 §Policies).

## Finding 4 — the agent subprocess must not inherit session-scoped variables

A server started from inside a Claude Code session handed its children
`CLAUDECODE`, `CLAUDE_CODE_MESSAGING_SOCKET`, `CLAUDE_CODE_MESSAGING_TOKEN`,
`CLAUDE_PID`, and friends. No behaviour change was measured; the concern
is isolation and reproducibility.

**Rules v1 keeps (12 §Agents):** scrub variables starting with `CLAUDE_`,
plus `CLAUDECODE` and `CLAUDE_PID`, before spawning; merge the explicit
`env`; `env_allowlist` for allow-nothing-by-default; set
`ATHANORE_TASK_URL` and `ATHANORE_TASK_TOKEN` last.

## Caveat — ACP permission requests are advisory

With a correct kind-based policy in `default` mode, `rm -rf` was
escalated and denied, while `git add -A && git commit -m wip` was never
escalated and ran. Seven tool calls produced four permission requests.
A policy built on `request_permission` is an audit trail with a veto on
what the agent chooses to ask about, not an enforcement boundary. The
boundary that held was the agent's own deny rules
(`.claude/settings.local.json` → `{"permissions": {"deny": ["Bash(git
commit:*)", "Bash(git push:*)"]}}`), enforced before the client is
consulted; `deny` rules are honoured from any settings tier, escalating
`defaultMode` values only from the local or user tier.

v1 states this in 05 and 12 and recommends containers for anything that
executes code (the `docker_acp` example).

## Checked and found sound (still true for v1)

- `fs/*` and `terminal/*` answering `method_not_found`: agents do their
  own I/O.
- Empty `ClientCapabilities` accepted.
- Protocol version 1 on both sides; SDK `>=0.12,<0.13`.
- Truncation detection (a final turn consumed by reasoning and reported
  as `end_turn`) is a real failure mode; in v1 it lives behind
  `SessionStatsProvider.final_stop_reason` (D27).

## Permission-channel decisions carried from `docs/design/permissions.md`

- One channel for permissions, elicitations, node questions, and HTTP
  asks (later generalised into 06); answers keyed to their request, never
  FIFO; replies never resolve permissions and decisions never resolve
  questions.
- `ask` is the default policy; `permission_timeout` with
  `permission_timeout_action` (default `deny`) is the headless fallback,
  recorded as an `engine`-authored answer so the audit trail shows who
  decided.
- The TUI auto-switched to the agent pane on a new request, with an
  opt-out (`ATHANORE_NO_AUTO_REQUESTS=1`); v1 keeps the behaviour as an
  SPA preference (10 §Attention).
