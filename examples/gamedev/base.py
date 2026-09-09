"""The seat every `gamedev` stage sits in: one model, one adapter.

The same shape `feature_build` has and for the same reason (05 §Agent
classes): the stages differ in their prompt and, where the node routes on
what they said, their ``output_model``. Everything else is one class.

What that base is, is :class:`pi.PiAgent` — the pinned ``pi-acp``
command, the ``native`` tooling tier and :class:`~pi.PiSessionStats` are
facts about pi, and pi is a vendor the package must not know about (02
§Small core, D14). It matters more here than it does for
`feature_build`: two of these stages drive a real Chrome through pi's
`browser-tools` skill, which is pi's, not Athanore's.
"""

from __future__ import annotations

from pi import PiAgent

__all__ = ["MODEL", "GamedevAgent"]

#: The model every seat runs on, as ``<provider>/<model>`` — the id form
#: pi resolves against `docker/dev/pi/models.json`. It is the same model
#: `feature_build` runs on, named through the same default provider, and
#: `llama-server/qwen3.8-27b` is the LAN copy of it that file also
#: declares. That box answers one request at a time, which is why 04
#: §Programmatic host puts this workflow on the capacity-1 ``local`` pool
#: beside `feature_build` rather than on one of its own.
MODEL = "openrouter/qwen/qwen3.8-27b"


class GamedevAgent(PiAgent):
    """pi, on one model, with reasoning off, for every stage.

    ``thinking = "off"`` is carried from the MVP and is a measurement
    rather than a preference: with reasoning enabled this model spent its
    whole output budget drafting inside one reasoning block and was cut
    off before it emitted a single tool call — four consecutive empty
    engineering attempts, MVP run ``24d000f03bc9``. A stage of this
    pipeline writes a finished game into one file, so the output budget
    is the scarce thing and reasoning is what competes with it.

    Set as a config option by category, never by id, and a rejection is
    logged into the transcript rather than swallowed (20 §Finding 2) — so
    an adapter that cannot turn reasoning off says so instead of quietly
    leaving it on.
    """

    model = MODEL
    thinking = "off"
