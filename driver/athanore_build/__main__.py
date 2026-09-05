"""Run the driver server:  uv run python -m athanore_build [--web]

v0 hosting one workflow. Capacity 1 plus run-list order is the whole of
"serial": the plan is executed top to bottom with never two tasks in
flight.
"""

import argparse
import os

from athanore import AthanoreServer, Pool

from .feature import wf as v1_feature


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="python -m athanore_build")
    # 4102, not 4002: the v1 app under ./scripts/run.sh owns 4002.
    p.add_argument("--port", type=int, default=int(os.environ.get("BUILDER_PORT", "4102")))
    p.add_argument("--web", action="store_true", help="also serve the TUI in a browser")
    p.add_argument("--web-host", default="0.0.0.0")
    p.add_argument("--web-port", type=int, default=int(os.environ.get("BUILDER_WEB_PORT", "2424")))
    return p.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    # max_retries=1: no engine-level retry of a node. Every node here is
    # either deterministic (git, an exit code — a retry does the same
    # thing) or a paid agent turn, and the workflow's own loop-backs are
    # the retry policy. Retrying `review` three times on a task that has
    # already blown its cap just buys three more reviews.
    server = AthanoreServer(port=args.port, workers=1, max_retries=1)
    server.register(v1_feature, Pool("sandbox", capacity=1))
    server.run(web=args.web, web_host=args.web_host, web_port=args.web_port)
