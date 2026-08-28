import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import List, Optional

from loguru import logger
from sqlalchemy import or_
from sqlmodel import Session, select

from app.db import get_engine
from app.models.content import ContentPiece, ContentPieceStatus, ContentSocialAccount
from app.models.content_publishing import ContentSocialPublication, PublicationStatus
from app.services.content import retry
from app.services.content.publish_errors import PublicationError, PublicationErrorCode, is_retryable
from app.services.content.publications import get_final_asset
from app.services.content.publishers.base import get_adapter, load_credentials

DISPATCH_INTERVAL_SECONDS = float(
    os.environ.get("CONTENT_PUBLISH_DISPATCH_INTERVAL_SECONDS", 2)
)
WORKERS = int(os.environ.get("CONTENT_PUBLISH_WORKERS", 4))
BATCH_SIZE = int(os.environ.get("CONTENT_PUBLISH_DISPATCH_BATCH_SIZE", WORKERS))
PLATFORM_CONCURRENCY = int(os.environ.get("CONTENT_PUBLISH_PLATFORM_CONCURRENCY", 2))

_executor = ThreadPoolExecutor(
    max_workers=WORKERS, thread_name_prefix="mpt-content-publish"
)
_platform_semaphores: dict[str, threading.BoundedSemaphore] = {}
_platform_semaphores_lock = threading.Lock()
_stop_event = threading.Event()
_dispatcher_thread: Optional[threading.Thread] = None


def _platform_semaphore(platform: str) -> threading.BoundedSemaphore:
    with _platform_semaphores_lock:
        if platform not in _platform_semaphores:
            _platform_semaphores[platform] = threading.BoundedSemaphore(PLATFORM_CONCURRENCY)
        return _platform_semaphores[platform]


def claim_due_publications(
    session: Session, *, limit: int
) -> List[ContentSocialPublication]:
    """Atomically claim due rows so two dispatcher ticks (or replicas) never
    run the same publication — SKIP LOCKED, not application-level locking.
    """
    now = datetime.utcnow()
    statement = (
        select(ContentSocialPublication)
        .where(
            ContentSocialPublication.status.in_(
                [PublicationStatus.queued, PublicationStatus.retrying]
            ),
            or_(
                ContentSocialPublication.next_run_at.is_(None),
                ContentSocialPublication.next_run_at <= now,
            ),
        )
        .order_by(ContentSocialPublication.next_run_at.nulls_first())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    rows = list(session.exec(statement).all())
    for row in rows:
        row.status = PublicationStatus.running
        row.attempt_count += 1
        row.updated_at = datetime.utcnow()
        session.add(row)
    session.commit()
    return rows


def recompute_publication_summary(session: Session, *, content_piece_id: int) -> dict:
    """Recomputed from source of truth on every call — a jsonb cache patched
    incrementally can drift; recomputing cannot.
    """
    rows = session.exec(
        select(ContentSocialPublication).where(
            ContentSocialPublication.content_piece_id == content_piece_id
        )
    ).all()
    summary = {"total": len(rows), "succeeded": 0, "failed": 0, "pending": 0, "platforms": {}}
    for row in rows:
        platform_counts = summary["platforms"].setdefault(
            row.platform, {"succeeded": 0, "failed": 0}
        )
        if row.status == PublicationStatus.succeeded:
            summary["succeeded"] += 1
            platform_counts["succeeded"] += 1
        elif row.status == PublicationStatus.failed:
            summary["failed"] += 1
            platform_counts["failed"] += 1
        else:
            summary["pending"] += 1
    return summary


def _handle_success(session: Session, row: ContentSocialPublication, piece: ContentPiece, result) -> None:
    row.status = PublicationStatus.succeeded
    row.platform_post_id = result.platform_post_id
    row.platform_post_url = result.platform_post_url
    row.completed_at = datetime.utcnow()
    row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()

    piece.publication_summary = recompute_publication_summary(
        session, content_piece_id=piece.id
    )
    if piece.posted_at is None:
        piece.posted_at = datetime.utcnow()
        piece.status = ContentPieceStatus.posted
    piece.updated_at = datetime.utcnow()
    session.add(piece)
    session.commit()


def _handle_failure(
    session: Session, row: ContentSocialPublication, piece: ContentPiece, error: PublicationError
) -> None:
    row.error_code = error.code.value
    row.error_message = error.message
    row.updated_at = datetime.utcnow()

    if is_retryable(error.code) and row.attempt_count < row.max_attempts:
        row.status = PublicationStatus.retrying
        row.next_run_at = datetime.utcnow() + timedelta(
            seconds=retry.backoff_delay(row.attempt_count)
        )
        session.add(row)
        session.commit()
        return

    row.status = PublicationStatus.failed
    row.completed_at = datetime.utcnow()
    session.add(row)
    session.commit()

    piece.publication_summary = recompute_publication_summary(
        session, content_piece_id=piece.id
    )
    piece.updated_at = datetime.utcnow()
    session.add(piece)
    session.commit()


def execute_claimed_publication(session: Session, publication_id: int) -> None:
    row = session.get(ContentSocialPublication, publication_id)
    if row is None:
        return
    piece = session.get(ContentPiece, row.content_piece_id)
    account = session.get(ContentSocialAccount, row.social_account_id)

    # Setup (asset/adapter/credential lookup) and the adapter call itself are
    # both inside this try — a row already marked `running` by the claim
    # must never be left stuck there. Anything unexpected here still has to
    # resolve to retrying/failed, not silence.
    try:
        asset = get_final_asset(session, content_piece_id=row.content_piece_id)
        adapter = get_adapter(row.platform)
        credentials = load_credentials(account)

        semaphore = _platform_semaphore(row.platform)
        semaphore.acquire()
        try:
            result = adapter.publish(piece, asset, account, credentials)
        finally:
            semaphore.release()
    except PublicationError as error:
        _handle_failure(session, row, piece, error)
        return
    except Exception as error:
        _handle_failure(
            session, row, piece, PublicationError(PublicationErrorCode.transient, str(error))
        )
        return

    _handle_success(session, row, piece, result)


def _run_and_log(publication_id: int) -> None:
    with Session(get_engine()) as session:
        try:
            execute_claimed_publication(session, publication_id)
        except Exception:
            logger.exception(f"unhandled error executing publication {publication_id}")


def _tick() -> None:
    with Session(get_engine()) as session:
        claimed = claim_due_publications(session, limit=BATCH_SIZE)
        claimed_ids = [row.id for row in claimed]
    for publication_id in claimed_ids:
        _executor.submit(_run_and_log, publication_id)


def _loop() -> None:
    while not _stop_event.is_set():
        try:
            _tick()
        except Exception:
            logger.exception("publish dispatcher tick failed")
        _stop_event.wait(DISPATCH_INTERVAL_SECONDS)


def start_dispatcher() -> None:
    global _dispatcher_thread
    if _dispatcher_thread is not None:
        return
    _stop_event.clear()
    _dispatcher_thread = threading.Thread(
        target=_loop, name="mpt-content-publish-dispatcher", daemon=True
    )
    _dispatcher_thread.start()


def stop_dispatcher() -> None:
    global _dispatcher_thread
    _stop_event.set()
    if _dispatcher_thread is not None:
        _dispatcher_thread.join(timeout=5)
        _dispatcher_thread = None
