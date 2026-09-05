# 12 — Security

## Posture: a local tool

Athanore runs on the operator's own machine and talks to agents the
operator chose to run. The default deployment is one person, one process,
loopback only. v1 does not add ceremony to that case: there is no login,
no operator token, no rate limiting. The goals are narrower:

1. **Don't get worse than the machine you run on by accident.** Binding
   to a network interface is an explicit choice and turns on the one
   control that matters there (an operator token).
2. **Agents get exactly one task's rights.** A per-task token lets an
   agent read its task, append to the log, submit a value, and ask a
   question. It cannot answer requests, touch other tasks, or steer runs.
3. **Cheap hygiene is free.** Fixes that cost nothing (do not return
   tokens in responses, accept them in a header only, cascade deletes)
   are done regardless of deployment.

Threats in scope: an agent escalating beyond its task, a runaway agent
filling the disk, a token ending up in logs or history, a LAN bind done
without meaning to. Out of scope: multi-user isolation, malicious
operators, protecting one operator from another.

## Trust boundaries

```
┌── operator's machine ────────────────────────────────────────────────┐
│  Browser (SPA)  ─────────▶  Athanore server  ◀──task token──  agents  │
│  CLI            ─────────▶      │                    │  (subprocesses,│
│   (loopback, no auth)           ▼                    │   containers)  │
│                          SQLite / Postgres            ▼               │
│                                                  model providers      │
└──────────────────────────────────────────────────────────────────────┘
```

Three principals: the **operator** (full control), an **agent** (one
task's rights), and **workflow code / plugins** (trusted at install time;
they run in-process on the server and, for JS assets, in the operator's
browser).

## Review of the MVP

These are the findings from reading the MVP with this posture in mind.
Severities are for the intended local deployment; the LAN column says
what changes if you bind to `0.0.0.0`, which the MVP did by default.

| # | Finding | Local | On a LAN bind | v1 |
|---|---|---|---|---|
| S1 | No authentication on operator endpoints; default bind `0.0.0.0`. | fine | anyone on the network can steer runs and approve agent tool calls | Default bind `127.0.0.1`. A non-loopback bind requires an operator token; the server refuses to start without one |
| S2 | `GET /api/runs/{id}` returns clear-text task tokens (`SELECT *` on tasks). A reader of the API can impersonate any in-flight agent and submit a forged result. | low (same user) | high | Tokens hashed at rest, never in any response |
| S3 | Task token accepted via `?token=` and a `_token` body field, so it lands in access logs and stored payloads. | low | medium | Header only |
| S4 | Token compared with `!=`. | negligible | low | `hmac.compare_digest` on hashes |
| S5 | No body size limit; an agent can submit an arbitrarily large payload. | low (disk) | low | 1 MiB limit, 413 |
| S6 | Agents are told `http://0.0.0.0:4002` as their API base. Works on Linux by accident; wrong for containers and remote agents. | correctness | correctness | `settings.public_url` |
| S7 | `npx -y pi-acp` resolves the latest version at every spawn. | supply chain | same | Examples pin versions |
| S8 | Agent subprocess inherits the parent env (the MVP already scrubs `CLAUDE_*`). | fine | fine | Keep scrubbing; optional `env_allowlist` |
| S9 | `delete_run` leaves request/answer rows behind. | data hygiene | same | Cascade deletes |
| S10 | `human_input` holds a worker slot; one unanswered question stalls the server under `workers=1`. | availability | same | Waiting releases the slot (04) |
| S11 | Blocking SQLite calls on the event loop stall every request and agent callback on a slow disk. | availability | same | Async driver, single writer, WAL |

Only S2, S3, S5, S6, S9 are fixed for their own sake. S1 is fixed by
changing the default bind and making the network case opt-in; nothing
else changes for the local case.

## Operator token (network binds only)

- `athanore token rotate` generates a random token (`secrets.token_urlsafe`)
  and stores it `0600` at `{root}/.athanore/token`; `athanore serve --host
  0.0.0.0` refuses to start without one. `.athanore/` is git-ignored (14).
