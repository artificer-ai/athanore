#!/usr/bin/env python
"""The one place a fact about this package is turned into markdown.

One front end frames what is rendered here, and nothing else reads it:
`scripts/gen_docs.py` writes `docs/site/src/reference/`, for a reader who
has neither the checkout nor the specifications. `scripts/gen_skills.py`
republishes those pages into `skills/*/reference/` with their links
rewritten, so the skills carry the same pages rather than a second
framing of the same facts.

What lives here is therefore the *body* of each reference: no title, no
lede, no marker, and no citation of a design document — the reader has
none. Each renderer returns `list[str]`, and the front end wraps it in its
own heading and its own opening paragraph through :func:`document`.

Determinism is the point, as it is in `scripts/dump_openapi.py`: no
timestamps, no version numbers, no absolute paths, and no ordering that
can vary between runs. Enum members and dataclass fields keep declaration
order, which is contract; everything else is sorted.

`scripts/` is dev machinery rather than a package. Nothing in `athanore/`
imports this, and this starts no server, opens no database and reaches no
network — it imports the package, reads its own tree, and reads the
committed OpenAPI snapshot.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import re
from enum import Enum
from pathlib import Path
from types import NoneType
from typing import Any

from pydantic import BaseModel
from typer.main import get_command

import athanore
from athanore.agents.acp import ACPAgent, AgentSession
from athanore.agents.base import Agent, AgentResult
from athanore.api.errors import ErrorCode
from athanore.cli import app as cli_app
from athanore.engine.ops import Ops
from athanore.engine.pools import Pool
from athanore.events.names import EPHEMERAL, EventName
from athanore.events.payloads import PAYLOADS
from athanore.plugins import decl
from athanore.plugins.context import NO_RUN, NO_TASK, PluginContext, PluginServices
from athanore.workflow import Workflow

ROOT = Path(__file__).resolve().parent.parent

#: The committed OpenAPI document, checkout-relative. Read from disk
#: rather than from `create_app()` so that a stale snapshot fails one
#: check — `tests/test_openapi_snapshot.py`'s — instead of two, and so
#: that no generator ever builds an application.
SNAPSHOT = ROOT / "tests" / "snapshots" / "openapi.json"

# --------------------------------------------------------------------------
# Envelope and formatting
# --------------------------------------------------------------------------


def document(lines: list[str], *, marker: str) -> str:
    """The marker, the body, one trailing newline, no trailing blanks."""

    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join([marker, "", *lines]) + "\n"


def first_line(text: str | None) -> str:
    """The first non-empty line of a docstring, whitespace collapsed."""

    for line in (text or "").strip().splitlines():
        if line.strip():
            return " ".join(line.split())
    return ""


def summary(value: Any) -> str:
    """The one-line summary of a class or a function's own docstring.

    ``__doc__`` off the object rather than :func:`inspect.getdoc`, which
    walks the MRO: an exception class with no docstring of its own would
    otherwise be described by :class:`Exception`'s.
    """

    if not (inspect.isclass(value) or inspect.isroutine(value)):
        return ""
    return first_line(getattr(value, "__doc__", None))


def signature(value: Any) -> str | None:
    """``(a: int, *, b: str = 'x')`` for what has one, else ``None``.

    Rendered parameter by parameter rather than by ``str()`` of the
    :class:`inspect.Signature`, because every module here carries ``from
    __future__ import annotations``: the annotations arrive as source
    strings and the default repr quotes each one, which is not what an
    author would type.
    """

    if not (inspect.isclass(value) or inspect.isroutine(value)):
        return None
    try:
        signature = inspect.signature(value)
    except (TypeError, ValueError):  # pragma: no cover - builtins only
        return None
    kinds = inspect.Parameter
    parts: list[str] = []
    previous: Any = None
    seen_star = False
    for name, parameter in signature.parameters.items():
        if name == "self":
            continue
        if previous is kinds.POSITIONAL_ONLY and parameter.kind is not previous:
            parts.append("/")
        if parameter.kind is kinds.KEYWORD_ONLY and not seen_star:
            parts.append("*")
        if parameter.kind in (kinds.VAR_POSITIONAL, kinds.KEYWORD_ONLY):
            seen_star = True
        text = name
        if parameter.kind is kinds.VAR_POSITIONAL:
            text = f"*{name}"
        elif parameter.kind is kinds.VAR_KEYWORD:
            text = f"**{name}"
        annotated = parameter.annotation is not kinds.empty
        if annotated:
            text += f": {type_name(parameter.annotation)}"
        if parameter.default is not kinds.empty:
            joiner = " = " if annotated else "="
            text += f"{joiner}{default(parameter.default)}"
        parts.append(text)
        previous = parameter.kind
    if previous is kinds.POSITIONAL_ONLY:
        parts.append("/")
    rendered = f"({', '.join(parts)})"
    returns = signature.return_annotation
    if not inspect.isclass(value) and returns is not inspect.Signature.empty:
        rendered += f" -> {type_name(returns)}"
    return rendered


def type_name(annotation: Any) -> str:
    """A stable spelling of an annotation, resolved or still a string.

    The payload models resolve theirs (pydantic does it at class
    creation), so what arrives here is sometimes a type object, and
    ``str()`` of one carries ``typing.`` prefixes, ``<class '...'>``
    wrappers and module paths that no author writes.
    """

    if annotation is None or annotation is NoneType:
        return "None"
    if isinstance(annotation, str):
        text = annotation
    elif isinstance(annotation, type):
        return annotation.__name__
    else:
        text = str(annotation)
    text = text.replace("typing.", "")
    text = re.sub(r"<class '([^']+)'>", lambda m: m.group(1).rsplit(".", 1)[-1], text)
    text = re.sub(r"\bathanore(?:\.\w+)*\.(\w+)", r"\1", text)
    if text.startswith("Optional[") and text.endswith("]"):
        text = f"{text[len('Optional[') : -1]} | None"
    return text


def default(value: Any) -> str:
    """How a default is written: by name for a class or an enum member."""

    if inspect.isclass(value):
        return value.__name__
    if isinstance(value, Enum):
        return f"{type(value).__name__}.{value.name}"
    return repr(value)


def relative(obj: Any) -> str | None:
    """The checkout-relative file ``obj`` is defined in, if there is one."""

    try:
        source = inspect.getsourcefile(obj)
    except TypeError:
        return None
    if source is None:  # pragma: no cover - C extensions only
        return None
    try:
        return Path(source).resolve().relative_to(ROOT).as_posix()
    except ValueError:  # pragma: no cover - an installed copy, not a checkout
        return None


def annotated_attributes(cls: type) -> list[tuple[str, str, str]]:
    """``(name, annotation, default)`` for a class's own annotated attributes.

    ``__annotations__`` off the class itself, so a subclass lists what it
    adds rather than repeating its base. The annotations are the source
    strings — every module here carries ``from __future__ import
    annotations`` — which is exactly what an author would type.
    """

    out: list[tuple[str, str, str]] = []
    for name, annotation in vars(cls).get("__annotations__", {}).items():
        if name.startswith("_"):
            continue
        out.append((name, type_name(annotation), default(getattr(cls, name))))
    return out


def dataclass_fields(cls: type) -> list[tuple[str, str, str | None]]:
    """``(name, annotation, default)`` per public field, in declaration order."""

    out: list[tuple[str, str, str | None]] = []
    for field in dataclasses.fields(cls):  # type: ignore[arg-type]
        if field.name.startswith("_"):
            continue
        annotation = type_name(field.type)
        if field.default is not dataclasses.MISSING:
            value: str | None = default(field.default)
        elif field.default_factory is not dataclasses.MISSING:
            # `dict`, `list`, `tuple` — what a `default_factory` is in
            # practice, and the name is what an author would have written.
            value = f"{getattr(field.default_factory, '__name__', 'factory')}()"
        else:
            value = None
        out.append((field.name, annotation, value))
    return out


def declaration(name: str, annotation: str, value: str | None) -> str:
    """One ``- `name: type = default`` bullet."""

    text = f"{name}: {annotation}"
    if value is not None:
        text += f" = {value}"
    return f"- `{text}`"


def members(cls: type[Enum]) -> list[str]:
    """One bullet per enum member, in declaration order.

    The value is written out only where it differs from the member name —
    ``global_`` is spelled ``global`` on the wire, and it is the only one.
    """

    return [
        f"- `{member.name}`"
        + (f" = `{member.value}`" if member.name != member.value else "")
        for member in cls
    ]


def methods(cls: type, *, title: str) -> list[str]:
    """A heading and one bullet per public method of ``cls``."""

    where = relative(cls)
    lines = [f"{title}" + (f" (`{where}`)" if where else ""), ""]
    for name, member in sorted(vars(cls).items()):
        if name.startswith("_") or not inspect.isroutine(member):
            continue
        rendered = signature(member) or "(...)"
        rendered = rendered.replace("(self, ", "(").replace("(self)", "()")
        prefix = "await " if inspect.iscoroutinefunction(member) else ""
        lines.append(f"- `{prefix}{name}{rendered}`")
        text = summary(member)
        if text:
            lines.append(f"  - {text}")
    lines.append("")
    return lines


def snapshot() -> dict[str, Any]:
    """The committed OpenAPI document, parsed."""

    loaded: dict[str, Any] = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    return loaded


# --------------------------------------------------------------------------
# The package
# --------------------------------------------------------------------------


def public_api() -> list[str]:
    """Every name `athanore` exports, resolved through its `__getattr__`."""

    lines: list[str] = []
    for name in sorted(athanore.__all__):
        value = getattr(athanore, name)
        if inspect.isclass(value):
            kind = "class"
        elif inspect.isroutine(value):
            kind = "function"
        else:
            kind = type(value).__name__
        where = relative(value) or "athanore/__init__.py"
        lines.append(f"- **`{name}`**: {kind}, `{where}`")
        rendered = signature(value)
        if rendered is not None:
            lines.append(f"  - `{name}{rendered}`")
        text = summary(value)
        if text:
            lines.append(f"  - {text}")
    return lines


def node_options() -> list[str]:
    """The metadata seam: `wf.node()`'s keywords, and `Pool`'s fields."""

    lines = ["## `@wf.node(...)`", ""]
    for name, parameter in inspect.signature(Workflow.node).parameters.items():
        if name == "self" or parameter.kind is inspect.Parameter.VAR_KEYWORD:
            continue
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY:
            lines.append(
                declaration(
                    name,
                    type_name(parameter.annotation),
                    default(parameter.default),
                )
            )
    lines += ["", "## `Pool`", ""]
    for name, annotation, value in dataclass_fields(Pool):
        lines.append(declaration(name, annotation, value))
    return lines


def agents() -> list[str]:
    """What an agent subclass may set, and what one run returns."""

    lines = ["## `Agent`", ""]
    for name, annotation, value in annotated_attributes(Agent):
        lines.append(declaration(name, annotation, value))
    lines += [
        "",
        "## `ACPAgent`",
        "",
        "Adds to `Agent`, and inherits the three above.",
        "",
    ]
    for name, annotation, value in annotated_attributes(ACPAgent):
        lines.append(declaration(name, annotation, value))
    lines += [
        "",
        "## `AgentSession`",
        "",
        "What `open()` yields; `run()` is `open()` plus one `prompt()`.",
        "",
    ]
    # `session_id` is annotated on the class and assigned in `__init__`,
    # so it has no class-level value to read a default off.
    for name, annotation in vars(AgentSession).get("__annotations__", {}).items():
        lines.append(declaration(name, type_name(annotation), None))
    prompt = AgentSession.prompt
    lines.append(f"- `await prompt{signature(prompt) or '(...)'}`")
    lines.append(f"  - {summary(prompt)}")
    lines += ["", "## `AgentResult`", ""]
    for name, annotation, value in dataclass_fields(AgentResult):
        lines.append(declaration(name, annotation, value))
    lines.append(f"- `ok`: property. {first_line(AgentResult.ok.__doc__)}")
    return lines


def event_groups() -> list[tuple[str, list[EventName]]]:
    """`EventName`'s members, grouped by the comment blocks of its source."""

    groups: list[tuple[str, list[EventName]]] = []
    for line in inspect.getsource(EventName).splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            groups.append((stripped[2:].strip(), []))
        elif "=" in stripped:
            member = EventName.__members__.get(stripped.split("=", 1)[0].strip())
            if member is not None:
                if not groups:
                    groups.append(("Events", []))
                groups[-1][1].append(member)
    grouped = [(title, group) for title, group in groups if group]
    seen = {member for _, group in grouped for member in group}
    missing = [member.value for member in EventName if member not in seen]
    if missing:
        raise RuntimeError(
            f"athanore/events/names.py has members no comment block covers: "
            f"{missing}. Group them, or this reference would drop them silently."
        )
    return grouped


def payload_fields(model: type[BaseModel]) -> str:
    """One payload's wire fields: ``key?: type``, in declaration order."""

    parts: list[str] = []
    for name, field in model.model_fields.items():
        key = field.serialization_alias or name
        mark = "" if field.is_required() else "?"
        parts.append(f"`{key}{mark}: {type_name(field.annotation)}`")
    return ", ".join(parts) if parts else "no fields"


def events() -> list[str]:
    """The vocabulary, and the payload each name carries."""

    lines: list[str] = []
    for title, group in event_groups():
        lines += [f"## {title}", ""]
        for member in group:
            lines.append(f"- `{member.value}`: {payload_fields(PAYLOADS[member])}")
        lines.append("")
    lines += [
        "## Published but never stored",
        "",
        "`EPHEMERAL` in `athanore/events/names.py`:",
        "",
    ]
    for name in sorted(member.value for member in EPHEMERAL):
        lines.append(f"- `{name}`")
    return lines


# --------------------------------------------------------------------------
# Plugins
# --------------------------------------------------------------------------


def declarations() -> list[str]:
    """The four declarations, the two enums, and the two closed vocabularies."""

    lines: list[str] = []
    for cls in (decl.Route, decl.Action, decl.Panel, decl.Handler):
        lines += [f"## `{cls.__name__}`", ""]
        for name, annotation, value in dataclass_fields(cls):
            lines.append(declaration(name, annotation, value))
        lines.append("")
    lines += [
        "## `Slot` (and `Scope`, which is the same enum)",
        "",
        "Where a panel is shown, and what a declaration needs resolved before",
        "it runs.",
        "",
        *members(decl.Slot),
        "",
        "## `PanelKind`",
        "",
        "The renderer vocabulary: which of these a panel declares fixes",
        "the shape its `source` has to return.",
        "",
        *members(decl.PanelKind),
        "",
        "## `Placement`",
        "",
        *[f"- `{value}`" for value in sorted(decl.PLACEMENTS)],
        "",
        "## Methods a route may declare",
        "",
        *[f"- `{method}`" for method in sorted(decl.METHODS)],
        "",
        "## `PluginError`",
        "",
        f"- `{decl.PluginError.__name__}{signature(decl.PluginError)}`",
        f"  - {summary(decl.PluginError)}",
    ]
    return lines


def service_classes() -> list[tuple[str, type]]:
    """The class behind each property of `PluginServices`, in declaration order.

    Resolved through the module the properties are annotated in, because
    the annotation is a string under PEP 563 and the point of this file is
    the *methods* the class has.
    """

    namespace = vars(inspect.getmodule(PluginServices))
    out: list[tuple[str, type] | None] = []
    for name, member in vars(PluginServices).items():
        if name.startswith("_") or not isinstance(member, property):
            continue
        assert member.fget is not None
        annotation = inspect.signature(member.fget).return_annotation
        target = namespace.get(annotation) if isinstance(annotation, str) else None
        out.append((name, target) if isinstance(target, type) else None)
    resolved = [entry for entry in out if entry is not None]
    if len(resolved) != len(out):
        raise RuntimeError(
            "a service property of athanore/plugins/context.py has a return "
            "annotation this script could not resolve to a class"
        )
    return resolved


def context() -> list[str]:
    """What a handler is handed: the context, its services, and the refusals."""

    lines = ["## Attributes", ""]
    for name, annotation, value in dataclass_fields(PluginContext):
        lines.append(declaration(name, annotation, value))
    lines += [
        "",
        "## `ctx.ops`",
        "",
        f"- {summary(PluginContext.ops.fget)}",
        "",
        *methods(Ops, title="### `Ops`"),
        "## `ctx.services`",
        "",
        "Each is a property, so reaching for one out of scope raises where it",
        "is reached for.",
        "",
    ]
    services = service_classes()
    for name, target in services:
        member = getattr(PluginServices, name)
        lines.append(f"- `ctx.services.{name}` → `{target.__name__}`")
        text = first_line(member.__doc__)
        if text:
            lines.append(f"  - {text}")
    lines.append("")
    for _, target in services:
        lines += methods(target, title=f"### `{target.__name__}`")
    lines += [
        "## Refusals",
        "",
        "What the context itself raises when a handler reaches for something",
        "its scope does not have. Both are `PluginError(400, ...)`, and an",
        "out-of-scope id is a 404 rather than a 403.",
        "",
        f"- `{NO_RUN}`",
        f"- `{NO_TASK}`",
    ]
    return lines


# --------------------------------------------------------------------------
# The wire
# --------------------------------------------------------------------------


def credential(operation: dict[str, Any]) -> str:
    """The security scheme an operation declares, as one word."""

    security = operation.get("security")
    if not security:
        return "none"
    return ", ".join(sorted(scheme for entry in security for scheme in entry))


def route_table() -> list[str]:
    """One row per operation of the committed OpenAPI snapshot."""

    spec = snapshot()
    lines = [
        "| Method | Path | Tag | Operation | Credential | Summary |",
        "|---|---|---|---|---|---|",
    ]
    rows: list[tuple[str, str, str, str, str, str]] = []
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            rows.append(
                (
                    path,
                    method.upper(),
                    ", ".join(operation.get("tags", ())),
                    operation.get("operationId", ""),
                    credential(operation),
                    operation.get("summary", ""),
                )
            )
    for path, method, tags, operation_id, scheme, text in sorted(rows):
        lines.append(
            f"| `{method}` | `{path}` | {tags} | `{operation_id}` | {scheme} | {text} |"
        )
    return lines


def error_codes() -> list[str]:
    """The `code` vocabulary of the error shape, in declaration order."""

    return [f"- `{member.value}`" for member in ErrorCode]


# --------------------------------------------------------------------------
# The command line
# --------------------------------------------------------------------------


def parameter(param: Any) -> str | None:
    """One click parameter as a bullet, or ``None`` for a hidden one."""

    if getattr(param, "hidden", False):
        return None
    if param.param_type_name == "argument":
        label = param.metavar or str(param.name).upper()
        head = f"- `{label}`"
    else:
        head = "- " + ", ".join(f"`{opt}`" for opt in sorted(param.opts))
        if param.metavar:
            head += f" `{param.metavar}`"
    if param.required:
        head += " (required)"
    elif param.default is not None and param.default is not False:
        head += f" (default: `{param.default!r}`)"
    help_text = first_line(getattr(param, "help", None))
    if help_text:
        head += f": {help_text}"
    return head


def command(node: Any, path: str, level: int) -> list[str]:
    """A heading, the help, the parameters, then every subcommand."""

    lines = [f"{'#' * level} `{path}`", ""]
    text = first_line(node.help or node.short_help)
    if text:
        lines += [text, ""]
    rendered = [bullet for bullet in map(parameter, node.params) if bullet is not None]
    if rendered:
        lines += [*rendered, ""]
    for name in sorted(getattr(node, "commands", {})):
        lines += command(node.commands[name], f"{path} {name}", level + 1)
    return lines


def commands() -> list[str]:
    """The command tree, walked through click."""

    root: Any = get_command(cli_app)
    return command(root, "athanore", 2)
