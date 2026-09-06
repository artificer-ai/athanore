"""The transcript repository: agent output, written in batches.

07 §Transcript writes: the agent façade buffers chunks in memory and a
flusher writes a batch every ``stream_flush_interval`` as **one** insert
of N rows, then publishes one ephemeral ``task.stream`` event naming the
range. Two to three flushes a second per streaming task is why the batch
matters: a statement per chunk is a round trip per chunk, and on SQLite a
turn of the one writer per chunk.

``seq`` is the cursor ``GET /api/tasks/{id}/stream?after=`` pages by and
is unique per task, so a re-sent batch cannot duplicate the transcript —
the constraint is the schema's (07 §Schema), and this module does not
paper over the ``IntegrityError`` it raises. Sequence numbers start at 1;
:meth:`StreamRepo.last_seq` answers ``0`` for a task that has written
nothing, which is what a restarted flusher counts up from.

Retention is T017's schedule over :meth:`StreamRepo.prune_finished`: the
transcript is diagnostic, and the work log keeps the deliverables.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select

from athanore.store.clock import now
from athanore.store.repos.base import Repo
from athanore.store.rows import StreamChunkRow
from athanore.store.tables import stream_chunks, tasks

#: Rows per ``INSERT``. A flush is one statement; this is the ceiling that
#: keeps an implausibly large burst from exceeding a backend's
#: bind-parameter limit (32766 on SQLite, 65535 on PostgreSQL — 500 rows
#: of five columns is 2500) and failing the flush outright.
MAX_ROWS_PER_INSERT = 500


class StreamRepo(Repo):
    """Queries over ``stream_chunks`` (07 §Schema)."""

    async def append_batch(
        self, task_id: int, chunks: Sequence[tuple[int, str, str]]
    ) -> int:
        """Write ``(seq, kind, text)`` chunks as one multi-row insert.

        Returns how many were written. Raises
        :exc:`~sqlalchemy.exc.IntegrityError` if any ``seq`` is already
        taken for the task: a duplicate transcript segment is a bug in the
        flusher's counter, not something to absorb.
        """

        if not chunks:
            return 0
        stamp = now()
        for start in range(0, len(chunks), MAX_ROWS_PER_INSERT):
            batch = chunks[start : start + MAX_ROWS_PER_INSERT]
            await self.conn.execute(
                stream_chunks.insert().values(
                    [
                        {
                            "task_id": task_id,
                            "seq": seq,
                            "kind": str(kind),
                            "text": text,
                            "created": stamp,
                        }
                        for seq, kind, text in batch
                    ]
                )
            )
        return len(chunks)

    async def list_after(
        self, task_id: int, after_seq: int = 0, limit: int | None = None
    ) -> list[StreamChunkRow]:
        """A task's chunks after ``after_seq``, in transcript order."""

        statement = (
            select(stream_chunks)
            .where(
                stream_chunks.c.task_id == task_id,
                stream_chunks.c.seq > after_seq,
            )
            .order_by(stream_chunks.c.seq)
        )
        if limit is not None:
            statement = statement.limit(limit)
        return self._rows(StreamChunkRow, await self.conn.execute(statement))

    async def last_seq(self, task_id: int) -> int:
        """The highest ``seq`` written for a task, or ``0`` for none."""

        result = await self.conn.execute(
            select(func.max(stream_chunks.c.seq)).where(
                stream_chunks.c.task_id == task_id
            )
        )
        highest = result.scalar_one_or_none()
        return 0 if highest is None else int(highest)

    async def prune_finished(self, before: datetime) -> int:
        """Delete the chunks of tasks that finished before ``before``.

        A running task keeps its transcript however old the chunks are:
        the window is measured from the attempt ending, not from the chunk
        being written, so a long turn is never pruned out from under a
        reader. Tasks that have not finished have a ``NULL`` ``finished``
        and are excluded by the comparison.
        """

        finished = select(tasks.c.id).where(tasks.c.finished < before)
        result = await self.conn.execute(
            stream_chunks.delete().where(stream_chunks.c.task_id.in_(finished))
        )
        return result.rowcount


__all__ = ["MAX_ROWS_PER_INSERT", "StreamRepo"]
