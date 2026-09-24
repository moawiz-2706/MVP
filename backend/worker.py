from __future__ import annotations

import logging
import signal
import threading
import time

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.models.entities import GHLInstallation
from app.services.ghl_staff_user_service import GHLStaffUserService
from app.services.outbox_service import OutboxService
from app.services.reservation_lifecycle_service import ReservationLifecycleService

logger = logging.getLogger("passport.staff_sync_worker")
_stop = threading.Event()


def _request_stop(signum: int, _frame: object) -> None:
    logger.info("Received signal %s; stopping staff synchronization worker", signum)
    _stop.set()


def sync_all_operators() -> dict[str, int]:
    """Run one complete directory-and-availability reconciliation pass."""
    synced = failed = deactivated = availability_synced = availability_failed = 0
    session_factory = get_session_factory()
    with session_factory() as discovery_db:
        operator_ids = list(
            discovery_db.scalars(
                select(GHLInstallation.operator_id).where(
                    GHLInstallation.is_installed.is_(True),
                    GHLInstallation.lifecycle_status == "active",
                )
            )
        )

    for operator_id in operator_ids:
        with session_factory() as db:
            try:
                result = GHLStaffUserService(db, operator_id).sync_all()
                synced += int(result["synced"])
                deactivated += int(result.get("deactivated", 0))
                availability_synced += int(result.get("availability_synced", 0))
                availability_failed += int(result.get("availability_failed", 0))
            except Exception:
                # Isolate tenant failures so one expired token or missing scope
                # does not stop synchronization for every other sub-account.
                failed += 1
                logger.exception("GHL staff synchronization failed for operator %s", operator_id)

    summary = {
        "synced": synced,
        "failed": failed,
        "deactivated": deactivated,
        "availability_synced": availability_synced,
        "availability_failed": availability_failed,
    }
    logger.info("GHL staff synchronization completed: %s", summary)
    return summary


def process_outbox() -> dict[str, int]:
    """Apply pending external side effects without waiting for the daily cron."""
    settings = get_settings()
    with get_session_factory()() as db:
        result = OutboxService(db, settings).process(limit=20)
    logger.info("GHL outbox processing completed: %s", result)
    return result


def expire_holds() -> dict[str, int]:
    with get_session_factory()() as db:
        result = ReservationLifecycleService(db).expire_pending_holds()
    logger.info("Expired payment holds: %s", result)
    return result


def main() -> None:
    settings = get_settings()
    settings.validate_runtime()
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    interval = settings.ghl_staff_sync_interval_seconds
    logger.info("Starting GHL staff synchronization worker with %ss interval", interval)

    while not _stop.is_set():
        started = time.monotonic()
        sync_all_operators()
        try:
            expire_holds()
        except Exception:
            logger.exception("Payment-hold expiration failed")
        try:
            process_outbox()
        except Exception:
            # Staff reconciliation and outbox processing are independent. A
            # database or worker error must not terminate the long-running loop.
            logger.exception("GHL outbox processing failed")
        remaining = max(0.0, interval - (time.monotonic() - started))
        _stop.wait(remaining)

    logger.info("GHL staff synchronization worker stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()


__all__ = ["expire_holds", "main", "process_outbox", "sync_all_operators"]
