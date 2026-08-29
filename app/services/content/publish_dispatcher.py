import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import List, Optional

from loguru import logger
from sqlalchemy import and_, or_
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
# A row a worker never finishes (process killed, deploy, stuck thread) has no
# other way back into the claim query — queued/retrying is not enough. A
# grace window lets a later tick (this process or a fresh one after restart)
# reclaim it. Consumes an attempt like any other claim, so it's bounded by
# max_attempts, not an unbounded retry loop.
#
# The default has real margin above the worst realistic single-attempt wall
# time, not just "a while": get_bytes' fetch timeout is (10, 120) and the
# slowest adapters' upload timeout is (10, 300) — YouTube/LinkedIn — so one
# attempt's HTTP calls alone can take up to ~430s before any semaphore wait
# is even counted. Setting this too low doesn't just strand a row longer;
# it reclaims a row that is still genuinely in flight, and a second worker
# then calls the same platform's publish a second time — an actual duplicate
# post, which is worse than the stuck-row problem this exists to fix. The
# `claimed_attempt_count` fencing in execute_claimed_publication/_handle_*
# is the backstop if this margin is ever wrong under real load, but it does
# not prevent the duplicate call to the platform itself, only the duplicate
# bookkeeping — the margin is the real defense.
STALE_RUNNING_SECONDS = int(os.environ.get("CONTENT_PUBLISH_STALE_RUNNING_SECONDS", 1800))

