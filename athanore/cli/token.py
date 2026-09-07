"""``athanore token`` and ``athanore login``: the two secrets (11, 12).

Two files, one rule. Both hold a credential, both are written ``0600``,
and neither is a setting:

- ``{root_path}/.athanore/token`` is the **operator token** a non-loopback
  bind requires (12 §Operator token). It is refused in ``athanore.toml``
  (``settings._TomlSource._REFUSED_KEYS``) precisely so that there is one
  place it can be, and ``token rotate`` is what puts it there. The
  directory is created ``0700``; the file is created ``0600`` and forced
  back to ``0600`` if it was already there under a wider mode, because a
  rotation that left a world-readable token would be worse than no
  rotation at all.
- ``~/.config/athanore/config.toml`` is the **client's** end of the same
  secret (11 §Client connection): the url and token
  :func:`athanore.cli.client.resolve` falls back to. ``login`` writes it,
  and writes nothing else into it — an unknown key there is an error, so
  a file this verb wrote is a file the client can read.

``token show`` prints the token, and that is the point of it: the
operator is on their own machine asking for their own credential. What 12
§Hygiene forbids is *logging* one, which is why the value never reaches
structlog and why the file is the only place it is kept.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Annotated

import typer

from athanore.cli import Options, app
from athanore.cli.client import CONFIG_KEYS, config_path, is_http_url
from athanore.cli.output import EXIT_API_ERROR, emit, fail
from athanore.settings import AthanoreSettings

__all__ = ["login", "rotate", "show", "token_app", "write_secret_file"]

token_app = typer.Typer(
    name="token",
    help="Show or rotate the operator token.",
    no_args_is_help=True,
)
app.add_typer(token_app, name="token")

#: How many random bytes a rotated token carries.
#: ``secrets.token_urlsafe`` renders them base64url, so this is 32 bytes
#: of entropy in 43 characters that survive a shell, a URL and a header.
TOKEN_BYTES = 32


def write_secret_file(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` as a file only its owner can read.

    ``os.open`` with an explicit mode rather than :meth:`Path.write_text`
    plus a :func:`os.chmod`, so the file is never briefly readable
    between being created and being narrowed. The ``chmod`` after it is
    for the other case: an existing file keeps the mode it already had,
    and rotating into a token file somebody had made ``0644`` must not
    leave it that way.
    """

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, 0o600)


def _json(ctx: typer.Context) -> bool:
    """Whether the operator asked for JSON on the application's callback."""

    options = ctx.obj
    return options.json if isinstance(options, Options) else False


@token_app.command("show")
def show(ctx: typer.Context) -> None:
    """Print the operator token this installation would use."""

    settings = AthanoreSettings()
    token = settings.effective_operator_token
    if token is None:
        fail(
            f"no operator token is configured; `athanore token rotate` "
            f"writes one to {settings.token_file}."
        )
        raise typer.Exit(EXIT_API_ERROR)
    # Where it came from, because the two sources behave differently: a
    # token in the environment is gone with the shell, and one in the
    # file is what a server started tomorrow will use.
    source = "file" if settings.operator_token is None else "environment"
    emit(
        {
            "token": token.get_secret_value(),
            "source": source,
            "path": str(settings.token_file),
        },
        json_flag=_json(ctx),
    )


@token_app.command("rotate")
def rotate(ctx: typer.Context) -> None:
    """Generate a new operator token and store it ``0600`` (12)."""

    settings = AthanoreSettings()
    token = secrets.token_urlsafe(TOKEN_BYTES)
    path = settings.token_file
    try:
        write_secret_file(path, token + "\n")
    except OSError as exc:
        fail(f"{path} could not be written: {exc}")
        raise typer.Exit(EXIT_API_ERROR) from exc
    emit({"token": token, "path": str(path)}, json_flag=_json(ctx))


@app.command()
def login(
    ctx: typer.Context,
    url: Annotated[
        str,
        typer.Argument(help="The server to store a token for, e.g. http://host:4002."),
    ],
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            help="The token to store. Prompted for, hidden, if not given.",
        ),
    ] = None,
) -> None:
    """Store a server's URL and operator token for later verbs (11)."""

    if not is_http_url(url):
        raise typer.BadParameter(f"{url!r} is not an http(s) URL.")
    # `hide_input` because this is a credential being typed into a
    # terminal, and a shell that keeps history would otherwise be the
    # third place it lives.
    typed = (
        token if token is not None else typer.prompt("Operator token", hide_input=True)
    )
    secret = str(typed).strip()
    if not secret:
        raise typer.BadParameter("the token is empty.")
    path = config_path()
    try:
        write_secret_file(path, _config_toml(url, secret))
    except OSError as exc:
        fail(f"{path} could not be written: {exc}")
        raise typer.Exit(EXIT_API_ERROR) from exc
    emit({"url": url, "path": str(path)}, json_flag=_json(ctx))


def _config_toml(url: str, token: str) -> str:
    """The whole of ``config.toml``: the two keys 11 gives it, and no more.

    The file is rewritten rather than merged into, because
    :data:`athanore.cli.client.CONFIG_KEYS` is its entire vocabulary — an
    unknown key in it is an error, so there is nothing else in there to
    preserve.

    :func:`json.dumps` is the string encoder: a TOML basic string takes
    the escapes JSON produces (``\\"``, ``\\\\``, ``\\uXXXX`` for the
    control characters), so a token or a URL with a quote in it round
    trips through :mod:`tomllib` instead of writing a file that will not
    parse.
    """

    values = {"url": url, "token": token}
    lines = [f"{key} = {json.dumps(values[key])}" for key in sorted(CONFIG_KEYS)]
    return "\n".join(lines) + "\n"
