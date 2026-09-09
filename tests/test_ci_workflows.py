"""The CI workflows mirror the gate.

`./scripts/test.sh` is the definition of green (D74); `.github/workflows/`
is that same set of checks on a runner. Nothing here runs CI — there is
no remote to run it on — but drift between the two is exactly the kind
of thing nobody notices until a release, so the correspondence is
asserted rather than remembered.
"""

import json
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

# YAML 1.1 reads a bare `on:` as the boolean True, so a workflow's keys
# are not all strings.
Workflow = dict[Any, Any]

ROOT = Path(__file__).resolve().parent.parent
CI = ROOT / ".github" / "workflows" / "ci.yml"
NIGHTLY = ROOT / ".github" / "workflows" / "nightly.yml"

#: The Playwright the dev image bakes a chromium of (`docker/dev/Dockerfile`)
#: and the one `web/package.json` pins, which must be the same one (T068a).
PLAYWRIGHT_VERSION = "1.63.0"


def load(path: Path) -> Workflow:
    return yaml.safe_load(path.read_text())


def steps(job: Workflow) -> list[dict[str, Any]]:
    return job["steps"]


def commands(job: Workflow) -> str:
    """Every shell command the job runs, as one blob to search."""
    return "\n".join(step["run"] for step in steps(job) if "run" in step)


@pytest.fixture(scope="module")
def ci() -> Workflow:
    return load(CI)


@pytest.fixture(scope="module")
def nightly() -> Workflow:
    return load(NIGHTLY)


def test_workflows_parse(ci: Workflow, nightly: Workflow) -> None:
    assert ci["name"] == "CI"
    assert nightly["name"] == "nightly"
    # Either spelling of the trigger block will do; a workflow with
    # neither never runs.
    for workflow in (ci, nightly):
        assert workflow.get("on", workflow.get(True))


def test_ci_jobs_are_python_web_and_contract(ci: Workflow) -> None:
    assert list(ci["jobs"]) == ["python", "web", "contract"]


def test_python_matrix_covers_the_supported_floor(ci: Workflow) -> None:
    """3.11 is tested, not just declared in `requires-python` (D66)."""
    matrix = ci["jobs"]["python"]["strategy"]["matrix"]["python-version"]
    assert matrix == ["3.11", "3.12", "3.13"]

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    floor = pyproject["project"]["requires-python"].lstrip(">=")
    assert floor == min(matrix, key=lambda v: tuple(map(int, v.split("."))))


def test_python_job_runs_every_step_of_the_gate(ci: Workflow) -> None:
    ran = commands(ci["jobs"]["python"])
    assert "uv sync --all-packages --all-groups --all-extras" in ran
    assert "pytest -q --cov=athanore" in ran
    assert "ruff check ." in ran
    assert "ruff format --check ." in ran
    assert "pyright" in ran
    assert "lint-imports" in ran


#: 13 §CI's coverage thresholds: three packages at 95 %, the whole of
#: `athanore` at 85 %. One gate each, so a red build names the package
#: that slipped (D149). `None` is the overall gate, which takes no
#: `--include`.
COVERAGE_GATES = {
    "graph": ("athanore/graph/*", 95),
    "engine": ("athanore/engine/*", 95),
    "requests": ("athanore/requests/*", 95),
    "overall": (None, 85),
}


def test_python_job_gates_the_coverage_13_asks_for(ci: Workflow) -> None:
    """Every threshold of 13 §CI is a step, and none of them is missing.

    Each gate reads the data file the `pytest` step wrote, so the suite
    runs once and the threshold is applied to what all of it covered —
    which is why it is `coverage report --fail-under` rather than a
    second, narrower pytest run (D112).
    """
    ran = commands(ci["jobs"]["python"])
    for name, (include, threshold) in COVERAGE_GATES.items():
        expected = "uv run --no-sync coverage report"
        if include is not None:
            expected += f" --include='{include}'"
        expected += f" --fail-under={threshold}"
        # The YAML folds `>` blocks onto one line, so the command a
        # runner executes is what is compared, not how it was written.
        assert expected in " ".join(ran.split()), name


def test_every_coverage_gate_runs_after_the_suite_it_reads(ci: Workflow) -> None:
    """Measured before it is gated: the report has nothing to read otherwise."""
    steps_run = [step.get("name") for step in steps(ci["jobs"]["python"])]
    for name in COVERAGE_GATES:
        assert steps_run.index("pytest") < steps_run.index(f"coverage gate ({name})")


