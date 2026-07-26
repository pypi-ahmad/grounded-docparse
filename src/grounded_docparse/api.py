from __future__ import annotations

import hashlib
import json
import mimetypes
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from .evaluation import EvaluationReport, evaluate_tree, load_gold_tree
from .ingest import SUPPORTED_EXTENSIONS
from .jobs import ArtifactStore, JobExecution, JobRecord, JobStore
from .models import DocumentTree, ProcessingProfile, SegmentationMode


@dataclass(frozen=True, slots=True)
class AppServices:
    jobs: JobStore
    artifacts: ArtifactStore
    dispatch: Callable[[str], None]
    api_token: str


class ReviewCorrection(BaseModel):
    node_id: str = Field(min_length=1, max_length=1_000)
    corrected_text: str | None = Field(default=None, max_length=100_000)
    corrected_bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)
    reason: str = Field(min_length=1, max_length=2_000)


def create_app(services: AppServices) -> FastAPI:
    app = FastAPI(title="Grounded document parser", version="1.0.0")
    bearer = HTTPBearer(auto_error=False)

    def authorize(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> None:
        if credentials is None or not secrets.compare_digest(
            credentials.credentials, services.api_token
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    secured = [Depends(authorize)]

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(
        "/api/v1/jobs",
        response_model=JobRecord,
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=secured,
    )
    async def submit_job(
        file: Annotated[UploadFile, File()],
        profile: Annotated[ProcessingProfile, Form()] = ProcessingProfile.BALANCED,
        execution: Annotated[JobExecution, Form()] = JobExecution.REALTIME,
        segmentation: Annotated[SegmentationMode, Form()] = SegmentationMode.AUTO,
        taxonomy: Annotated[str | None, Form()] = None,
        extraction_schema: Annotated[str | None, Form()] = None,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> JobRecord:
        source_name = Path(file.filename or "document").name
        if Path(source_name).suffix.casefold() not in SUPPORTED_EXTENSIONS:
            raise HTTPException(status_code=422, detail="Unsupported document type")
        source = await file.read()
        source_sha256 = hashlib.sha256(source).hexdigest()
        request: dict[str, Any] = {
            "segmentation": str(segmentation),
            "taxonomy": _optional_json(taxonomy, "taxonomy"),
            "extraction_schema": _optional_json(
                extraction_schema, "extraction_schema"
            ),
        }
        if idempotency_key is None:
            canonical = json.dumps(
                {
                    "source_sha256": source_sha256,
                    "profile": str(profile),
                    "execution": str(execution),
                    "request": request,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            idempotency_key = hashlib.sha256(canonical.encode()).hexdigest()
        existing = services.jobs.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing
        job = services.jobs.create_job(
            source_sha256=source_sha256,
            source_name=source_name,
            profile=profile,
            execution=execution,
            idempotency_key=idempotency_key,
            request=request,
        )
        source_key = f"jobs/{job.id}/source/{source_name}"
        services.artifacts.put(source_key, source)
        services.dispatch(job.id)
        return job

    @app.get(
        "/api/v1/jobs/{job_id}",
        response_model=JobRecord,
        dependencies=secured,
    )
    def get_job(job_id: str) -> JobRecord:
        job = services.jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return job

    @app.get("/api/v1/jobs/{job_id}/artifacts", dependencies=secured)
    def list_artifacts(job_id: str) -> dict[str, list[str]]:
        if services.jobs.get(job_id) is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return {"artifacts": services.artifacts.list(f"jobs/{job_id}/result")}

    @app.get(
        "/api/v1/jobs/{job_id}/artifacts/{artifact_path:path}",
        dependencies=secured,
    )
    def download_artifact(job_id: str, artifact_path: str) -> Response:
        if services.jobs.get(job_id) is None:
            raise HTTPException(status_code=404, detail="Job not found")
        key = f"jobs/{job_id}/result/{artifact_path}"
        try:
            content = services.artifacts.get(key)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="Artifact not found") from exc
        media_type = mimetypes.guess_type(artifact_path)[0] or "application/octet-stream"
        return Response(content=content, media_type=media_type)

    @app.post(
        "/api/v1/jobs/{job_id}/reviews",
        status_code=status.HTTP_201_CREATED,
        dependencies=secured,
    )
    def record_review(job_id: str, correction: ReviewCorrection) -> dict[str, str]:
        if services.jobs.get(job_id) is None:
            raise HTTPException(status_code=404, detail="Job not found")
        review_id = f"review-{uuid.uuid4().hex}"
        key = f"jobs/{job_id}/reviews/{review_id}.json"
        payload = {
            "schema_version": "1.0.0",
            "id": review_id,
            "job_id": job_id,
            "verification_state": "human_verified",
            "created_at": datetime.now(UTC).isoformat(),
            **correction.model_dump(mode="json"),
        }
        services.artifacts.put(
            key,
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        return {"id": review_id, "artifact": key}

    @app.post(
        "/api/v1/evaluations",
        response_model=EvaluationReport,
        status_code=status.HTTP_201_CREATED,
        dependencies=secured,
    )
    async def evaluate_job(
        job_id: Annotated[str, Form()],
        gold: Annotated[UploadFile, File()],
    ) -> EvaluationReport:
        job = services.jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        candidate_key = (
            f"jobs/{job.id}/result/{Path(job.source_name).stem}.json"
        )
        try:
            candidate = DocumentTree.model_validate_json(
                services.artifacts.get(candidate_key)
            )
            gold_tree = load_gold_tree(await gold.read())
            report = evaluate_tree(candidate, gold_tree)
        except (FileNotFoundError, KeyError) as exc:
            raise HTTPException(
                status_code=409, detail="Candidate result is not available"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        evaluation_id = f"evaluation-{uuid.uuid4().hex}"
        services.artifacts.put(
            f"jobs/{job.id}/evaluations/{evaluation_id}.json",
            report.model_dump_json(indent=2).encode("utf-8"),
        )
        return report

    @app.delete(
        "/api/v1/jobs/{job_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=secured,
    )
    def purge_job(job_id: str) -> Response:
        if not services.jobs.delete(job_id):
            raise HTTPException(status_code=404, detail="Job not found")
        services.artifacts.delete_prefix(f"jobs/{job_id}")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return app


def _optional_json(value: str | None, field_name: str) -> Any:
    if value is None or not value.strip():
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=422, detail=f"{field_name} must be valid JSON"
        ) from exc