- `require_token=true` turns the operator token on for a loopback bind
  too. That is the reverse-proxy case (§Beyond the LAN): the proxy talks
  to `127.0.0.1`, so "loopback means trusted" would silently expose the
  API through the proxy without auth.
- Sent as `Authorization: Bearer` on operator endpoints, plugin routes,
  and SSE (or `?access_token=` on the SSE path only, which is not logged).
- On loopback the token is ignored entirely, so a machine that never
  binds a network never sees a login.
- CORS is off unless `cors_origins` is set (the Vite dev server). The SPA
  is same-origin in production and no cookies are used, so there is no
  CSRF surface.
- Multi-user auth is a later seam: the dependency that resolves the
  principal is the only thing to replace.

## Task tokens

- Generated per attempt at claim (04), stored as SHA-256 only, delivered
  to the runner with the claimed row, placed in the agent's prompt (the
  curl lines) and env (`ATHANORE_TASK_TOKEN`, `ATHANORE_TASK_URL`) so
  adapters can avoid prompt text where the harness allows.
- Valid only while that attempt is `in_progress` or `waiting`; 403
  otherwise. A recovered or retried task gets a new token, so a token
  captured from a dead attempt is dead too.
- Grants exactly, and only under `/api/agent/`: read own task and the
  run's log, append log, submit, ask (if `ask_policy="http"`), poll own
  requests. Nothing else; operator routes never accept it.
- In the `mcp` and `native` tooling tiers (05) the token travels only in
  a header the harness sends or in the subprocess environment, and never
  appears in prompt text. In the `http` tier it does reach the model
  provider inside the prompt. That is accepted for the fallback: it is
  single-task, dies with the task, and grants nothing beyond what the
  agent is supposed to do anyway.

## Agents

- Env scrubbed of session-scoped variables; explicit `env` merged;
  `env_allowlist` for anyone who wants allow-nothing-by-default.
- `cwd` is the agent's workspace; the engine never writes there.
- Containerised agents via `command` are the recommended way to run
  anything that executes code. ACP permission requests are advisory
  (agents do not escalate every action; 20 §Caveat); hard limits belong
  in the agent harness or the container.
- Agent stderr is captured, capped, and logged; it never reaches another
  agent's prompt.

## Prompt injection

The work log is shared by every stage and is agent-writable, so a stage
can be steered by an earlier stage's output. That is inherent to the
product. What the platform guarantees regardless: an agent cannot move
the graph, cannot answer requests, cannot touch other tasks, and
structured submissions are schema-validated, so routing decisions are
constrained to the enum a body expects.

## Plugins

Installing a workflow package is code execution on the server and in
the operator's browser; the documentation says so. Mitigations that are
free: plugin routes are scoped to their workflow, action input is
validated server-side, assets are served by `StaticFiles` (no traversal),
the manifest carries no secrets, and the SPA ships no inline scripts so a
plain `script-src 'self'` CSP holds. The full policy is `default-src
'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src
'self'; img-src 'self' data:; connect-src 'self'` (React and the panel
splitter set inline `style` attributes, which is why `style-src` is the
one relaxation). Fonts are bundled (10), so nothing loads from a third
party.

## Beyond the LAN

v1 is HTTP. For remote access terminate TLS in a reverse proxy, keep the
bind on loopback, and set `require_token=true`; `public_url` and
`forwarded_allow_ips` make that work. Built-in TLS and rate limiting are
later seams.

## Hygiene

- Database and token file `0600`; `athanore db backup` for consistent
  copies; retention (07) prunes transcripts.
- `uv.lock` and `pnpm-lock.yaml` committed; `pip-audit` / `pnpm audit`
  in CI; adapters pinned in examples.
- Never log tokens, `Authorization` headers, or the SSE query string.
- No telemetry, and no outbound requests from the SPA to anyone but the
  server that served it.
