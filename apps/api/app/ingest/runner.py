"""Ingest runner: executes an adapter with run tracking and archival.

Invariant (M1.T1 acceptance): every fetched record is archived and
committed to raw_ingest_archive BEFORE any transform sees it. If a
transform or a later batch fails, everything already fetched is safely on
disk and reprocessable.
"""

import datetime
import logging
from collections.abc import Callable

from sqlalchemy.orm import Session, sessionmaker

from app.db.models import IngestRun, RawIngestArchive, Source
from app.db.partitions import ensure_monthly_partition
from app.ingest.base import RawRecord, SourceAdapter

logger = logging.getLogger(__name__)

Transform = Callable[[Session, list[RawRecord]], None]

MAX_BATCHES_DEFAULT = 1000


def run_ingest(
    adapter: SourceAdapter,
    session_factory: sessionmaker[Session],
    transform: Transform | None = None,
    max_batches: int = MAX_BATCHES_DEFAULT,
) -> IngestRun:
    """Run an adapter to exhaustion (or max_batches). Returns the
    finished IngestRun row; status is 'success' or 'failed', never
    raises for adapter/transform errors (they are recorded on the run)."""
    with session_factory() as session:
        source = session.query(Source).filter(Source.code == adapter.code).one_or_none()
        if source is None:
            raise ValueError(f"Unknown source code: {adapter.code!r}")

        run = IngestRun(source_id=source.id, status="running")
        session.add(run)
        session.commit()
        session.refresh(run)
        run_id, source_id = run.id, source.id

    total = 0
    cursor: str | None = None
    error: str | None = None

    try:
        for _ in range(max_batches):
            result = adapter.fetch_batch(cursor)

            if result.records:
                with session_factory() as session:
                    ensure_monthly_partition(
                        session.connection(),
                        RawIngestArchive.__tablename__,
                        datetime.date.today(),
                    )
                    session.add_all(
                        RawIngestArchive(
                            source_id=source_id,
                            run_id=run_id,
                            kind=r.kind,
                            external_id=r.external_id,
                            payload=r.payload,
                        )
                        for r in result.records
                    )
                    session.commit()  # archived durably before transform

                if transform is not None:
                    with session_factory() as session:
                        transform(session, result.records)
                        session.commit()

                total += len(result.records)

            cursor = result.next_cursor
            if cursor is None:
                break
        else:
            error = f"max_batches ({max_batches}) reached before exhaustion"
    except Exception as exc:  # noqa: BLE001 - recorded on the run row
        error = f"{type(exc).__name__}: {exc}"
        logger.exception("ingest run %s failed", run_id)

    with session_factory() as session:
        run = session.get_one(IngestRun, run_id)
        run.status = "failed" if error else "success"
        run.error = error
        run.records_fetched = total
        run.finished_at = datetime.datetime.now(datetime.UTC)
        session.commit()
        session.refresh(run)
        return run
