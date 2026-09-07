"""The error body, as a wire model (08 §Conventions, §OpenAPI).

Every failure the API reports is one shape, and until now the document
did not say so: errors are *raised*, so nothing FastAPI generates from a
route signature describes them, and the only 4xx in the snapshot was
FastAPI's own ``HTTPValidationError`` — which is not what
:func:`~athanore.api.errors.validation_error_handler` sends. This module
is that shape written down once, so the generated TypeScript client
carries it and the SPA branches on ``code`` rather than on a message.

The class is deliberately named :class:`ApiError`, the same as the
*exception* in :mod:`athanore.api.errors`: 08 §OpenAPI names the schema
``ApiError``, and a component takes the name of the class FastAPI
generated it from. The two are the same thing in two registers — the
exception a router raises, and the body it becomes — and they are kept
apart by their modules rather than by their names. For that reason it is
the one model this package does **not** re-export from
:mod:`athanore.api.schemas`: a router that writes ``ApiError`` means the
exception, and importing the wire model has to be spelled out.

Nothing constructs one. It is declared as the ``model`` of the error
responses in :mod:`athanore.api.openapi` and rendered by the handlers in
:mod:`athanore.api.errors`, which build the body themselves — a model
that validated a refusal would be one more thing to raise while
reporting a failure.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from athanore.api.errors import ErrorCode
from athanore.events.payloads import ValidationError

__all__ = ["ApiError"]


class ApiError(BaseModel):
    """The body of every refusal: ``{error, code, ...extras}``.

    ``code`` is the :class:`~athanore.api.errors.ErrorCode` vocabulary,
    referenced rather than inlined, which is how the SPA gets a union
    instead of a bare string (08 §OpenAPI). ``errors`` is the extra a
    validation failure and a rejected submission carry, and it is 18's
    :class:`~athanore.events.payloads.ValidationError` rather than a
    second model of the same three fields: one function
    (:func:`~athanore.agents.submissions.validate_submission`) projects
    pydantic's errors onto ``loc``/``msg``/``type``, and the list it
    returns is what the 422 body carries *and* what ``submission.rejected``
    publishes. The rest of 08's "...extras" are open, so the schema allows
    further properties rather than pretending the two named fields are all
    a body can hold.
    """

    model_config = ConfigDict(extra="allow")

    error: str = Field(description="What went wrong, for a person to read.")
    code: ErrorCode = Field(
        description="The stable code a client branches on; the wording of "
        "`error` may change, this may not."
    )
    errors: list[ValidationError] | None = Field(
        default=None,
        description="Per-field detail, on a validation failure or a "
        "rejected submission. Absent otherwise.",
    )
