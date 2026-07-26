from __future__ import annotations

import os

from .api import AppServices, create_app
from .jobs import JobStore, artifact_store_from_env
from .worker import dispatch_job


def create_default_app():
    token = os.getenv("DOCPARSE_API_TOKEN")
    if not token:
        raise RuntimeError("DOCPARSE_API_TOKEN is required")
    return create_app(
        AppServices(
            jobs=JobStore(
                os.getenv(
                    "DOCPARSE_DATABASE_URL",
                    "sqlite:///.docparse/jobs.db",
                )
            ),
            artifacts=artifact_store_from_env(),
            dispatch=dispatch_job,
            api_token=token,
        )
    )


app = create_default_app()
