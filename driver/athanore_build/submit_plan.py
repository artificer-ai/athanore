"""Submit tasks of the serial plan to the driver, in order.

    uv run python -m athanore_build.submit_plan --dry-run
    uv run python -m athanore_build.submit_plan --only T003
    uv run python -m athanore_build.submit_plan --from T003 --to T010

One run per task, submitted in plan order; capacity 1 makes execution
serial. T000 is skipped — it is this machinery.
"""

import argparse
import os
import re
import sys

import httpx

# `### T024a — title (ticket)`: the letter suffix keeps inserted tasks in
# their place.
HEADING = re.compile(r"^###\s+(T\d{3}[a-z]?)\s+—\s+(.*)$")

# Resolved against the checkout, not the cwd: the orchestrator runs
# this from `driver/`.
PLAN_DOC = "docs/v1/17-serial-task-plan.md"
PLAN = os.path.join(os.environ.get("WORKSPACE", "."), PLAN_DOC)
WORKFLOW = "v1_feature"


def parse_plan(path: str) -> list[tuple[str, str]]:
    tasks = []
    with open(path) as f:
        for line in f:
            m = HEADING.match(line.rstrip("\n"))
            if m and m.group(1) != "T000":
                tasks.append((m.group(1), m.group(2).strip()))
    return tasks


def select(tasks, *, only, start, end):
    if only:
        wanted = {t.strip() for t in only.split(",")}
        missing = wanted - {t for t, _ in tasks}
        if missing:
            sys.exit(f"unknown task(s): {', '.join(sorted(missing))}")
        return [(t, title) for t, title in tasks if t in wanted]
    ids = [t for t, _ in tasks]
    lo = ids.index(start) if start else 0
    hi = ids.index(end) + 1 if end else len(ids)
    if start and start not in ids:
        sys.exit(f"unknown task: {start}")
    if end and end not in ids:
        sys.exit(f"unknown task: {end}")
    return tasks[lo:hi]


def description(task_id: str, title: str, notes: str) -> str:
    """The run description is the implementer's specification. For a plan
    task it is a pointer: the plan section and the specs it cites are the
    real text, and they are in the checkout the agent is working in."""
    text = (
        f"{task_id} — {title}.\n\n"
        f"The task is specified in `{PLAN_DOC}`, under the heading "
        f"`### {task_id}`. That section's **Do**, **Tests** and **Done** "
        "blocks are the specification; read it and every `docs/v1/` section "
        "it cites before you write anything."
    )
    if notes.strip():
        text += f"\n\nOperator notes: {notes.strip()}"
    return text


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="submit_plan")
    p.add_argument("--plan", default=PLAN)
    p.add_argument("--url", default=os.environ.get("BUILDER_URL", "http://127.0.0.1:4102"))
    p.add_argument("--from", dest="start", help="first task id, inclusive")
    p.add_argument("--to", dest="end", help="last task id, inclusive")
    p.add_argument("--only", help="one id, or a comma-separated list")
    p.add_argument("--notes", default="", help="operator notes for every run")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    tasks = parse_plan(args.plan)
    if not tasks:
        sys.exit(f"no task headings found in {args.plan}")
    chosen = select(tasks, only=args.only, start=args.start, end=args.end)

    for task_id, title in chosen:
        if args.dry_run:
            print(f"{task_id}  {title}")
            continue
        r = httpx.post(
            f"{args.url}/api/workflows/{WORKFLOW}/runs",
            json={"title": task_id, "description": description(task_id, title, args.notes)},
            timeout=30,
        )
        if r.status_code >= 400:
            sys.exit(f"{task_id}: {r.status_code} {r.text}")
        print(f"{task_id}  {r.json().get('run_id', r.text)}  {title}")

    if args.dry_run:
        print(f"\n{len(chosen)} task(s) — nothing submitted (--dry-run)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
