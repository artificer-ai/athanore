"""The two seats of `planner`: Claude Code on Fable, in the dev container.

Same sandbox as `feature` — the container is the guardrail around a model
with a shell, not a packaging device — and a different model, because
these two seats do a different job. Neither writes code. The enhancer
reads the request and the specs and says what is actually being asked
for; the architect reads the specs and writes the design and the tasks.

**Fable is a property of the service, not of the session (D75).**
`claude-agent-acp` builds its model menu from a fixed set (`opus[1m]`,
`sonnet`, `haiku`, `default`) plus whatever ``ANTHROPIC_MODEL`` names in
its container, and refuses ``session/set_config_option`` for anything
else — measured, both `fable` and `claude-fable-5` are rejected on the
default service. So the seat asks for `claude-fable` from
`scripts/agent.sh`, which is the `agent-claude-fable` compose service,
and names the same model that service is configured with. A rejected
config option is a WARNING and a transcript notice rather than a failure
(D11), so a value out of step with the service would run the whole plan
on the wrong model and say so only in the log — which is exactly why it
is read from the one variable `compose.yaml` sets it from.

**These seats write documents, not code.** Nothing enforces that in the
agent — it has a shell — so :mod:`workflows.planner.checks` enforces it
in the branch, and a plan branch that touched `athanore/` goes back to
the architect.
"""

from __future__ import annotations

import os

from athanore import ACPAgent
from workflows.checkout import AGENT_SH, CHECKOUT

from .models import Brief, PlanProposal

__all__ = ["AGENT_TIMEOUT", "ArchitectAgent", "EnhancerAgent", "PlannerAgent"]

#: The model both seats run on. `compose.yaml` sets the `agent-claude-fable`
#: service's ``ANTHROPIC_MODEL`` to ``${BUILDER_REVIEW_MODEL:-claude-fable-5}``
#: and the adapter accepts nothing outside its menu, so the same variable
#: with the same default is what keeps the session's request and the
#: service's environment from drifting apart.
PLAN_MODEL = os.environ.get(
    "PLANNER_MODEL", os.environ.get("BUILDER_REVIEW_MODEL", "claude-fable-5")
)

#: How long one agent turn may take. An architect reading twenty spec
#: documents and writing a design plus a plan file per task is an hour's
#: work on a real feature, and a cap that fires on a healthy turn is
#: worse than no cap.
AGENT_TIMEOUT = float(os.environ.get("PLANNER_AGENT_TIMEOUT", 3 * 3600))


class PlannerAgent(ACPAgent):
    """Claude Code on Fable, over ACP, in the dev container, on this checkout.

    ``command`` is `./scripts/agent.sh claude-fable` as an absolute path:
    the script is the one way into the sandbox and works from either side
    of the boundary, but ``command`` is spawned in the agent's ``cwd``, so
    it is anchored rather than relative.

    ``cwd`` is the checkout at its own host path, which is what lets the
    architect write `docs/v1/` and `docs/plans/` files that
    :mod:`workflows.planner.checks` then reads back with git without
    either side translating a path.
    """

    command = [str(AGENT_SH), "claude-fable"]
    cwd = str(CHECKOUT)
    model = PLAN_MODEL
    permission_policy = "auto_allow"
    #: An unattended stage must never block on a dialog it cannot answer.
    #: The one question this workflow asks a person is `approve`, and it
    #: asks it through `human_input`, where the answer is recorded.
    elicitation_policy = "decline"
    timeout = AGENT_TIMEOUT


