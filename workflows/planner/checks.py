"""Everything about a proposal that git answers, not the architect.

`feature` has a gate: an exit code decides whether a branch is worth a
reviewer's time. A plan branch has no gate — it changes documents, and
`./scripts/test.sh` has nothing to say about a document — so this module
is the equivalent, and it checks the two things a plan can be wrong about
in a way that only shows up much later:

1. **The branch wrote what the proposal says it wrote.** The design
   document and every plan file are read out of `git diff --name-only`,
   not out of the architect's answer. An architect that described files
   it did not write would otherwise pass the human gate — a person
   reading a proposal cannot see an absent file — and fail at the far end
   as an implementer with no plan to follow.
2. **The task ids are free.** ``PlannedTask.id`` becomes the title of a
   `feature` run, which makes it the branch name, the merge subject
   prefix, and the glob :func:`workflows.checkout.plan_docs` resolves. An
   id some earlier task already used hands the next implementer that
   task's plan, silently, and the first sign of it is a branch built to
   the wrong specification.

It also holds the plan branch to its own scope: **a plan is documents**.
A branch that edited `athanore/` has stopped proposing and started
building, and the whole point of the approval gate is that nobody builds
until a person has said yes.

Every failure comes back as a sentence the architect can act on, because
that is what the loop-back carries. Nothing here raises for a problem the
architect could fix; rule 3 is for the checkout being in a state no node
can route around.
"""

from __future__ import annotations

import re

from workflows.checkout import changed_paths, git, git_try

from .models import PlanProposal

__all__ = ["TASK_ID", "verify"]

#: A task id, as `docs/v1/17-serial-task-plan.md` writes them: `T003`,
#: `T013a`, `T014b`. Anchored, because `plan_docs` globs on the prefix and
#: an id with a trailing space would match a different task's file.
TASK_ID = re.compile(r"^T\d{3,}[a-z]?$")

#: Where a plan file and a design document must live. Both are fixed by
#: AGENTS.md — `docs/v1/` is the spec and `docs/plans/<task-id>*.md` is
#: what `feature` reads to the implementer — so neither is the
#: architect's to choose.
PLANS = "docs/plans/"
SPEC = "docs/v1/"
DOCS = "docs/"

#: The serial task plan, read at the merge base to find the ids already
#: spent. Post-1.0 work is not added to it (it is the v1 build order and
#: it is finished), but every id it ever used is still taken: a merge
#: commit prefixed `T012:` a second time makes `git log --grep` lie.
TASK_PLAN = "docs/v1/17-serial-task-plan.md"


async def verify(proposal: PlanProposal, *, branch: str, base: str) -> str:
    """The problems with ``proposal``, as one message, or ``""``.

    Returns rather than raises: a proposal that does not check out is a
    loop-back to the architect carrying what to fix, and the caller is
    the node that owns that routing (rule 2).
    """

    problems: list[str] = []
    touched = await changed_paths(base)
    added = set(await changed_paths(base, added_only=True))
    spent = await _ids_already_spent(base)

    if not touched:
        return (
            f"You committed nothing to `{branch}`. The design document and "
            "the plan files have to be committed on the branch; an "
            "uncommitted tree is not a proposal."
        )

    outside = [path for path in touched if not path.startswith(DOCS)]
    if outside:
        problems.append(
            "A plan is documents. This branch changed files outside `docs/`, "
            "which is building rather than proposing — revert them and "
            "describe the change in the plan instead:\n"
            + "\n".join(f"- {path}" for path in outside)
        )

    problems.extend(_document_problems(proposal, touched))
    problems.extend(_task_problems(proposal, added, spent))

    if not problems:
        return ""
    return "\n\n".join(problems)


def _document_problems(proposal: PlanProposal, touched: list[str]) -> list[str]:
    """Whether the design document is where it says it is, and is new work."""

    document = proposal.document.strip()
    if not document.startswith(SPEC):
        return [
            f"`document` is {document!r}. The design document belongs under "
            f"`{SPEC}`, which is the spec this repository builds against."
        ]
    if document not in touched:
        return [
            f"`document` names {document!r}, and this branch did not change "
            "that file. Write the design document, commit it, and name what "
            "you wrote."
        ]
    return []


def _task_problems(
    proposal: PlanProposal, added: set[str], spent: set[str]
) -> list[str]:
    """Whether every task has a free id and a plan file this branch wrote."""

    if not proposal.tasks:
        return [
            "`tasks` is empty. A design that cannot be split into at least "
            "one implementation task is not a plan anyone can build from."
        ]

    problems: list[str] = []
    seen: set[str] = set()
    for task in proposal.tasks:
        task_id = task.id.strip()
        plan = task.plan.strip()
        where = f"task {task_id or task.title!r}"

        if not TASK_ID.match(task_id):
            problems.append(
                f"{where}: {task_id!r} is not a task id. They are `T` and at "
                "least three digits, optionally one lowercase letter — "
                "`T080`, `T081a`."
            )
            continue
        if task_id in seen:
            problems.append(
                f"{where}: two tasks share the id {task_id}. Each one becomes "
                "its own run and its own branch, so each needs its own id."
            )
            continue
        seen.add(task_id)

        if taken := sorted(one for one in spent if one.startswith(task_id)):
            problems.append(
                f"{where}: the id {task_id} is already taken by earlier work "
                f"({', '.join(taken)}). "
                "Continue the numbering past every id in "
                f"`{TASK_PLAN}` and `{PLANS}` rather than reusing one."
            )
        if not plan.startswith(PLANS):
            problems.append(
                f"{where}: `plan` is {plan!r}. A plan file lives at "
                f"`{PLANS}{task_id}-<slug>.md` — that is the glob the "
                "implementer's run resolves it by."
            )
        elif not _names_task(plan, task_id):
            problems.append(
                f"{where}: `plan` is {plan!r}, which does not begin with "
                f"`{PLANS}{task_id}`. The run for {task_id} finds its plan by "
                "that prefix and would find nothing."
            )
        elif plan not in added:
            problems.append(
                f"{where}: this branch did not add {plan!r}. Write the plan "
                "file and commit it; a plan that already existed belongs to "
                "another task."
            )
        if not task.description.strip():
            problems.append(
                f"{where}: `description` is empty. It is the whole brief the "
                "implementer is given, so it has to say what to build and "
                "what done means."
            )
    return problems


def _names_task(plan: str, task_id: str) -> bool:
    """Whether ``plan`` is what `plan_docs(task_id)` would find.

    The same prefix match the glob makes, so a file this accepts is a
    file the implementer's run resolves.
    """

    return plan[len(PLANS) :].startswith(task_id)


async def _ids_already_spent(base: str) -> set[str]:
    """Every task id in use at ``base``: the plan files, and the task plan.

    Read at the merge base rather than from the working tree, so the
    files this branch is proposing are not counted as collisions with
    themselves.
    """

    spent: set[str] = set()

    listing = await git("ls-tree", "-r", "--name-only", base, "--", PLANS)
    for path in listing.splitlines():
        found = re.match(r"T\d{3,}[a-z]?", path[len(PLANS) :])
        if found:
            spent.add(found.group(0))

    code, plan = await git_try("show", f"{base}:{TASK_PLAN}")
    if code == 0:
        spent.update(re.findall(r"^### (T\d{3,}[a-z]?)\b", plan, flags=re.MULTILINE))
    return spent
