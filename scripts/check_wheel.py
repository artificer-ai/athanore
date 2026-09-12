#!/usr/bin/env python
"""Build the wheel and prove it serves the SPA from a clean install.

The Phase 4 checkpoint (`docs/v1/17-serial-task-plan.md` § T069). One
integration nothing else in the gate covers: `pnpm -C web build` writes
`athanore/web/dist`, hatch ships that directory as package data
(`pyproject.toml` `[tool.hatch.build] artifacts`, 14 §Repository
changes), and `athanore.api.static` serves it at `/`. Every one of those
three is exercised on its own — the vitest suite, the wheel's config,
the Playwright suite against a source checkout — and none of them
notices a wheel that builds and then serves the "the interface is not
built" page.

What this script does, in order:

1. **Refuses to build a wheel over an SPA that is not there.** The order
   T069 asks for is `pnpm build` *before* `uv build`, so that the wheel
   carries a fresh SPA rather than whatever was last built locally.
   Written as two steps in a workflow file, that order is a convention;
   enforced here, it is a check — a wheel built first fails at the first
   line instead of shipping.
2. **Builds the distribution**, `uv build`: the sdist and then the wheel
   *from* the sdist, which is the path where a git-ignored artifact can
   silently be dropped.
3. **Reads the wheel.** `index.html` is in it, under
   `athanore/web/dist/`, and so is every `/assets/…` file that document
   references. A build that shipped an index without its bundle is a
   white page with a 404 in the console. The license file is in it too,
   byte for byte the checkout's `LICENSE`: hatchling ships it by default
   (PEP 639), and a default is a thing that can change under a version
   bump.
4. **Installs it into a clean venv and serves it.** `python -m venv`,
   then `pip install <the wheel>` — a real install of a real wheel, with
   no source checkout on `sys.path`: the server runs from a temporary
   directory, and every `ATHANORE_*` variable this environment carries is
   dropped, so what answers is a stock installation and not this
   machine's. The clean-venv step is the one that catches a wheel that
   builds but does not serve.
5. **Asks it for the page.** `/` is the built document (the one in the
   wheel, byte for byte), one of its assets is served, and `/api/health`
   reports the version that was just built.

POSIX only: it looks for `bin/` in the venv it makes. The dev image and
the runner are both Linux, and this is a check on the packaging of a
server, not a portable installer.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Final

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
DIST: Final[Path] = ROOT / "dist"

#: The package data the wheel must carry, as a posix prefix inside it.
PACKAGE_DATA: Final[str] = "athanore/web/dist"
#: The document `athanore.api.static` falls back to.
INDEX: Final[str] = f"{PACKAGE_DATA}/index.html"
#: Where `pnpm -C web build` writes it in the checkout.
BUILT_INDEX: Final[Path] = ROOT / "athanore" / "web" / "dist" / "index.html"

#: Where hatchling puts the root `LICENSE` in the wheel (PEP 639): the
#: `licenses/` directory of the `.dist-info`, whose name carries the
#: version, so it is matched by suffix rather than spelled out.
LICENSE_IN_WHEEL: Final[str] = ".dist-info/licenses/LICENSE"

#: `src="/assets/index-….js"` and `href="/assets/index-….css"`: every
#: file the built document asks the server for by absolute path.
ASSET_REF: Final[re.Pattern[str]] = re.compile(r'(?:src|href)="(/assets/[^"]+)"')

#: A sentence from `athanore.api.static.UNBUILT_PAGE`. A server that
#: answers with it is one whose package data did not arrive.
UNBUILT_MARKER: Final[str] = "The interface is not built"

#: How long to wait for the server to say where it bound, in seconds.
STARTUP_TIMEOUT: Final[float] = 90.0
#: How long any one request to it may take, in seconds.
REQUEST_TIMEOUT: Final[float] = 30.0


class CheckFailed(Exception):
    """A check did not hold. The message is what to do about it."""


def note(message: str) -> None:
    """Say what just passed, on stderr, where the gate's other steps talk."""

    print(f"  {message}", file=sys.stderr, flush=True)


def run(command: Sequence[str], *, cwd: Path | None = None) -> None:
    """Run ``command`` to completion, raising :class:`CheckFailed` if it fails."""

    result = subprocess.run(command, cwd=cwd)
    if result.returncode != 0:
        raise CheckFailed(
            f"`{' '.join(command)}` exited {result.returncode}",
        )