def test_the_coverage_gates_measure_paths_that_exist(ci: Workflow) -> None:
    """A threshold on a glob that matches nothing passes at 100 %."""
    for include, _ in COVERAGE_GATES.values():
        if include is None:
            continue
        package = ROOT / include.removesuffix("/*")
        assert package.is_dir(), include
        assert list(package.glob("*.py")), include


def test_the_once_only_steps_run_once(ci: Workflow) -> None:
    """ruff, pyright and lint-imports are interpreter-independent."""
    once = {"ruff", "pyright", "lint-imports"}
    for step in steps(ci["jobs"]["python"]):
        if step.get("name") in once:
            assert step["if"] == "matrix.python-version == '3.13'", step["name"]
        elif "run" in step:
            assert "if" not in step, step.get("name")


def test_web_job_runs_the_pnpm_half_of_the_gate(ci: Workflow) -> None:
    ran = commands(ci["jobs"]["web"])
    for command in ("install --frozen-lockfile", "typecheck", "lint", "test", "build"):
        assert f"pnpm -C web {command}" in ran


#: The Playwright command both the gate and the `web` job run (T068a).
PLAYWRIGHT = "pnpm -C web exec playwright test"


def test_web_job_runs_the_playwright_suite_on_chromium_only(ci: Workflow) -> None:
    """T068a: "CI `web` job runs Playwright (Chromium only)".

    The suite drives a real `athanore serve`, so the job needs the
    Python environment as well as the node one — and it needs a browser,
    which is installed for `chromium` and for nothing else.
    """
    job = ci["jobs"]["web"]
    ran = commands(job)
    assert "uv sync --all-packages --all-groups --all-extras" in ran
    assert "playwright install --with-deps chromium" in ran
    assert PLAYWRIGHT in ran
    assert any(
        step.get("uses", "").startswith("astral-sh/setup-uv") for step in steps(job)
    )

    # After the build, because the suite drives what the build produced.
    named = [step.get("name") for step in steps(job)]
    assert named.index("pnpm build") < named.index("pnpm e2e")


def test_the_gate_runs_the_playwright_suite_too(ci: Workflow) -> None:
    """`./scripts/test.sh` is the definition of green (D74).

    A check only the runner performs is a check that first goes red on
    somebody else's branch, and this repository has no runner to perform
    it: the E2E suite would never run at all. So the gate runs it, and
    the `web` job is that same command (D178).
    """
    gate = (ROOT / "scripts" / "test.sh").read_text()
    assert PLAYWRIGHT in gate
    assert PLAYWRIGHT in commands(ci["jobs"]["web"])


def test_the_playwright_suite_and_its_browser_are_one_version() -> None:
    """The revision the image ships and the one npm resolves are one.

    `docker/dev/Dockerfile` bakes `playwright@$PLAYWRIGHT_VERSION`'s
    chromium into `PLAYWRIGHT_BROWSERS_PATH` (D68); a `@playwright/test`
    on a different minor would ask for a revision that is not there and
    the gate would try to download one mid-run. Pinned exactly, not
    ranged, for that reason.
    """
    package = json.loads((ROOT / "web" / "package.json").read_text())
    pinned = package["devDependencies"]["@playwright/test"]
    assert pinned == PLAYWRIGHT_VERSION, pinned

    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    args = compose["services"]["dev"]["build"]["args"]
    assert (
        f"${{PLAYWRIGHT_VERSION:-{PLAYWRIGHT_VERSION}}}" == args["PLAYWRIGHT_VERSION"]
    )
    # The image ships the browser by default: the driver's `qa` node and
    # this suite both need it (D68).
    assert args["WITH_BROWSERS"] == "${WITH_BROWSERS:-1}"


def test_the_playwright_config_is_chromium_only() -> None:
    """One engine, in the image and on the runner (T068a)."""
    config = (ROOT / "web" / "playwright.config.ts").read_text()
    assert "testDir: './e2e'" in config
    projects = config[config.index("projects:") :]
    assert projects.count("name:") == 1
    assert "'chromium'" in projects


#: The SPA's coverage gate: 80 % of `web/src`, on all four metrics
#: (`docs/v1/17-serial-task-plan.md` § T068, D177).
WEB_COVERAGE_THRESHOLD = 80
WEB_COVERAGE_METRICS = ("statements", "branches", "functions", "lines")


