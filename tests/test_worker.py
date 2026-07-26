import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from grounded_docparse.api import AppServices, create_app
from grounded_docparse.config import ParserConfig
from grounded_docparse.jobs import (
    FileArtifactStore,
    JobExecution,
    JobStatus,
    JobStore,
)
from grounded_docparse.models import ProcessingProfile
from grounded_docparse.pipeline import DocumentParser
from grounded_docparse.worker import ProcessingServices, process_job

from test_vision_pipeline import AcceptingVisionGateway


def test_worker_persists_complete_auditable_bundle(tmp_path: Path, simple_pdf: bytes) -> None:
    jobs = JobStore(f"sqlite:///{tmp_path / 'jobs.db'}")
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    digest = hashlib.sha256(simple_pdf).hexdigest()
    job = jobs.create_job(
        source_sha256=digest,
        source_name="report.pdf",
        profile=ProcessingProfile.BALANCED,
        execution=JobExecution.REALTIME,
        idempotency_key="worker-test",
        request={"segmentation": "off"},
    )
    artifacts.put(f"jobs/{job.id}/source/report.pdf", simple_pdf)
    services = ProcessingServices(jobs=jobs, artifacts=artifacts)

    completed = process_job(
        job.id,
        services,
        parser_factory=lambda: DocumentParser(
            ParserConfig(
                enable_paddle=False,
                enable_glm=False,
                enable_openai=True,
                render_dpi=72,
            ),
            gateway_factory=lambda config: AcceptingVisionGateway(),
        ),
    )

    assert completed.status is JobStatus.COMPLETED
    keys = artifacts.list(f"jobs/{job.id}/result")
    assert any(key.endswith(".llm.md") for key in keys)
    assert any(key.endswith(".annotated.pdf") for key in keys)
    assert any(key.endswith(".zip") for key in keys)

    candidate_key = next(
        key
        for key in keys
        if key.endswith("/report.json")
    )
    candidate = artifacts.get(candidate_key)
    client = TestClient(
        create_app(
            AppServices(
                jobs=jobs,
                artifacts=artifacts,
                dispatch=lambda job_id: None,
                api_token="test-token",
            )
        )
    )
    evaluated = client.post(
        "/api/v1/evaluations",
        headers={"Authorization": "Bearer test-token"},
        data={"job_id": job.id},
        files={"gold": ("gold.json", candidate, "application/json")},
    )
    assert evaluated.status_code == 201
    assert evaluated.json()["metrics"]["text"]["character_error_rate"] == 0
    assert len(artifacts.list(f"jobs/{job.id}/evaluations")) == 1


def test_worker_reuses_content_addressed_result_cache(tmp_path: Path, simple_pdf: bytes) -> None:
    jobs = JobStore(f"sqlite:///{tmp_path / 'jobs.db'}")
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    digest = hashlib.sha256(simple_pdf).hexdigest()
    request = {"segmentation": "off"}
    first = jobs.create_job(
        source_sha256=digest,
        source_name="first.pdf",
        profile=ProcessingProfile.FAST,
        execution=JobExecution.REALTIME,
        idempotency_key="first",
        request=request,
    )
    second = jobs.create_job(
        source_sha256=digest,
        source_name="renamed.pdf",
        profile=ProcessingProfile.FAST,
        execution=JobExecution.REALTIME,
        idempotency_key="second",
        request=request,
    )
    for job in (first, second):
        artifacts.put(f"jobs/{job.id}/source/{job.source_name}", simple_pdf)
    services = ProcessingServices(jobs=jobs, artifacts=artifacts)
    calls = 0

    def parser_factory() -> DocumentParser:
        nonlocal calls
        calls += 1
        return DocumentParser(
            ParserConfig(enable_paddle=False, enable_glm=False, enable_openai=True, render_dpi=72),
            gateway_factory=lambda config: AcceptingVisionGateway(),
        )

    assert process_job(first.id, services, parser_factory=parser_factory).status is JobStatus.COMPLETED
    assert process_job(second.id, services, parser_factory=parser_factory).status is JobStatus.COMPLETED

    assert calls == 1
    assert b'"status": "hit"' in artifacts.get(f"jobs/{second.id}/cache.json")
    assert artifacts.list(f"jobs/{second.id}/result")