def version() -> str:
    """The version `pyproject.toml` declares, which is the wheel's."""

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(pyproject["project"]["version"])


def require_built_spa() -> None:
    """Step 1: the SPA is built, so the wheel about to be built carries it."""

    if not BUILT_INDEX.is_file():
        raise CheckFailed(
            f"{BUILT_INDEX.relative_to(ROOT)} is not there: run "
            f"`pnpm -C web build` before this check, so the wheel carries a "
            f"fresh SPA rather than whatever was last built locally (T069)."
        )
    note(f"{BUILT_INDEX.relative_to(ROOT)} is built")


def build_distribution() -> Path:
    """Step 2: ``uv build``, and the one wheel it wrote."""

    for stale in DIST.glob("*.whl"):
        stale.unlink()
    run(["uv", "build"], cwd=ROOT)
    wheels = sorted(DIST.glob("*.whl"))
    if len(wheels) != 1:
        raise CheckFailed(
            f"expected exactly one wheel in {DIST.relative_to(ROOT)}, "
            f"found {[w.name for w in wheels]}"
        )
    note(f"built {wheels[0].relative_to(ROOT)}")
    return wheels[0]


def check_wheel_carries_spa(wheel: Path) -> bytes:
    """Step 3: the wheel holds the document and every asset it references.

    Returns the `index.html` the wheel carries, which is what the running
    server is then held against.
    """

    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        if INDEX not in names:
            carried = sorted(n for n in names if n.startswith(f"{PACKAGE_DATA}/"))
            raise CheckFailed(
                f"{wheel.name} carries no {INDEX} (it holds {carried or 'nothing'} "
                f"under {PACKAGE_DATA}/). `pyproject.toml`'s "
                f"`[tool.hatch.build] artifacts` is what puts it there."
            )
        document = archive.read(INDEX)
        referenced = ASSET_REF.findall(document.decode("utf-8"))
        if not referenced:
            raise CheckFailed(
                f"{INDEX} in {wheel.name} references no /assets/… file; "
                f"a document with no bundle is a white page."
            )
        missing = [
            asset
            for asset in referenced
            if f"{PACKAGE_DATA}{asset}" not in names  # asset starts with "/"
        ]
        if missing:
            raise CheckFailed(
                f"{wheel.name} carries {INDEX} but not the assets it asks for: "
                f"{missing}. The SPA in the wheel is not the one that was built."
            )
    note(f"the wheel carries {INDEX} and its {len(referenced)} assets")
    return document


def check_wheel_carries_license(wheel: Path) -> None:
    """Step 3, continued: the wheel holds the checkout's `LICENSE`, byte for byte.

    hatchling puts the root license file under `<dist-info>/licenses/`
    by its default `license-files` glob; `pyproject.toml` declares no
    glob of its own, so this is the check that the default still does.
    """

    expected = (ROOT / "LICENSE").read_bytes()
    with zipfile.ZipFile(wheel) as archive:
        carried = [n for n in archive.namelist() if n.endswith(LICENSE_IN_WHEEL)]
        if len(carried) != 1:
            raise CheckFailed(
                f"{wheel.name} carries {carried or 'no'} …{LICENSE_IN_WHEEL}. "
                f"hatchling ships the root LICENSE by its default license-files "
                f"glob; check that the file is still named LICENSE and that "
                f"pyproject.toml's [project] license is still the SPDX string."
            )
        if archive.read(carried[0]) != expected:
            raise CheckFailed(
                f"{carried[0]} in {wheel.name} is not the LICENSE in the checkout."
            )
    note("the wheel carries LICENSE")


@contextmanager
def clean_install(wheel: Path) -> Iterator[tuple[Path, Path]]:
    """Step 4: ``wheel`` installed into a fresh venv, and a directory to run in.

    Yields the `athanore` console script and a working directory that is
    not the checkout — the point of the whole step, since `athanore/` on
    the current directory would import the source tree and its build
    output whatever the wheel holds.
    """

    with tempfile.TemporaryDirectory(prefix="athanore-wheel-") as temporary:
        area = Path(temporary)
        env = area / "venv"
        run([sys.executable, "-m", "venv", str(env)])
        pip = env / "bin" / "pip"
        if not pip.is_file():
            raise CheckFailed(
                f"{sys.executable} -m venv made no pip at {pip}; the check "
                f"installs the wheel the way an operator would."
            )
        run([str(pip), "install", "--quiet", str(wheel)])
        athanore = env / "bin" / "athanore"
        if not athanore.is_file():
            raise CheckFailed(
                f"{wheel.name} installed but left no `athanore` command; "
                f"`[project.scripts]` is what declares it."
            )
        cwd = area / "run"
        cwd.mkdir()
        note(f"installed {wheel.name} into a clean venv")
        yield athanore, cwd