def test_web_job_gates_the_spa_coverage_t068_asks_for() -> None:
    """The threshold is in the config `pnpm -C web test` reads (D177).

    Not a step of its own: `./scripts/test.sh` runs `pnpm -C web test`
    too, so configuring it is what makes the gate and this job apply the
    same one. That is why this asserts the config and the script rather
    than a line of YAML.
    """
    package = json.loads((ROOT / "web" / "package.json").read_text())
    assert "--coverage" in package["scripts"]["test"]

    config = (ROOT / "web" / "vite.config.ts").read_text()
    for metric in WEB_COVERAGE_METRICS:
        assert f"{metric}: {WEB_COVERAGE_THRESHOLD}," in config, metric

    assert "@vitest/coverage-v8" in package["devDependencies"]


def test_web_work_is_probe_guarded(ci: Workflow) -> None:
    """Every step of the `web` job runs only if the probe found `web/`.

    The guard is from T006, when `web/` did not exist and the job had to
    pass having run nothing. It stays correct now that it does — the
    probe says yes, and no YAML changed — so this asserts the shape, not
    today's tree.
    """
    job = ci["jobs"]["web"]
    probe, *rest = steps(job)[1:]
    assert probe["id"] == "probe"
    assert "GITHUB_OUTPUT" in probe["run"]
    # The guard opens every condition. A step may add to it — the
    # Playwright report is uploaded on failure and not otherwise — but
    # none may run without it, which is the invariant.
    for step in rest:
        assert step["if"].startswith("steps.probe.outputs.present == 'yes'"), step


def test_contract_work_is_not_conditional(ci: Workflow) -> None:
    """The contract job runs unconditionally, every time (T008).

    Its inputs — `scripts/dump_openapi.py` and `web/` — are both in the
    tree for good, and a freshness check that can decide not to run is
    not a freshness check.
    """
    for step in steps(ci["jobs"]["contract"]):
        assert "if" not in step, step.get("name", step.get("uses"))


def test_node_and_pnpm_match_the_dev_image(ci: Workflow) -> None:
    """The runner and `docker/dev/Dockerfile` are one toolchain."""
    dockerfile = (ROOT / "docker" / "dev" / "Dockerfile").read_text()
    assert "FROM node:22-bookworm-slim" in dockerfile
    assert "ARG PNPM_VERSION=10" in dockerfile

    for name in ("web", "contract"):
        job = ci["jobs"][name]
        node = next(
            step
            for step in steps(job)
            if step.get("uses", "").startswith("actions/setup-node")
        )
        assert node["with"]["node-version"] == 22
        assert "pnpm@10" in commands(job)


def test_contract_job_checks_the_generated_client_is_fresh(ci: Workflow) -> None:
    ran = commands(ci["jobs"]["contract"])
    assert "scripts/dump_openapi.py" in ran
    assert "pnpm -C web gen" in ran
    assert "git diff --exit-code tests/snapshots web/src/api/gen" in ran


def test_the_contract_jobs_generators_exist() -> None:
    """What the job regenerates, and what it then diffs (T008)."""
    assert (ROOT / "scripts" / "dump_openapi.py").is_file()
    assert (ROOT / "web" / "openapi-ts.config.ts").is_file()
    assert "gen" in json.loads((ROOT / "web" / "package.json").read_text())["scripts"]
    assert (ROOT / "tests" / "snapshots" / "openapi.json").is_file()
    assert (ROOT / "web" / "src" / "api" / "gen" / "index.ts").is_file()


def test_nightly_selects_the_postgres_marker(nightly: Workflow) -> None:
    job = nightly["jobs"]["postgres"]
    assert "pytest -m postgres" in commands(job)
    assert "asyncpg" in job["env"]["ATHANORE_TEST_PG_URL"]


def test_nightly_runs_the_same_postgres_as_the_dev_stack(
    nightly: Workflow,
) -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    service = nightly["jobs"]["postgres"]["services"]["postgres"]
    assert service["image"] == compose["services"]["postgres"]["image"]
    assert (
        service["env"]["POSTGRES_PASSWORD"]
        == (compose["services"]["postgres"]["environment"]["POSTGRES_PASSWORD"])
    )


def test_the_postgres_marker_is_registered(pytestconfig: pytest.Config) -> None:
    """An unregistered marker is a warning today and an error under -W error."""
    registered = [m.split(":", 1)[0] for m in pytestconfig.getini("markers")]
    assert "postgres" in registered
