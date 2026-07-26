from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from celery import Celery
from openai import APIConnectionError, APITimeoutError, RateLimitError

from .jobs import (
    ArtifactStore,
    JobRecord,
    JobStatus,
    JobStore,
    artifact_store_from_env,
)
from .models import VerificationState
from .pipeline import DocumentParser


PIPELINE_PROMPT_VERSION = "grounded-vision-v1"


def processing_cache_key(job: JobRecord) -> str:
    """Return a stable key for every input that can affect parser output."""
    payload = {
        "source_sha256": job.source_sha256,
        "profile": job.profile.value,
        "segmentation": job.request.get("segmentation", "auto"),
        "taxonomy": job.request.get("taxonomy"),
        "extraction_schema": job.request.get("extraction_schema"),
        "luna_model": os.getenv("DOCPARSE_LUNA_MODEL", "gpt-5.6-luna"),
        "terra_model": os.getenv("DOCPARSE_TERRA_MODEL", "gpt-5.6-terra"),
        "prompt_version": PIPELINE_PROMPT_VERSION,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _copy_artifacts(
    artifacts: ArtifactStore, source_prefix: str, destination_prefix: str
) -> None:
    for key in artifacts.list(source_prefix):
        suffix = key[len(source_prefix) :].lstrip("/")
        artifacts.put(f"{destination_prefix}/{suffix}", artifacts.get(key))


@dataclass(frozen=True, slots=True)
class ProcessingServices:
    jobs: JobStore
    artifacts: ArtifactStore


def process_job(
    job_id: str,
    services: ProcessingServices,
    *,
    parser_factory: Callable[[], DocumentParser] = DocumentParser,
) -> JobRecord:
    job = services.jobs.get(job_id)
    if job is None:
        raise KeyError(job_id)
    if job.status in {
        JobStatus.COMPLETED,
        JobStatus.NEEDS_REVIEW,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    }:
        return job
    job = services.jobs.transition(job.id, JobStatus.RUNNING)
    try:
        cache_key = processing_cache_key(job)
        cache_prefix = f"cache/{cache_key}/result"
        cache_metadata_key = f"cache/{cache_key}/metadata.json"
        result_prefix = f"jobs/{job.id}/result"
        if services.artifacts.list(cache_metadata_key):
            cache_metadata = json.loads(services.artifacts.get(cache_metadata_key))
            _copy_artifacts(services.artifacts, cache_prefix, result_prefix)
            services.artifacts.put(
                f"jobs/{job.id}/cache.json",
                json.dumps({"status": "hit", "key": cache_key}).encode(),
            )
            return services.jobs.transition(
                job.id, JobStatus(cache_metadata["terminal_status"])
            )

        source_keys = services.artifacts.list(f"jobs/{job.id}/source")
        if len(source_keys) != 1:
            raise RuntimeError("Job must contain exactly one source artifact")
        source = services.artifacts.get(source_keys[0])
        parser = parser_factory()
        result = parser.parse(
            source,
            job.source_name,
            profile=job.profile,
            segmentation=job.request.get("segmentation", "auto"),
            extraction_schema=job.request.get("extraction_schema"),
            taxonomy=job.request.get("taxonomy"),
        )
        stem = Path(job.source_name).stem
        prefix = result_prefix
        outputs: dict[str, bytes | str] = {
            f"{prefix}/{stem}.md": result.markdown,
            f"{prefix}/{stem}.llm.md": result.llm_markdown,
            f"{prefix}/{stem}.json": result.json,
            f"{prefix}/{stem}.audit.json": result.audit_json,
            f"{prefix}/{stem}.failures.jsonl": result.failures_jsonl,
            f"{prefix}/{stem}.quality.json": result.quality_json,
            f"{prefix}/{stem}.annotated.pdf": result.annotated_pdf,
            f"{prefix}/{stem}.batch.manifest.json": result.batch_manifest_json,
            f"{prefix}/{stem}.zip": result.bundle,
        }
        if result.extraction_json:
            outputs[f"{prefix}/{stem}.extraction.json"] = result.extraction_json
        for asset_path, content in result.assets.items():
            outputs[f"{prefix}/{asset_path}"] = content
        for key, value in outputs.items():
            content = value.encode("utf-8") if isinstance(value, str) else value
            services.artifacts.put(key, content)
            suffix = key[len(prefix) :].lstrip("/")
            services.artifacts.put(f"{cache_prefix}/{suffix}", content)
        services.artifacts.put(
            f"jobs/{job.id}/cache.json",
            json.dumps({"status": "miss", "key": cache_key}).encode(),
        )
        review_required = any(
            node.verification_state
            in {VerificationState.NEEDS_REVIEW, VerificationState.REJECTED}
            for node in result.tree.nodes.values()
        )
        terminal_status = (
            JobStatus.NEEDS_REVIEW if review_required else JobStatus.COMPLETED
        )
        services.artifacts.put(
            cache_metadata_key,
            json.dumps({"terminal_status": terminal_status.value}).encode(),
        )
        return services.jobs.transition(
            job.id, terminal_status
        )
    except (APIConnectionError, APITimeoutError, RateLimitError) as exc:
        services.jobs.transition(
            job.id,
            JobStatus.WAITING_PROVIDER,
            error=f"{type(exc).__name__}: transient provider failure",
        )
        raise
    except Exception as exc:
        services.jobs.transition(
            job.id,
            JobStatus.FAILED,
            error=f"{type(exc).__name__}: {str(exc)[:500]}",
        )
        raise


celery_app = Celery(
    "grounded_docparse",
    broker=os.getenv("DOCPARSE_REDIS_URL", "redis://127.0.0.1:6379/0"),
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
)


def _services_from_env() -> ProcessingServices:
    return ProcessingServices(
        jobs=JobStore(
            os.getenv(
                "DOCPARSE_DATABASE_URL",
                "sqlite:///.docparse/jobs.db",
            )
        ),
        artifacts=artifact_store_from_env(),
    )


@celery_app.task(
    name="grounded_docparse.process_job",
    autoretry_for=(APIConnectionError, APITimeoutError, RateLimitError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def process_job_task(job_id: str) -> str:
    return process_job(job_id, _services_from_env()).status


def dispatch_job(job_id: str) -> None:
    services = _services_from_env()
    job = services.jobs.get(job_id)
    if job is None:
        raise KeyError(job_id)
    process_job_task.apply_async(args=[job_id], queue=job.execution.value)