def child_environment() -> dict[str, str]:
    """This environment with everything Athanore reads taken out of it.

    A stock installation is the subject. `ATHANORE_HOST`, `ATHANORE_PORT`
    and friends are set by `compose.yaml` for the dev stack, and a check
    that passed because of one of them would be a check on this machine
    rather than on the wheel.
    """

    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("ATHANORE_") and key != "PYTHONPATH"
    }


@contextmanager
def serving(athanore: Path, cwd: Path) -> Iterator[str]:
    """Run ``athanore serve --port 0`` in ``cwd`` and yield the URL it printed.

    The output is drained by a thread for as long as the server lives:
    the URL arrives on stdout among uvicorn's own lines, and a pipe
    nobody reads fills up and stops the process being measured.
    """

    process = subprocess.Popen(
        [str(athanore), "serve", "--port", "0"],
        cwd=cwd,
        env=child_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    lines: list[str] = []
    found: dict[str, str] = {}
    ready = threading.Event()

    def drain() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.append(line.rstrip("\n"))
            if line.startswith("Athanore is serving on ") and "url" not in found:
                found["url"] = line.removeprefix("Athanore is serving on ").strip()
                ready.set()
        ready.set()  # the process ended without ever saying it

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        ready.wait(STARTUP_TIMEOUT)
        if "url" not in found:
            process.kill()
            reader.join(timeout=5)
            output = "\n".join(lines) or "(it wrote nothing)"
            raise CheckFailed(
                f"the installed server never said where it bound within "
                f"{STARTUP_TIMEOUT:.0f}s. It said:\n{output}"
            )
        note(f"a clean install serves on {found['url']}")
        yield found["url"]
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=15)
        reader.join(timeout=5)


def fetch(url: str) -> tuple[bytes, str]:
    """``GET url``, as bytes and a content type, or fail saying which URL."""

    try:
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT) as response:
            return response.read(), response.headers.get_content_type()
    except urllib.error.HTTPError as exc:
        raise CheckFailed(f"GET {url} answered {exc.code} {exc.reason}") from exc
    except OSError as exc:
        raise CheckFailed(f"GET {url} failed: {exc}") from exc


def check_it_serves_the_spa(url: str, document: bytes) -> None:
    """Step 5: `/` is the wheel's document, its assets load, `/api/health` is up."""

    body, content_type = fetch(f"{url}/")
    if UNBUILT_MARKER in body.decode("utf-8", "replace"):
        raise CheckFailed(
            f"GET {url}/ answered the 'the interface is not built' page: the "
            f"wheel carries {INDEX} but the installation is not serving it."
        )
    if content_type != "text/html":
        raise CheckFailed(f"GET {url}/ answered {content_type}, not text/html")
    if body != document:
        raise CheckFailed(
            f"GET {url}/ is not the document the wheel carries; the server is "
            f"serving an SPA from somewhere else."
        )
    note("GET / is the document the wheel carries")

    for asset in ASSET_REF.findall(document.decode("utf-8")):
        asset_body, _ = fetch(f"{url}{asset}")
        if not asset_body:
            raise CheckFailed(f"GET {url}{asset} answered an empty body")
    note("every asset the document references is served")

    health, content_type = fetch(f"{url}/api/health")
    if content_type != "application/json":
        raise CheckFailed(
            f"GET {url}/api/health answered {content_type}, not application/json"
        )
    reported = json.loads(health)
    if reported.get("version") != version():
        raise CheckFailed(
            f"GET {url}/api/health reports version {reported.get('version')!r}, "
            f"not the {version()!r} that was just built"
        )
    note(f"GET /api/health is up on version {version()}")


def main() -> int:
    started = time.monotonic()
    try:
        require_built_spa()
        wheel = build_distribution()
        document = check_wheel_carries_spa(wheel)
        check_wheel_carries_license(wheel)
        with clean_install(wheel) as (athanore, cwd):
            with serving(athanore, cwd) as url:
                check_it_serves_the_spa(url, document)
    except CheckFailed as failure:
        print(f"packaging check failed: {failure}", file=sys.stderr, flush=True)
        return 1
    note(f"the wheel ships the SPA ({time.monotonic() - started:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
