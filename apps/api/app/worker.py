"""Postgres job runner. SELECT … FOR UPDATE SKIP LOCKED."""

from __future__ import annotations

import logging
import time

from sqlalchemy import text

from accumo_canonical.db import engine, init_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s worker %(message)s")
log = logging.getLogger("accumo.worker")


def loop() -> None:
    init_engine()
    assert engine is not None
    log.info("worker up")
    while True:
        with engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id, kind
                    FROM job
                    WHERE status = 'queued' AND run_after <= now()
                    ORDER BY run_after
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                    """
                )
            ).first()
            if row:
                conn.execute(
                    text("UPDATE job SET status = 'running', attempts = attempts + 1 WHERE id = :id"),
                    {"id": row.id},
                )
                log.info("job id=%s kind=%s", row.id, row.kind)
                conn.execute(text("UPDATE job SET status = 'complete' WHERE id = :id"), {"id": row.id})
        time.sleep(2)


if __name__ == "__main__":
    loop()