_executor = ThreadPoolExecutor(
    max_workers=WORKERS, thread_name_prefix="mpt-content-publish"
)
_executor_lock = threading.Lock()
_platform_semaphores: dict[str, threading.BoundedSemaphore] = {}
_platform_semaphores_lock = threading.Lock()
_stop_event = threading.Event()
_dispatcher_thread: Optional[threading.Thread] = None
# Submitted-but-not-yet-finished work. The executor's internal queue is
# unbounded, so without this counter a tick can claim BATCH_SIZE rows every
# interval regardless of how many workers are free: the surplus sits in that
# queue already marked `running` with `updated_at` stamped at claim time,
# and a later tick's stale-running sweep reclaims a row that was never stuck,
# just queued — a second worker then calls the same platform's publish() a
# second time, an actual duplicate post.
_in_flight_lock = threading.Lock()
_in_flight = 0


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

    Also reclaims rows stuck in `running` past `STALE_RUNNING_SECONDS` — the
    only recovery path for a row whose worker never finished (process
    restart, deploy, stuck thread). `attempt_count` already increments on
    every claim, so a reclaim consumes an attempt like any other and is
    bounded by `max_attempts`, not an unbounded loop.
    """
    now = datetime.utcnow()
    stale_cutoff = now - timedelta(seconds=STALE_RUNNING_SECONDS)
    statement = (
        select(ContentSocialPublication)
        .where(
            or_(
                and_(
                    ContentSocialPublication.status.in_(
                        [PublicationStatus.queued, PublicationStatus.retrying]
                    ),
                    or_(
                        ContentSocialPublication.next_run_at.is_(None),
                        ContentSocialPublication.next_run_at <= now,
                    ),
                ),
                and_(
                    ContentSocialPublication.status == PublicationStatus.running,
                    ContentSocialPublication.updated_at < stale_cutoff,
                ),
            )
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


def _handle_success(
    session: Session,
    row: ContentSocialPublication,
    piece: ContentPiece,
    result,
    claimed_attempt_count: int,
) -> None:
    # Fencing check: if attempt_count no longer matches what THIS call's
    # claim produced, another worker has already reclaimed the row (most
    # likely the stale-running sweep firing while this attempt was still
    # genuinely in flight) and owns it now. Writing here would clobber that
    # newer attempt's state with a stale result — drop it instead.
    #
    # session.refresh(), not session.get(): session.get(Model, id,
    # with_for_update=True) forces a real SELECT but does NOT repopulate
    # attributes already loaded on an existing identity-mapped instance
    # unless populate_existing=True is *also* given — a footgun that made an
    # earlier version of this exact fencing check just as inert as having no
    # lock at all. session.refresh() is the tool actually meant for "make
    # this in-memory row reflect the current DB row": it unconditionally
    # re-reads every attribute, no separate opt-in required. The lock taken
    # here is held through the write and commit below (same transaction, no
    # intervening commit), so the check-then-write gap is closed, not moved.
    try:
        session.refresh(row, with_for_update=True)
    except Exception:
        logger.warning(f"publication {row.id} vanished before completion — dropping stale success")
        return
    if row.attempt_count != claimed_attempt_count:
        logger.warning(
            f"publication {row.id} superseded before completion "
            f"(attempt {claimed_attempt_count} no longer current) — dropping stale success"
        )
        return
    row.status = PublicationStatus.succeeded
    row.platform_post_id = result.platform_post_id
    row.platform_post_url = result.platform_post_url
    row.completed_at = datetime.utcnow()
    row.updated_at = datetime.utcnow()
    session.add(row)

    # No commit between the row write above and the piece write below: the
    # spec ("Atualização transacional unificada") requires row + piece to
    # land atomically, otherwise a crash in the gap leaves the publication
    # `succeeded` while the piece never reaches `posted`.
    #
    # Lock the piece row for the recompute+write. Without this, two workers
    # finishing near-simultaneously on the same piece (the normal case for a
    # cross-post to N platforms) each recompute from their own read and the
    # later commit silently overwrites the earlier one's result — permanent
    # drift, not a transient race, since nothing recomputes again until the
    # next publish event on that piece.
    #
    # session.refresh(), not session.get(): `piece` is already loaded in this
    # session, and session.get(..., with_for_update=True) emits the locking
    # SELECT but leaves the already-loaded attributes untouched without
    # populate_existing=True — the same footgun documented above for `row`,
    # which would let `piece.posted_at` read as None here even though the row
    # just locked already carries a value.
    session.refresh(piece, with_for_update=True)
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
    session: Session,
    row: ContentSocialPublication,
    piece: ContentPiece,
    error: PublicationError,
    claimed_attempt_count: int,
) -> None:
    # Same fencing check as _handle_success, same reason — session.refresh(),
    # not session.get(), for the same reason documented there: get() with
    # with_for_update=True alone does not repopulate already-loaded
    # attributes without populate_existing=True too, which made an earlier
    # version of this check inert.
    try:
        session.refresh(row, with_for_update=True)
    except Exception:
        logger.warning(f"publication {row.id} vanished before completion — dropping stale failure")
        return
    if row.attempt_count != claimed_attempt_count:
        logger.warning(
            f"publication {row.id} superseded before completion "
            f"(attempt {claimed_attempt_count} no longer current) — dropping stale failure"
        )
        return
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

    # Same single-transaction requirement as _handle_success — no commit
    # between the row write and the piece write. Same piece-row lock too, and
    # session.refresh() for the same reason documented there: concurrent
    # workers on the same piece must not race a read-recompute-write.
    session.refresh(piece, with_for_update=True)
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
    # Captured once, right after claim — the fencing token _handle_success/
    # _handle_failure use to detect whether this row was reclaimed by
    # another worker (a stale-running sweep firing while this attempt was
    # still genuinely in flight) while this call was in progress.
    claimed_attempt_count = row.attempt_count
    piece = session.get(ContentPiece, row.content_piece_id)
    account = session.get(ContentSocialAccount, row.social_account_id)

    # Setup (asset/adapter/credential lookup) and the adapter call itself are
    # both wrapped — a row already marked `running` by the claim must never be
    # left stuck there. Anything unexpected here still has to resolve to
    # retrying/failed, not silence.
    try:
        asset = get_final_asset(session, content_piece_id=row.content_piece_id)
        if asset is None:
            # Second layer of defense: resolve_publication_request already
            # rejects this pair at request time, but a piece's final asset
            # could be removed/replaced between enqueue and dispatch.
            raise PublicationError(
                PublicationErrorCode.unsupported_capability,
                "content piece has no final asset to publish",
            )
        adapter = get_adapter(row.platform)
        credentials = load_credentials(account)
    except PublicationError as error:
        _handle_failure(session, row, piece, error, claimed_attempt_count)
        return
    except Exception as error:
        _handle_failure(
            session,
            row,
            piece,
            PublicationError(PublicationErrorCode.invalid_params, str(error)),
            claimed_attempt_count,
        )
        return

    # Close the read transaction before the network call: holding it open for
    # the duration of adapter.publish() (up to ~430s in the worst case, see
    # STALE_RUNNING_SECONDS) risks pool exhaustion or being killed by a
    # managed Postgres's idle-in-transaction timeout.
    #
    # expire_on_commit=False is what makes that release actually stick: with
    # the default, this commit expires `piece`/`asset`/`account`, and the very
    # first attribute the adapter touches (piece.type, asset.url) lazy-loads
    # and immediately re-opens a transaction that then stays open for the
    # whole HTTP call. The handlers below re-read under an explicit
    # session.refresh(..., with_for_update=True), so nothing downstream relies
    # on commit-time expiry for freshness.
    session.expire_on_commit = False
    session.commit()

    semaphore = _platform_semaphore(row.platform)
    semaphore.acquire()
    try:
        result = adapter.publish(piece, asset, account, credentials)
    except PublicationError as error:
        _handle_failure(session, row, piece, error, claimed_attempt_count)
        return
    except Exception as error:
        # Every genuinely retryable failure mode (rate limit, network error,
        # 5xx) already raises PublicationError with the right code via the
        # base-adapter HTTP helpers, and is caught above. Anything landing
        # here is a structural bug (a missing credentials field, an adapter
        # coding error) that fails identically on every attempt — retrying it
        # is pure waste and hides the real problem. Non-retryable.
        _handle_failure(
            session,
            row,
            piece,
            PublicationError(PublicationErrorCode.invalid_params, str(error)),
            claimed_attempt_count,
        )
        return
    finally:
        semaphore.release()

    _handle_success(session, row, piece, result, claimed_attempt_count)


def _run_and_log(publication_id: int) -> None:
    with Session(get_engine()) as session:
        try:
            execute_claimed_publication(session, publication_id)
        except Exception:
            logger.exception(f"unhandled error executing publication {publication_id}")


def _mark_done(_future) -> None:
    global _in_flight
    with _in_flight_lock:
        _in_flight -= 1


def _tick() -> None:
    """Claim only as much work as the pool can actually start — never more.

    `_in_flight` can never overshoot WORKERS: each submit increments it by
    exactly the number of futures created and each future's completion
    decrements it by 1, so `available <= 0` is the only guard needed.
    """
    global _in_flight
    with _in_flight_lock:
        available = WORKERS - _in_flight
    if available <= 0:
        return
    with Session(get_engine()) as session:
        claimed = claim_due_publications(session, limit=min(BATCH_SIZE, available))
        claimed_ids = [row.id for row in claimed]
    if not claimed_ids:
        return
    with _in_flight_lock:
        _in_flight += len(claimed_ids)
    for publication_id in claimed_ids:
        future = _executor.submit(_run_and_log, publication_id)
        future.add_done_callback(_mark_done)


def _loop() -> None:
    while not _stop_event.is_set():
        try:
            _tick()
        except Exception:
            logger.exception("publish dispatcher tick failed")
        _stop_event.wait(DISPATCH_INTERVAL_SECONDS)


def start_dispatcher() -> None:
    # Always builds a *fresh* executor: stop_dispatcher() shuts the previous
    # one down for good, so a stop→start cycle would otherwise come back with
    # a permanently-dead pool. The module-level default above stays eager for
    # callers that drive _tick()/execute_claimed_publication() directly.
    global _dispatcher_thread, _executor, _in_flight
    if _dispatcher_thread is not None:
        return
    with _executor_lock:
        _executor = ThreadPoolExecutor(
            max_workers=WORKERS, thread_name_prefix="mpt-content-publish"
        )
    with _in_flight_lock:
        _in_flight = 0
    _stop_event.clear()
    _dispatcher_thread = threading.Thread(
        target=_loop, name="mpt-content-publish-dispatcher", daemon=True
    )
    _dispatcher_thread.start()


def stop_dispatcher() -> None:
    # Stopping the polling thread is not enough — submitted-but-unfinished
    # futures would be abandoned mid-publish, leaving rows stuck in `running`
    # until the stale sweep. Drain the pool before returning.
    global _dispatcher_thread
    _stop_event.set()
    if _dispatcher_thread is not None:
        _dispatcher_thread.join(timeout=5)
        _dispatcher_thread = None
    with _executor_lock:
        _executor.shutdown(wait=True)
