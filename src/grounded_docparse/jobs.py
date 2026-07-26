from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, String, Text, create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .models import ProcessingProfile


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_PROVIDER = "waiting_provider"
    NEEDS_REVIEW = "needs_review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobExecution(StrEnum):
    REALTIME = "realtime"
    BATCH = "batch"


class JobRecord(BaseModel):
    model_config = ConfigDict(use_enum_values=False)

    id: str
    source_sha256: str
    source_name: str
    profile: ProcessingProfile
    execution: JobExecution
    status: JobStatus
    idempotency_key: str
    request: dict[str, Any]
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class Base(DeclarativeBase):
    pass


class JobRow(Base):
    __tablename__ = "document_jobs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    source_sha256: Mapped[str] = mapped_column(String(64), index=True)
    source_name: Mapped[str] = mapped_column(String(500))
    profile: Mapped[str] = mapped_column(String(40))
    execution: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_json: Mapped[str] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.CANCELLED, JobStatus.FAILED},
    JobStatus.RUNNING: {
        JobStatus.WAITING_PROVIDER,
        JobStatus.NEEDS_REVIEW,
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    },
    JobStatus.WAITING_PROVIDER: {
        JobStatus.RUNNING,
        JobStatus.NEEDS_REVIEW,
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    },
    JobStatus.NEEDS_REVIEW: {JobStatus.COMPLETED, JobStatus.CANCELLED},
    JobStatus.COMPLETED: set(),
    JobStatus.FAILED: set(),
    JobStatus.CANCELLED: set(),
}