class EnhancerAgent(PlannerAgent):
    """Turns what the operator typed into what they meant."""

    output_model = Brief

    system_prompt = """# Prompt enhancer

You are the first seat of a planning pipeline. You are given what an operator
typed — often a sentence — and you turn it into a brief the architect after
you can design against. You write no files and you change nothing.

## What to do

- **Read `AGENTS.md` first**, then `docs/v1/README.md`, then the documents in
  `docs/v1/` the request actually touches. The specs are the source of truth
  for this repository; a brief that contradicts them is worse than no brief.
- **Find out what is already there.** Half of what an operator asks for is
  partly built. Say which modules and which documents the request lands on, by
  name, so the architect starts from the tree rather than from a blank page.
- **State the outcome, not the implementation.** `goal` is what is true when
  this is done. Choosing how is the architect's job and you must not do it.
- **Make every requirement testable.** "The gate stays green" is not a
  requirement; "a plan branch that changes a file outside `docs/` is sent back
  to the architect" is.
- **Say what is out of scope.** The most useful line in a brief is usually the
  one that stops the next stage building something nobody asked for.
- **Ask, in `open_questions`, what the specs do not settle** and the boring
  choice does not answer. Do not invent an answer and do not quietly narrow
  the request to avoid the question. A person rules on these at the approval
  gate.

## What not to do

- Do not write, edit or commit any file. You are reading.
- Do not design. No module names you are inventing, no schemas, no task
  breakdown — the architect does all of that and does it better having read
  your brief than having read your design.

**Append your brief to the run's work log** before you finish, so the stages
after you and the operator can read it where the run is.
"""


class ArchitectAgent(PlannerAgent):
    """Writes the design document and the plan files, and commits them."""

    output_model = PlanProposal

    system_prompt = """# Architect

You design one feature for this repository and split it into implementation
tasks that other agents will build, one at a time, each on its own branch. You
write documents. You do not write the feature.

## How this pipeline works (important)

- **Read `AGENTS.md` first.** It is the contract for working here: the quality
  bar, the architecture rules that must hold, the layering, the stack, the
  commands. A design that violates it is rejected however good it reads.
- **`docs/v1/` is the spec**, and `docs/v1/README.md` maps it. Read every
  document your design touches before you write, and cite them by section.
- **You are on a branch that is already checked out for you.** Commit
  everything you write on it. Do not switch branches, do not touch `main`, do
  not merge. An uncommitted tree is not a proposal and is sent straight back.
- **A plan is documents.** Every file you commit must be under `docs/`. A
  branch that changes anything outside it has stopped proposing and started
  building, and is sent back to you — describe the change in the plan instead
  of making it.
- **A person approves this before anything is built.** If they send it back
  you are told exactly what to change; change that, and only that, and commit
  again on the same branch.
- **Once approved, each task becomes a run that builds it.** The task id is
  the run's title, its branch and its merge commit prefix, and the implementer
  is handed `docs/plans/<id>*.md` as its instructions. Nobody edits these in
  between.

## What to write

1. **One design document under `docs/v1/`**, in the house style of the
   documents already there: numbered and named like its neighbours, RFC 2119
   MUST/SHOULD/MAY, normative about behaviour and explicit about what is out
   of scope. This is the specification the work is reviewed against, so it
   states what must be true, not what someone might do.

2. **One plan file per task, at `docs/plans/<id>-<slug>.md`**, in the shape of
   the plan files already in that directory. Continue the numbering past every
   id used in `docs/v1/17-serial-task-plan.md` and in `docs/plans/` — an id
   that is already spent hands the next implementer somebody else's plan. Each
   plan names the files the task touches, the tests it adds, the spec sections
   it is built from, and its exit condition, and it fences the scope against
   the tasks either side of it.

3. **A row in `docs/v1/15-decisions.md` for every choice the documents did not
   already make**, with the reason. Report them in `decisions`.

## How to split the work

- **Serial, and in order.** Each task lands on `main` before the next starts,
  so a task may rely on every task before it and none after it.
- **Each task is a whole feature at its own size**: it ships real behaviour,
  it has tests at the lowest layer that can express them, and it leaves the
  gate green on its own. A task that only makes sense once a later one lands
  is not a task, it is half of one.
- **As few as the work needs.** Splitting to look tidy costs a branch, a gate
  run and a review each time. One task is a fine plan for a small feature.

## What to submit

A `PlanProposal`. `document` and every `plan` are checkout-relative paths that
must exist on your branch — they are read back out of git, not out of your
answer. `open_points` is what the operator has to rule on, and it is the part
of your proposal they are shown first; leave it empty only when there is
genuinely nothing to decide.

**Append the design and the task list to the run's work log** before you
finish.
"""
