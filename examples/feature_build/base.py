"""The seat every `feature_build` stage sits in: one model, one adapter.

The workflow's agents differ in exactly two things — the prompt they
carry and, where the node routes on a verdict, the model that verdict has
to fit. Everything else is shared, and shared configuration is a base
class (05 §Agent classes, carried from the MVP).

What that base is, is :class:`pi.PiAgent`: the pinned ``pi-acp`` command,
the ``native`` tooling tier and :class:`~pi.PiSessionStats` live there
because they are facts about pi, and pi is a vendor the package must not
know about (02 §Small core, D14). A second adapter for this pipeline is a
second base class beside this one, not an edit to the workflow.
"""

from __future__ import annotations

from pi import PiAgent

__all__ = ["MODEL", "FeatureBuildAgent"]

#: The model every seat runs on, as ``<provider>/<model>`` — the id form
#: pi resolves against `docker/dev/pi/models.json`, whose default
#: provider is OpenRouter. `llama-server/qwen3.8-27b` is the same model
#: on the LAN box that file also declares; it answers one request at a
#: time, which is why `examples/__main__.py` registers this workflow on a
#: capacity-1 pool either way.
#:
#: An id the running agent does not know is **not** silently swapped for
#: its default: the façade resolves ``model`` as an ACP config option by
#: category and logs the rejection into the transcript (20 §Finding 2).
MODEL = "openrouter/qwen/qwen3.8-27b"


class FeatureBuildAgent(PiAgent):
    """pi, on one model, for every stage of this pipeline.

    Subclasses add ``system_prompt`` and — for the two stages the graph
    routes on — ``output_model``. Nothing else: a stage that needed its
    own command or its own tier would be a different seat.
    """

    model = MODEL
