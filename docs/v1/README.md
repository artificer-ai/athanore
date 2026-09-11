# Athanore v1 — design documents

Athanore runs code-defined AI agent workflows over the
[Agent Client Protocol](https://agentclientprotocol.com). A workflow is a
Python graph (decorated functions as nodes, edges inferred from parameter
names); a server executes runs of that graph, dispatching agents over ACP;
an operator watches and steers from a browser SPA or a small CLI.

This directory is the ground-up redesign of the MVP, which lives in the
neighbouring v0 checkout and not here (D65). The MVP (its `athanore/`
package, `workflow/`, `tests/`, `DESIGN.md`, and the notes under
`docs/design/`) proved every feature the product needs. v1 keeps every one
of those features and their hard-won decisions, and gives them a clean
architecture: a small core, a real web frontend, a plugin system so
workflows ship their own UI, and a local-first trust model that stays
simple on one machine and becomes explicit only when you bind to a
network.

## Provenance

These documents were written in, and copied from, the **athanore MVP
repository** (`~/Projects/athanore`, the v0 code at version 0.0.11,
commit `2244f91`, 2026-09-05). That repository is the behavioural
specification v1 re-implements: wherever a document or the task plan
says "the MVP", "port", or `$MVP_CHECKOUT`, it means that checkout, now
tagged `v0.0.12` and driving this build from the orchestrator's own
environment (D67). Its `docs/v1/` was the original of this directory;
**this copy is the working one** — the two have diverged since
development started here, and the MVP's copy is history.

## How to read

Start at 01, read in order the first time. Each document is self-contained
afterwards; cross-references use the document number.

| # | Document | What it settles |
|---|----------|-----------------|
| 01 | [Vision, principles, and the MVP feature inventory](01-vision-and-scope.md) | What Athanore is, the three rules, what v1 must preserve, non-goals |
| 02 | [System architecture](02-architecture.md) | Processes, packages, layering, library choices, request/data flows |
| 03 | [Domain model](03-domain-model.md) | Entities, identifiers, state machines, invariants |
| 04 | [Engine: graph, scheduling, execution](04-engine.md) | DSL, dispatch order, pools, retries, recovery, waiting, cancellation |
| 05 | [Agents and the ACP façade](05-agents.md) | Agent classes, ACP client, permissions/elicitation/ask, submissions, stats |
| 06 | [Requests: the human-in-the-loop channel](06-requests.md) | One object for permissions, elicitations, node questions; answers; durability |
| 07 | [Storage](07-storage.md) | Schema, migrations, transcripts, retention, the v0 → v1 data migration |
| 08 | [HTTP API and event stream](08-api.md) | Every endpoint, auth, error shape, SSE, OpenAPI, versioning |
| 09 | [Plugin system](09-plugins.md) | Routes, actions, panels, events, assets; manifest; builtins as plugins |
| 10 | [Frontend SPA](10-frontend.md) | Stack, screens, state, realtime, plugin renderers, design system |
| 11 | [CLI](11-cli.md) | `athanore serve`, submit/inspect/steer verbs, config |
| 12 | [Security](12-security.md) | Threat model, trust boundaries, tokens, plugin and agent isolation, review of the MVP |
| 13 | [Testing and quality](13-testing.md) | Test pyramid, fakes, contract tests, CI |
| 14 | [Migration and delivery plan](14-migration-and-phasing.md) | From the MVP to v1 in phases; what is deleted; compatibility |
| 15 | [Decision log](15-decisions.md) | Every decision, carried-forward or new, with its reason |
| 16 | [Implementation tickets](16-implementation-tickets.md) | The delivery plan in 14 broken into epics and tickets, each pointing at the section that specifies it |
| 17 | [Serial task plan](17-serial-task-plan.md) | The tickets in 16 flattened into one ordered sequence of day-sized tasks with files, tests, and exit criteria |
| 18 | [Event payloads](18-event-payloads.md) | The `data` object of every event name; the typed union the SPA and plugins consume |
| 19 | [Agent prompt text](19-agent-prompts.md) | The verbatim kickoff, ask, submission, and repair blocks agents receive |
| 20 | [Carried findings](20-carried-findings.md) | The MVP's ACP findings and permission decisions the other documents cite, folded in so the set is self-contained |
| 21 | [Design refresh: re-import, narrow viewports, type scale](21-design-refresh.md) | The first post-1.0 phase: the refreshed design import and its diff discipline, the narrow-viewport layout and touch operation, the font-size chooser and the base-relative type ramp |
| 22 | [Live registration](22-live-registration.md) | The second post-1.0 phase: workflows added, replaced and removed on a serving process — the server verbs, what happens to runs in flight, module reloading, the three routes, verbs and events, and how the SPA follows |
| — | [design/](design/README.md) | The imported Claude Design mock and Nocturne tokens |
| — | [../plans/](../plans/) | One implementation plan per task of 17: the fenced scope, the file-by-file steps, and the verification a reviewer and QA ask for. Written before the task is built and read by whoever builds it |

## Status

**Being built, from these documents.** [17](17-serial-task-plan.md) is
executed in order, one task per commit and one merge commit per task, and
every task that has landed carries a `**Status.** Done.` line saying what
it landed and where it departed from the plan — so the plan, not this
paragraph, is where the build's position is read. Phases 0 to 5 of
[14](14-migration-and-phasing.md) are delivered (the store, the engine,
requests, agents, the API and its plugin host, the CLI, and the SPA);
phase 6 is the examples, the live smoke scripts, this pass over the
documents, and the 1.0.0 release.

The documents are kept in step with what shipped rather than left as the
design that preceded it: the architectural review of 2026-09-05 is D38–D51
in [15-decisions.md](15-decisions.md), a gap review the same day added
D52–D61 and documents 18–20, every choice made while building is a row
after those, and the phase checkpoints (T029, T041, T056, T069) are where
04, 05, 06, 10 and 13 were brought back in line with the code.

The Claude Design project (`Athanore.dc.html`, "Nocturne" design system)
is imported under [design/](design/README.md) and is the normative
source for [10-frontend.md](10-frontend.md). Tickets are in
[16-implementation-tickets.md](16-implementation-tickets.md); the serial
execution order is [17-serial-task-plan.md](17-serial-task-plan.md).

## Conventions used in these documents

- **MUST / SHOULD / MAY** carry their RFC 2119 meanings.
- "**MVP**" (also "v0") means the code in the neighbouring `athanore`
  checkout, tagged `v0.0.12`, and never code in this repository (D65).
- "**Operator**" is the human running Athanore. "**Agent**" is an ACP
  subprocess. "**Node body**" is the Python function a node runs.
- A "**seam**" is an existing extension point. New capability attaches to a
  seam before it gets a new concept (DESIGN.md's guardrail, kept).
