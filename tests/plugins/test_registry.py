"""Declarations, the six validation checks, and the manifest (T049, 09).

The subject is `athanore.plugins.registry`: what `collect` takes off a
`Workflow`, what `validate` refuses, and what `manifest_entry` publishes.
Everything here is synchronous and touches no store — a declaration is
data, and the point of checking it at registration is that nothing has to
be running to know it is wrong.

Each of the six checks gets a test of its own. A validation suite that
only proves the happy path is what lets a bad declaration reach the SPA,
where the symptom is an empty pane and no error anywhere.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from athanore.plugins.decl import Panel, PanelKind, PluginError, Slot
from athanore.plugins.registry import (
    BUILTIN_WORKFLOW,
    PluginSpec,
    PluginValidationError,
    collect,
    manifest_entry,
    validate,
)
from athanore.workflow import Workflow


class Override(BaseModel):
    """The action form of 09 §Declarations."""

    word: str
    reason: str = ""


def build(name: str = "gamedev", **kwargs: object) -> Workflow:
    """A two-node workflow with nothing declared on it yet."""

    wf = Workflow(name, **kwargs)  # type: ignore[arg-type]

    @wf.node(start=True)
    async def play(qa):
        return qa("go")

    @wf.node()
    async def qa(*, result=None):
        return result

    return wf


def everything(name: str = "gamedev") -> Workflow:
    """One of every declaration, as 09 §Declarations writes them."""

    wf = build(name)

    @wf.route("/words")
    async def words(ctx, limit: int = 50) -> dict:
        """Every word this run has used."""
        return {"words": []}

    @wf.action("override", scope="run", title="Override secret word", confirm=True)
    async def override(ctx, input: Override) -> dict:
        return {"ok": True}

    wf.panel(
        "Words", slot="run", kind="table", source=words, refresh_on=["log.appended"]
    )
    wf.panel(
        "Playfield",
        slot="task",
        node="qa",
        kind="custom",
        element="gd-playfield",
    )
    wf.panel("Override", slot="run", placement="card", kind="form", source=override)

    @wf.on("run.completed")
    async def done(ctx, event) -> None:
        return None

    return wf


def spec_of(wf: Workflow) -> PluginSpec:
    """Collect and validate, which is what `server.register` does."""

    spec = collect(wf)
    validate(spec, wf.finalize())
    return spec


# -- collection ------------------------------------------------------------


def test_collect_takes_every_declaration_in_order():
    spec = collect(everything())

    assert spec.workflow == "gamedev"
    assert [route.path for route in spec.routes] == ["/words"]
    assert [route.methods for route in spec.routes] == [("GET",)]
    assert [action.name for action in spec.actions] == ["override"]
    assert [panel.name for panel in spec.panels] == ["Words", "Playfield", "Override"]
    assert [handler.event for handler in spec.handlers] == ["run.completed"]


def test_panel_is_a_plain_call_that_returns_the_panel():
    """`panel` declares data: there is no function to decorate (D50)."""

    wf = build()
    panel = wf.panel("Words", slot="run", kind="markdown")

    assert isinstance(panel, Panel)
    assert panel is wf.declarations.panels[0]
    assert panel.kind is PanelKind.markdown
    assert panel.placement == "pane"


def test_panel_scope_defaults_to_its_slot():
    wf = build()
    assert wf.panel("A", slot="task", kind="kv").scope is Slot.task
    assert wf.panel("B", slot="run", kind="kv", scope="global").scope is Slot.global_


def test_action_reads_its_model_off_the_input_annotation():
    action = collect(everything()).actions[0]

    assert action.model is Override
    assert action.title == "Override secret word"
    assert action.confirm is True
    assert action.scope is Slot.run


def test_action_without_an_input_parameter_has_no_model():
    wf = build()

    @wf.action("restart")
    async def restart(ctx) -> dict:
        return {}

    assert collect(wf).actions[0].model is None


def test_action_with_an_unmodelled_input_is_refused_at_declaration():
    wf = build()

    with pytest.raises(TypeError, match="pydantic model"):

        @wf.action("bad")
        async def bad(ctx, input: str) -> dict:
            return {}


def test_route_methods_default_to_get_and_are_upper_cased():
    wf = build()

    @wf.route("/one", methods="post")
    async def one(ctx) -> dict:
        return {}

    @wf.route("/two", methods=["put", "PATCH"])
    async def two(ctx) -> dict:
        return {}

    assert [route.methods for route in collect(wf).routes] == [
        ("POST",),
        ("PUT", "PATCH"),
    ]


def test_a_declaration_after_finalize_is_refused():
    from athanore.graph import GraphError

    wf = build()
    wf.finalize()

    with pytest.raises(GraphError, match="already finalized"):
        wf.panel("Late", slot="run", kind="kv")


def test_a_workflow_that_declares_nothing_has_an_empty_spec():
    spec = collect(build())

    assert not spec
    assert spec.routes == () and spec.panels == ()


# -- the six checks --------------------------------------------------------


def test_1_duplicate_names_are_refused():
    wf = build()
    wf.panel("Words", slot="run", kind="kv")
    wf.panel("Words", slot="run", kind="markdown")

    with pytest.raises(PluginValidationError, match="more than one panel named"):
        validate(collect(wf), wf.finalize())


def test_1_duplicate_route_operations_are_refused_and_two_methods_are_not():
    wf = build()

    @wf.route("/words")
    async def get_words(ctx) -> dict:
        return {}

    @wf.route("/words", methods="POST")
    async def post_words(ctx) -> dict:
        return {}

    # One path, two methods: two operations of one resource, not a clash.
    validate(collect(wf), wf.finalize())

    clashing = build()

    @clashing.route("/words")
    async def first(ctx) -> dict:
        return {}

    @clashing.route("/words", methods=["GET", "POST"])
    async def second(ctx) -> dict:
        return {}

    with pytest.raises(PluginValidationError, match="more than one route named"):
        validate(collect(clashing), clashing.finalize())


def test_1_duplicate_action_names_are_refused():
    wf = build()

    @wf.action("override")
    async def first(ctx) -> dict:
        return {}

    @wf.action("override")
    async def second(ctx) -> dict:
        return {}

    with pytest.raises(PluginValidationError, match="more than one action named"):
        validate(collect(wf), wf.finalize())


def test_2_a_panel_naming_a_node_the_graph_lacks_is_refused():
    wf = build()
    wf.panel("Playfield", slot="node", node="nope", kind="custom", element="gd-x")

    with pytest.raises(PluginValidationError, match="node 'nope'"):
        validate(collect(wf), wf.finalize())


def test_2_a_node_slot_panel_that_names_no_node_is_refused():
    wf = build()
    wf.panel("Playfield", slot="node", kind="custom", element="gd-x")

    with pytest.raises(PluginValidationError, match="names no node"):
        validate(collect(wf), wf.finalize())


def test_3_a_custom_panel_without_an_element_is_refused():
    wf = build()
    wf.panel("Playfield", slot="run", kind="custom")

    with pytest.raises(PluginValidationError, match="no `element`"):
        validate(collect(wf), wf.finalize())


def test_4_a_source_that_names_no_route_is_refused():
    wf = build()

    async def orphan(ctx) -> dict:
        return {}

    wf.panel("Words", slot="run", kind="table", source=orphan)

    with pytest.raises(PluginValidationError, match="not one of its routes"):
        validate(collect(wf), wf.finalize())


def test_4_a_form_panel_whose_source_is_not_an_action_is_refused():
    wf = build()

    @wf.route("/words")
    async def words(ctx) -> dict:
        return {}

    wf.panel("Override", slot="run", kind="form", source=words)

    with pytest.raises(PluginValidationError, match="not one of its actions"):
        validate(collect(wf), wf.finalize())


def test_4_a_source_given_as_a_path_resolves(tmp_path: Path):
    wf = build()

    @wf.route("/words")
    async def words(ctx) -> dict:
        return {}

    wf.panel("Words", slot="run", kind="table", source="/words")
    spec = spec_of(wf)

    assert manifest_entry(spec)["panels"][0]["source"] == "/api/plugins/gamedev/words"


def test_5_an_assets_directory_that_does_not_exist_is_refused(tmp_path: Path):
    wf = build(assets=tmp_path / "static")

    with pytest.raises(PluginValidationError, match="not a directory"):
        validate(collect(wf), wf.finalize())


def test_5_an_assets_directory_that_exists_passes(tmp_path: Path):
    (tmp_path / "static").mkdir()
    wf = build(assets=tmp_path / "static")

    validate(collect(wf), wf.finalize())


def test_5_a_relative_assets_path_resolves_against_the_declaring_module():
    """09: `assets="./static"` is relative to the module, not the cwd."""

    wf = build(assets="./static")

    assert wf.assets_base == Path(__file__).resolve().parent
    assert collect(wf).assets_dir() == Path(__file__).resolve().parent / "static"


def test_5_an_assets_root_overrides_the_declaring_module(tmp_path: Path):
    (tmp_path / "static").mkdir()
    wf = build(assets="./static")

    validate(collect(wf), wf.finalize(), tmp_path)


def test_6_an_event_outside_the_vocabulary_is_refused():
    wf = build()

    @wf.on("run.exploded")
    async def handler(ctx, event) -> None:
        return None

    with pytest.raises(PluginValidationError, match="not an event of the vocabulary"):
        validate(collect(wf), wf.finalize())


def test_6_a_plugin_event_in_this_workflows_namespace_is_allowed():
    wf = build()

    @wf.on("plugin.gamedev.scored")
    async def handler(ctx, event) -> None:
        return None

    validate(collect(wf), wf.finalize())


def test_6_a_plugin_event_in_another_namespace_is_refused():
    wf = build()

    @wf.on("plugin.other.scored")
    async def handler(ctx, event) -> None:
        return None

    with pytest.raises(PluginValidationError, match="namespace"):
        validate(collect(wf), wf.finalize())


def test_a_valid_workflow_validates():
    wf = everything()
    validate(collect(wf), wf.finalize())


# -- the manifest ----------------------------------------------------------


def test_manifest_entry_of_one_of_everything():
    entry = manifest_entry(spec_of(everything()))

    assert entry["workflow"] == "gamedev"
    assert entry["assets"] == []
    assert entry["panels"] == [
        {
            "name": "Words",
            "slot": "run",
            "placement": "pane",
            "kind": "table",
            "scope": "run",
            "source": "/api/plugins/gamedev/words",
            "refresh_on": ["log.appended"],
        },
        {
            "name": "Playfield",
            "slot": "task",
            "placement": "pane",
            "kind": "custom",
            "scope": "task",
            "node": "qa",
            "element": "gd-playfield",
            "refresh_on": [],
        },
        {
            "name": "Override",
            "slot": "run",
            "placement": "card",
            "kind": "form",
            "scope": "run",
            "source": "override",
            "refresh_on": [],
        },
    ]


def test_manifest_actions_carry_their_json_schema():
    [action] = manifest_entry(spec_of(everything()))["actions"]

    assert action["name"] == "override"
    assert action["title"] == "Override secret word"
    assert action["scope"] == "run"
    assert action["confirm"] is True
    assert action["schema"] == Override.model_json_schema()
    assert sorted(action["schema"]["properties"]) == ["reason", "word"]


def test_manifest_action_without_a_model_carries_an_empty_object_schema():
    wf = build()

    @wf.action("restart", title="Restart")
    async def restart(ctx) -> dict:
        return {}

    [action] = manifest_entry(spec_of(wf))["actions"]

    assert action["schema"] == {
        "type": "object",
        "title": "Restart",
        "properties": {},
    }


def test_manifest_omits_what_does_not_apply():
    """01 §Real data only: absent, never null."""

    wf = build()
    wf.panel("Notes", slot="global", kind="markdown")

    [panel] = manifest_entry(spec_of(wf))["panels"]

    assert "node" not in panel
    assert "source" not in panel
    assert "element" not in panel


def test_manifest_lists_every_js_asset_as_a_url(tmp_path: Path):
    static = tmp_path / "static"
    (static / "nested").mkdir(parents=True)
    (static / "b.js").write_text("//", encoding="utf-8")
    (static / "a.js").write_text("//", encoding="utf-8")
    (static / "nested" / "c.js").write_text("//", encoding="utf-8")
    (static / "styles.css").write_text("/**/", encoding="utf-8")

    wf = build(assets=static)
    validate(collect(wf), wf.finalize())

    assert manifest_entry(collect(wf))["assets"] == [
        "/plugins/gamedev/static/a.js",
        "/plugins/gamedev/static/b.js",
        "/plugins/gamedev/static/nested/c.js",
    ]


def test_the_builtin_workflow_name_is_reserved_looking():
    assert BUILTIN_WORKFLOW == "_builtin"


def test_plugin_error_carries_its_status_and_message():
    error = PluginError(404, "no such word")

    assert error.status == 404
    assert error.message == "no such word"
    assert str(error) == "no such word"
