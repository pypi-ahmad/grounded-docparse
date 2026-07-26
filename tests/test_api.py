from pathlib import Path

from fastapi.testclient import TestClient

from grounded_docparse.api import AppServices, create_app
from grounded_docparse.jobs import FileArtifactStore, JobStore


def _client(tmp_path: Path):
    dispatched: list[str] = []
    services = AppServices(
        jobs=JobStore(f"sqlite:///{tmp_path / 'jobs.db'}"),
        artifacts=FileArtifactStore(tmp_path / "artifacts"),
        dispatch=dispatched.append,
        api_token="test-token",
    )
    return TestClient(create_app(services)), services, dispatched


def test_job_api_requires_bearer_authentication(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)

    response = client.get("/api/v1/jobs/missing")

    assert response.status_code == 401


def test_submit_status_artifacts_and_purge_job(tmp_path: Path, simple_pdf: bytes) -> None:
    client, services, dispatched = _client(tmp_path)
    headers = {"Authorization": "Bearer test-token", "Idempotency-Key": "upload-1"}

    submitted = client.post(
        "/api/v1/jobs",
        headers=headers,
        files={"file": ("report.pdf", simple_pdf, "application/pdf")},
        data={"profile": "balanced", "execution": "realtime", "segmentation": "auto"},
    )
    duplicate = client.post(
        "/api/v1/jobs",
        headers=headers,
        files={"file": ("report.pdf", simple_pdf, "application/pdf")},
        data={"profile": "balanced", "execution": "realtime", "segmentation": "auto"},
    )

    assert submitted.status_code == 202
    job_id = submitted.json()["id"]
    assert duplicate.json()["id"] == job_id
    assert dispatched == [job_id]
    status = client.get(f"/api/v1/jobs/{job_id}", headers=headers)
    assert status.json()["status"] == "queued"
    source_keys = services.artifacts.list(f"jobs/{job_id}/source")
    assert len(source_keys) == 1
    services.artifacts.put(f"jobs/{job_id}/result/report.json", b"{}")
    downloaded = client.get(
        f"/api/v1/jobs/{job_id}/artifacts/report.json", headers=headers
    )
    assert downloaded.content == b"{}"

    reviewed = client.post(
        f"/api/v1/jobs/{job_id}/reviews",
        headers=headers,
        json={
            "node_id": "node-1",
            "corrected_text": "Verified text",
            "reason": "Compared against the source crop",
        },
    )
    assert reviewed.status_code == 201
    assert len(services.artifacts.list(f"jobs/{job_id}/reviews")) == 1

    deleted = client.delete(f"/api/v1/jobs/{job_id}", headers=headers)
    assert deleted.status_code == 204
    assert services.jobs.get(job_id) is None
    assert services.artifacts.list(f"jobs/{job_id}") == []
