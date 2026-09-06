"""The CI workflows mirror the gate.

`./scripts/test.sh` is the definition of green (D74); `.github/workflows/`
is that same set of checks on a runner. Nothing here runs CI — there is
no remote to run it on — but drift between the two is exactly the kind
of thing nobody notices until a release, so the correspondence is
asserted rather than remembered.
"""

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
    assert "uv sync --all-groups --all-extras" in ran
    assert "pytest -q --cov=athanore" in ran
    assert "ruff check ." in ran
    assert "ruff format --check ." in ran
    assert "pyright" in ran
    assert "lint-imports" in ran


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


def test_web_and_contract_work_is_probe_guarded(ci: Workflow) -> None:
    """Every step of these jobs runs only if the probe found its inputs.

    `web/` arrives with T007 and the generators with T008; until then the
    probe says no and the jobs pass having run nothing. The guard stays
    correct once they exist — the probe starts saying yes, and no YAML
    changes — so this asserts the shape, not today's tree.
    """
    for name in ("web", "contract"):
        job = ci["jobs"][name]
        probe, *rest = steps(job)[1:]
        assert probe["id"] == "probe"
        assert "GITHUB_OUTPUT" in probe["run"]
        for step in rest:
            assert step["if"] == "steps.probe.outputs.present == 'yes'"


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
