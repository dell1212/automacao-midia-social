from datetime import datetime
from typing import List, Optional

from sqlmodel import Session, select

from app.models.content import ContentCampaign, ContentClient, ContentPiece
from app.models.content_generation import (
    ContentGenerationJob,
    GenerationJobStatus,
    GenerationKind,
)


def create_job(
    session: Session,
    *,
    tenant_id: int,
    client_id: int,
    content_piece_id: int,
    kind: GenerationKind,
    request_payload: dict,
) -> ContentGenerationJob:
    job = ContentGenerationJob(
        tenant_id=tenant_id,
        client_id=client_id,
        content_piece_id=content_piece_id,
        kind=kind,
        status=GenerationJobStatus.queued,
        request_payload=request_payload,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def mark_running(session: Session, job: ContentGenerationJob) -> None:
    job.status = GenerationJobStatus.running
    job.started_at = datetime.utcnow()
    job.updated_at = datetime.utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)


def mark_completed(
    session: Session,
    job: ContentGenerationJob,
    *,
    provider: str,
    model: str,
    response_metadata: Optional[dict] = None,
    input_units: Optional[float] = None,
    output_units: Optional[float] = None,
    estimated_cost: Optional[float] = None,
    actual_cost: Optional[float] = None,
    currency: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> None:
    job.status = GenerationJobStatus.completed
    job.provider = provider
    job.model = model
    job.response_metadata = response_metadata or {}
    job.input_units = input_units
    job.output_units = output_units
    job.estimated_cost = estimated_cost
    job.actual_cost = actual_cost
    job.currency = currency
    job.duration_ms = duration_ms
    job.completed_at = datetime.utcnow()
    job.updated_at = datetime.utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)


def mark_failed(
    session: Session,
    job: ContentGenerationJob,
    *,
    error_code: str,
    error_message: str,
    status: GenerationJobStatus = GenerationJobStatus.failed,
) -> None:
    job.status = status
    job.error_code = error_code
    job.error_message = error_message
    job.failed_at = datetime.utcnow()
    job.updated_at = datetime.utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)


def record_attempt(
    session: Session, job: ContentGenerationJob, *, attempt: int, provider: str, model: str
) -> None:
    job.attempt_count += 1
    if attempt > 1:
        job.retry_count += 1
        job.status = GenerationJobStatus.retrying
    job.provider = provider
    job.model = model
    job.updated_at = datetime.utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)


def is_still_running(session: Session, job_id: int) -> bool:
    """Guard against a late provider response overwriting a settled job.

    A result that arrives after the job timed out must be dropped, not written.
    """
    current = session.get(ContentGenerationJob, job_id)
    return current is not None and current.status in (
        GenerationJobStatus.running,
        GenerationJobStatus.retrying,
    )


def list_jobs_for_piece(
    session: Session, *, tenant_id: int, piece_id: int
) -> List[ContentGenerationJob]:
    return list(
        session.exec(
            select(ContentGenerationJob)
            .join(ContentPiece, ContentPiece.id == ContentGenerationJob.content_piece_id)
            .join(ContentCampaign, ContentCampaign.id == ContentPiece.campaign_id)
            .join(ContentClient, ContentClient.id == ContentCampaign.client_id)
            .where(
                ContentGenerationJob.content_piece_id == piece_id,
                ContentClient.tenant_id == tenant_id,
            )
            .order_by(ContentGenerationJob.id)
        ).all()
    )
