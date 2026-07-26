from pathlib import Path

import pytest

from grounded_docparse.jobs import (
    FileArtifactStore,
    JobExecution,
    JobStatus,
    JobStore,
    S3ArtifactStore,
)
from grounded_docparse.models import ProcessingProfile
from grounded_docparse.worker import processing_cache_key


def _store(tmp_path: Path) -> JobStore:
    return JobStore(f"sqlite:///{tmp_path / 'jobs.db'}")


def test_job_submission_is_idempotent_for_same_key(tmp_path: Path) -> None:
    store = _store(tmp_path)

    first = store.create_job(
        source_sha256="a" * 64,
        source_name="document.pdf",
        profile=ProcessingProfile.BALANCED,
        execution=JobExecution.REALTIME,
        idempotency_key="submission-1",
        request={"segmentation": "auto"},
    )
    second = store.create_job(
        source_sha256="a" * 64,
        source_name="document.pdf",
        profile=ProcessingProfile.BALANCED,
        execution=JobExecution.REALTIME,
        idempotency_key="submission-1",
        request={"segmentation": "auto"},
    )

    assert second.id == first.id
    assert second.status is JobStatus.QUEUED


def test_terminal_job_cannot_return_to_running(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job = store.create_job(
        source_sha256="b" * 64,
        source_name="document.pdf",
        profile=ProcessingProfile.FAST,
        execution=JobExecution.BATCH,
        idempotency_key="submission-2",
        request={},
    )
    store.transition(job.id, JobStatus.RUNNING)
    store.transition(job.id, JobStatus.COMPLETED)

    with pytest.raises(ValueError, match="Invalid job transition"):
        store.transition(job.id, JobStatus.RUNNING)


def test_file_artifact_store_rejects_path_escape_and_purges_job(tmp_path: Path) -> None:
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    artifacts.put("jobs/job-1/result/document.json", b"{}")

    assert artifacts.get("jobs/job-1/result/document.json") == b"{}"
    assert artifacts.list("jobs/job-1") == ["jobs/job-1/result/document.json"]
    with pytest.raises(ValueError, match="artifact key"):
        artifacts.put("../secret", b"no")

    artifacts.delete_prefix("jobs/job-1")
    assert artifacts.list("jobs/job-1") == []


class FakeS3:
    def __init__(self) -> None:
        self.objects = {}

    def put_object(self, *, Bucket, Key, Body):
        self.objects[(Bucket, Key)] = Body

    def get_object(self, *, Bucket, Key):
        import io

        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def list_objects_v2(self, *, Bucket, Prefix, **kwargs):
        return {
            "Contents": [
                {"Key": key}
                for bucket, key in sorted(self.objects)
                if bucket == Bucket and key.startswith(Prefix)
            ],
            "IsTruncated": False,
        }

    def delete_objects(self, *, Bucket, Delete):
        for item in Delete["Objects"]:
            self.objects.pop((Bucket, item["Key"]), None)


def test_s3_artifact_store_uses_scoped_keys() -> None:
    client = FakeS3()
    artifacts = S3ArtifactStore("documents", client=client, prefix="docparse")
    artifacts.put("jobs/job-1/result.json", b"{}")

    assert artifacts.get("jobs/job-1/result.json") == b"{}"
    assert artifacts.list("jobs/job-1") == ["jobs/job-1/result.json"]
    artifacts.delete_prefix("jobs/job-1")
    assert artifacts.list("jobs/job-1") == []


def test_processing_cache_key_tracks_source_profile_and_schema(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.create_job(
        source_sha256="c" * 64,
        source_name="one.pdf",
        profile=ProcessingProfile.BALANCED,
        execution=JobExecution.REALTIME,
        idempotency_key="cache-1",
        request={"extraction_schema": {"type": "object"}},
    )
    same = store.create_job(
        source_sha256="c" * 64,
        source_name="renamed.pdf",
        profile=ProcessingProfile.BALANCED,
        execution=JobExecution.REALTIME,
        idempotency_key="cache-2",
        request={"extraction_schema": {"type": "object"}},
    )
    different = store.create_job(
        source_sha256="c" * 64,
        source_name="one.pdf",
        profile=ProcessingProfile.MAXIMUM,
        execution=JobExecution.REALTIME,
        idempotency_key="cache-3",
        request={"extraction_schema": {"type": "object"}},
    )

    assert processing_cache_key(first) == processing_cache_key(same)
    assert processing_cache_key(first) != processing_cache_key(different)