class JobStore:
    def __init__(self, database_url: str) -> None:
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self.engine = create_engine(database_url, connect_args=connect_args)
        Base.metadata.create_all(self.engine)

    @staticmethod
    def _record(row: JobRow) -> JobRecord:
        return JobRecord(
            id=row.id,
            source_sha256=row.source_sha256,
            source_name=row.source_name,
            profile=ProcessingProfile(row.profile),
            execution=JobExecution(row.execution),
            status=JobStatus(row.status),
            idempotency_key=row.idempotency_key,
            request=json.loads(row.request_json),
            error=row.error,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def create_job(
        self,
        *,
        source_sha256: str,
        source_name: str,
        profile: ProcessingProfile,
        execution: JobExecution,
        idempotency_key: str,
        request: dict[str, Any],
    ) -> JobRecord:
        now = datetime.now(UTC)
        row = JobRow(
            id=f"job-{uuid.uuid4().hex}",
            source_sha256=source_sha256,
            source_name=source_name,
            profile=str(profile),
            execution=str(execution),
            status=str(JobStatus.QUEUED),
            idempotency_key=idempotency_key,
            request_json=json.dumps(request, sort_keys=True, separators=(",", ":")),
            created_at=now,
            updated_at=now,
        )
        try:
            with Session(self.engine) as session:
                session.add(row)
                session.commit()
                session.refresh(row)
                return self._record(row)
        except IntegrityError:
            with Session(self.engine) as session:
                existing = session.scalar(
                    select(JobRow).where(JobRow.idempotency_key == idempotency_key)
                )
                if existing is None:
                    raise
                return self._record(existing)

    def get(self, job_id: str) -> JobRecord | None:
        with Session(self.engine) as session:
            row = session.get(JobRow, job_id)
            return self._record(row) if row is not None else None

    def get_by_idempotency_key(self, key: str) -> JobRecord | None:
        with Session(self.engine) as session:
            row = session.scalar(
                select(JobRow).where(JobRow.idempotency_key == key)
            )
            return self._record(row) if row is not None else None

    def transition(
        self, job_id: str, status: JobStatus, *, error: str | None = None
    ) -> JobRecord:
        with Session(self.engine) as session:
            row = session.get(JobRow, job_id)
            if row is None:
                raise KeyError(job_id)
            current = JobStatus(row.status)
            if status not in _TRANSITIONS[current]:
                raise ValueError(f"Invalid job transition: {current} -> {status}")
            row.status = str(status)
            row.error = error
            row.updated_at = datetime.now(UTC)
            session.commit()
            session.refresh(row)
            return self._record(row)

    def delete(self, job_id: str) -> bool:
        with Session(self.engine) as session:
            row = session.get(JobRow, job_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True


class ArtifactStore(Protocol):
    def put(self, key: str, data: bytes) -> str: ...

    def get(self, key: str) -> bytes: ...

    def list(self, prefix: str) -> list[str]: ...

    def delete_prefix(self, prefix: str) -> None: ...


def _artifact_parts(key: str) -> tuple[str, ...]:
    normalized = PurePosixPath(key.replace("\\", "/"))
    if normalized.is_absolute() or not normalized.parts or ".." in normalized.parts:
        raise ValueError("Invalid artifact key")
    return normalized.parts


class FileArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        target = self.root.joinpath(*_artifact_parts(key)).resolve()
        if self.root != target and self.root not in target.parents:
            raise ValueError("Invalid artifact key")
        return target

    def put(self, key: str, data: bytes) -> str:
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return key

    def get(self, key: str) -> bytes:
        return self._resolve(key).read_bytes()

    def list(self, prefix: str) -> list[str]:
        target = self._resolve(prefix)
        if not target.exists():
            return []
        if target.is_file():
            return [target.relative_to(self.root).as_posix()]
        return sorted(
            path.relative_to(self.root).as_posix()
            for path in target.rglob("*")
            if path.is_file()
        )

    def delete_prefix(self, prefix: str) -> None:
        target = self._resolve(prefix)
        if not target.exists():
            return
        if target.is_file():
            target.unlink()
        else:
            shutil.rmtree(target)


class S3ArtifactStore:
    def __init__(
        self,
        bucket: str,
        *,
        client: Any,
        prefix: str = "",
    ) -> None:
        self.bucket = bucket
        self.client = client
        self.prefix = "/".join(_artifact_parts(prefix)) if prefix else ""

    def _key(self, key: str) -> str:
        value = "/".join(_artifact_parts(key))
        return f"{self.prefix}/{value}" if self.prefix else value

    def put(self, key: str, data: bytes) -> str:
        self.client.put_object(Bucket=self.bucket, Key=self._key(key), Body=data)
        return key

    def get(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=self._key(key))
        return response["Body"].read()

    def list(self, prefix: str) -> list[str]:
        storage_prefix = self._key(prefix)
        continuation: str | None = None
        results: list[str] = []
        while True:
            arguments: dict[str, Any] = {
                "Bucket": self.bucket,
                "Prefix": storage_prefix,
            }
            if continuation:
                arguments["ContinuationToken"] = continuation
            response = self.client.list_objects_v2(**arguments)
            for item in response.get("Contents", []):
                key = str(item["Key"])
                if self.prefix:
                    key = key.removeprefix(f"{self.prefix}/")
                results.append(key)
            if not response.get("IsTruncated"):
                return sorted(results)
            continuation = response.get("NextContinuationToken")

    def delete_prefix(self, prefix: str) -> None:
        keys = self.list(prefix)
        for start in range(0, len(keys), 1_000):
            batch = keys[start : start + 1_000]
            self.client.delete_objects(
                Bucket=self.bucket,
                Delete={
                    "Objects": [{"Key": self._key(key)} for key in batch],
                    "Quiet": True,
                },
            )


def artifact_store_from_env() -> ArtifactStore:
    bucket = os.getenv("DOCPARSE_S3_BUCKET")
    if not bucket:
        return FileArtifactStore(
            Path(os.getenv("DOCPARSE_ARTIFACT_ROOT", ".docparse/artifacts"))
        )
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=os.getenv("DOCPARSE_S3_ENDPOINT"),
        region_name=os.getenv("DOCPARSE_S3_REGION", "us-east-1"),
        aws_access_key_id=os.getenv("DOCPARSE_S3_ACCESS_KEY"),
        aws_secret_access_key=os.getenv("DOCPARSE_S3_SECRET_KEY"),
    )
    return S3ArtifactStore(
        bucket,
        client=client,
        prefix=os.getenv("DOCPARSE_S3_PREFIX", "docparse"),
    )
