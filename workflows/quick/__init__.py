"""`quick` — a small change to this repository, from a description to `main`.

    prepare ─▶ implement ─▶ gate ─▶ publish ─▶ merge
                  ▲          │         │
                  └──────────┴─────────┘

The `feature` pipeline spends five model seats on a change — a rewrite,
an architect, an implementer, a reviewer and a QA engineer — because a
feature is worth judging three times before it reaches `main`. A LICENSE
file, a badge, a typo in a docstring, a one-line config change is not,
and running it through the full pipeline is an hour of wall clock and a
fair amount of money to reach the same merge commit. This is the short
form: one implementer on the cheap model, the gate, then the push, the
pull request, CI, the merge. No plan is written, nothing reviews the
diff, nobody exercises the result, and nothing asks the operator; the
gate and CI are the whole verdict, and nothing is pushed until the
gate has passed (D269).

That is the trade, and it is the operator's to make at submission time:
`athanore submit quick "..."` says "this does not need judging". A
change that turns out to need it — a red gate three times over — stops
with its worktree and branch intact, like `feature`, and the way on is
to resubmit it as one.

Everything deterministic is :mod:`workflows.shared.steps`, shared with
`feature`: the same worktree (D263), the same gate, the same publish and
merge (D260, D261). The only thing of its own here is the implementer:
the same seat in the same sandbox, on a cheaper model, with a shorter
brief.

Run it::

    python -m workflows                 # the host, on 127.0.0.1:4002
    athanore submit quick "MIT license" "Add LICENSE with ..."
"""

from __future__ import annotations

import os

from athanore import Workflow
from workflows.shared import steps
from workflows.shared.agents import SandboxAgent
from workflows.shared.models import TaskReport
from workflows.shared.sandbox import GATE_COMMAND

__all__ = ["IMPLEMENT_MODEL", "wf"]

#: The model the one seat runs on. Sonnet: the change was declared small
#: at submission, and the gate is what decides whether it was.
IMPLEMENT_MODEL = os.environ.get("QUICK_IMPLEMENT_MODEL", "sonnet")


class QuickImplementer(SandboxAgent):
    """An implementer briefed for a change nobody reviews.

    The same report as `feature`'s, the same rules about committing on
    the branch and not running the gate itself; what is gone is the
    account of the stages that do not exist here, replaced by the one
    thing that changes when nothing reviews the diff — keep it small.
    """

    model = IMPLEMENT_MODEL
    output_model = TaskReport

    system_prompt = f"""# Implementer

You implement one small change in the checkout at your working directory,
on a branch that is already checked out for you.

The description you are given is the whole specification. If it points at
a document in `docs/`, read that before you write a line.

## How this pipeline works (important)

- **Read `AGENTS.md` first.** It is the contract for working in this
  repository: the quality bar, the architecture rules, the layering, the
  commands. Nothing reviews your diff before it reaches `main`, so the
  contract is yours to keep.
- **Keep it to what was asked.** This pipeline exists for changes small
  enough not to need a plan or a review. If the change you are asked for
  turns out to need either — it touches the engine, the store, the wire
  contract, or more than a handful of files — stop, say so in the work
  log, and submit a report saying it should be a `feature` run instead.
  Do not build a large change without a review because you were asked
  quickly.
- **Commit your work on the branch you are on.** Everything the change
  needs must be committed: an uncommitted tree is rejected before the
  gate even runs. Do not switch branches, do not touch `main`, do not
  merge, and do not tag — the stage after you does that.
- **The gate decides whether you passed, not you.** After you finish,
  `{GATE_COMMAND}` runs, then CI runs it again on the pull request. If
  either is red you will be given its output and asked to fix it.
- **Do not run the whole gate yourself.** It takes many minutes and the
  node after you runs it once, for real. Run the narrow checks over what
  you changed:

      uv run pytest tests/<the ones you touched> -q
      uv run ruff check <paths> && uv run ruff format --check <paths>
      uv run pyright <paths>
      pnpm -C web typecheck && pnpm -C web test    # only if you changed web/

- **Append what you did to the run's work log**, so a later attempt of
  yours can read it.

## What to submit

Submit a `TaskReport`. `headline` becomes the subject line of the merge
commit, so write it as one: imperative mood, no trailing period.
`how_to_exercise` is a command, an endpoint or a page — not a description.
"""


wf = Workflow("quick")


@wf.node(start=True, retries=0, timeout=600)
async def prepare(implement, *, payload):
    """Branch and worktree from `origin/main`; see `feature.prepare`."""

    return implement(await steps.prepare(payload))


@wf.node(retries=1, timeout=None)
async def implement(gate, *, payload):
    """The one seat, on the cheap model, in the worktree."""

    return gate(await steps.implement(payload, QuickImplementer))


@wf.node(retries=0, timeout=None)
async def gate(publish, implement, *, payload):
    """git, then the gate in the worktree — the first half of the verdict."""

    passed, out = await steps.gate(payload)
    return publish(out) if passed else implement(out)


@wf.node(retries=0, timeout=None)
async def publish(merge, implement, *, payload):
    """Push, open the pull request, wait for CI — the second half."""

    passed, out = await steps.publish(payload)
    return merge(out) if passed else implement(out)


@wf.node(retries=0, timeout=900)
async def merge(*, payload):
    """Merge the pull request; the worktree and the branch are gone."""

    return await steps.merge(payload)
