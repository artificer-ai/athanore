#!/usr/bin/env bash
# Drive the v1 plan with athanore v0.
#
#   ./scripts/drive.sh up                    # start the orchestrator + TUI
#   ./scripts/drive.sh submit T003           # one task of the plan
#   ./scripts/drive.sh submit T003 "use the sqlite path, not the pg one"
#   ./scripts/drive.sh submit "sse replay cap" "see docs/v1/08-api.md"
#   ./scripts/drive.sh logs                  # follow it
#
# A `docs/plans/<title>*.md` is picked up automatically and named in the
# run description: write the plan first, then submit.
#   ./scripts/drive.sh down
#
# A run is one POST; several tasks are a shell loop, and capacity 1 keeps
# them serial:
#
#   for t in T003 T004 T005; do ./scripts/drive.sh submit $t; done
#
# v0 runs in its own container and its own venv — it is the same
# distribution name as v1 and the two must never meet in one environment
# (D67). It dispatches each task to `athanore/dev` over ACP, runs the
# gate in the same image, and shows progress in the v0 browser TUI.
source "$(dirname "$0")/_lib.sh"

in_container && die "drive from the host: the orchestrator spawns sibling containers"

cmd="${1:-up}"; shift || true

case "$cmd" in
  up)
    ensure_env
    # The sandbox image is what the agents actually run in.
    ensure_image
    compose --profile drive up -d --build orchestrator
    port="$(grep -m1 '^BUILDER_WEB_PORT=' "$ROOT/.env" 2>/dev/null | cut -d= -f2)"
    note "TUI: http://127.0.0.1:${port:-2424}   API: http://127.0.0.1:${BUILDER_PORT:-4102}"
    ;;
  down)  compose --profile drive down ;;
  logs)  compose_exec --profile drive logs -f orchestrator ;;
  submit)
    title="${1:-}"; shift || true
    [ -n "$title" ] || die "usage: $0 submit <task-id|title> [notes...]"
    # A plan task is a pointer: the plan section and the specs it cites
    # are the real text, and they are in the checkout the agent works in.
    # Anything else is a free-form feature, described by the notes.
    body="$(TITLE="$title" NOTES="$*" ROOT="$ROOT" python3 -c '
import glob, json, os, re
title, notes = os.environ["TITLE"], os.environ["NOTES"].strip()
root = os.environ["ROOT"]
parts = []
if re.fullmatch(r"T\d{3}[a-z]?", title):
    parts.append(
        f"{title} is specified in `docs/v1/17-serial-task-plan.md`, under the "
        f"heading `### {title}`. That section\u2019s **Do**, **Tests** and "
        "**Done** blocks are the specification; read it and every `docs/v1/` "
        "section it cites before you write anything."
    )
plans = sorted(
    os.path.relpath(p, root)
    for p in glob.glob(os.path.join(root, "docs", "plans", title + "*.md"))
)
if plans:
    parts.append(
        "The implementation plan is "
        + ", ".join(f"`{p}`" for p in plans)
        + ". Follow it: it fences the scope against the tasks either side and "
        "says what done means."
    )
if notes:
    parts.append(f"Operator notes: {notes}")
print(json.dumps({"title": title, "description": "\n\n".join(parts) or title}))')"
    curl -fsS -X POST \
      "http://127.0.0.1:${BUILDER_PORT:-4102}/api/workflows/v1_feature/runs" \
      -H 'content-type: application/json' -d "$body"
    echo
    ;;
  *) die "usage: $0 <up|down|logs|submit> [args...]" ;;
esac
