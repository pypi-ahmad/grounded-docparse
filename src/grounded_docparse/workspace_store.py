from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from .batch import BatchDocument
from .models import (
    AgenticAnalysis,
    AgentTraceEvent,
    Document,
    Element,
    OcrComparisonResult,
    ParseMetadata,
    ParseResult,
    RuntimeDiagnostics,
    RunUsage,
    VisualRecoveryResult,
)
from .native import NativeDocument, NativeParseResult

WorkspaceStatus = Literal["pending", "processing", "interrupted", "complete", "failed"]


@dataclass(slots=True)
class StoredWorkspaceDocument:
    document: BatchDocument
    status: WorkspaceStatus
    error: str | None
    selection_key: str | None
    analysis_key: str | None
    progress: dict | None
    parsed_source: bytes | None
    result: ParseResult | NativeParseResult | None
    analysis: AgenticAnalysis | None


@dataclass(slots=True)
class StoredWorkspace:
    settings: dict
    usage: RunUsage
    documents: list[StoredWorkspaceDocument]
    updated_at: str


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_result_payload(result: ParseResult | NativeParseResult) -> dict:
    if isinstance(result, NativeParseResult):
        return {
            "kind": "native-v5",
            "document": result.document.model_dump(mode="json"),
            "markdown": result.markdown,
            "json": result.json,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "usage": result.usage.model_dump(
                mode="json", exclude_computed_fields=True
            ),
            "trace": [item.model_dump(mode="json") for item in result.trace],
        }
    return {
        "kind": "legacy-v4",
        "document": result.document.model_dump(mode="json"),
        "markdown": result.markdown,
        "json": result.json,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "base_markdown": result.base_markdown,
        "usage": (
            result.usage.model_dump(mode="json", exclude_computed_fields=True)
            if result.usage
            else None
        ),
        "trace": [item.model_dump(mode="json") for item in result.trace or []],
        "runtime_diagnostics": (
            result.runtime_diagnostics.model_dump(mode="json")
            if result.runtime_diagnostics
            else None
        ),
        "elements": [item.model_dump(mode="json") for item in result.elements],
        "metadata": result.metadata.model_dump(mode="json"),
        "recovery_log": [item.model_dump(mode="json") for item in result.recovery_log],
        "ocr_comparisons": [
            item.model_dump(mode="json") for item in result.ocr_comparisons
        ],
    }


def _parse_result(
    value: dict, annotated_pdf: bytes
) -> ParseResult | NativeParseResult:
    if value.get("kind") == "native-v5":
        return NativeParseResult(
            document=NativeDocument.model_validate(value["document"]),
            markdown=value["markdown"],
            json=value["json"],
            annotated_pdf=annotated_pdf,
            input_tokens=value.get("input_tokens", 0),
            output_tokens=value.get("output_tokens", 0),
            usage=RunUsage.model_validate(value.get("usage", {})),
            trace=[
                AgentTraceEvent.model_validate(item)
                for item in value.get("trace", [])
            ],
        )
    return ParseResult(
        document=Document.model_validate(value["document"]),
        markdown=value["markdown"],
        json=value["json"],
        input_tokens=value["input_tokens"],
        output_tokens=value["output_tokens"],
        annotated_pdf=annotated_pdf,
        base_markdown=value.get("base_markdown", ""),
        usage=(RunUsage.model_validate(value["usage"]) if value.get("usage") else None),
        trace=[AgentTraceEvent.model_validate(item) for item in value.get("trace", [])],
        runtime_diagnostics=(
            RuntimeDiagnostics.model_validate(value["runtime_diagnostics"])
            if value.get("runtime_diagnostics")
            else None
        ),
        elements=[Element.model_validate(item) for item in value.get("elements", [])],
        metadata=ParseMetadata.model_validate(value.get("metadata", {})),
        recovery_log=[
            VisualRecoveryResult.model_validate(item)
            for item in value.get("recovery_log", [])
        ],
        ocr_comparisons=[
            OcrComparisonResult.model_validate(item)
            for item in value.get("ocr_comparisons", [])
        ],
    )


class WorkspaceStore:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.artifact_root = self.database_path.parent / "workspaces"

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS batch_workspace (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                format_version INTEGER NOT NULL,
                result_version TEXT NOT NULL,
                settings_json TEXT NOT NULL,
                usage_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS batch_workspace_documents (
                document_id TEXT PRIMARY KEY,
                ordinal INTEGER NOT NULL,
                name TEXT NOT NULL,
                display_name TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                status TEXT NOT NULL,
                error TEXT,
                selection_key TEXT,
                analysis_key TEXT,
                progress_json TEXT,
                result_json TEXT,
                analysis_json TEXT,
                updated_at TEXT NOT NULL
            );
            """
        )
        return connection

    def _directory(self, document_id: str) -> Path:
        return self.artifact_root / hashlib.sha256(document_id.encode()).hexdigest()

    @staticmethod
    def _write(path: Path, value: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(value)
        os.replace(temporary, path)

    def sync_documents(
        self,
        documents: list[BatchDocument],
        *,
        settings: dict,
        result_version: str,
    ) -> None:
        now = _now()
        keep = {document.id for document in documents}
        for document in documents:
            self._write(self._directory(document.id) / "source.bin", document.source)
        with self._connect() as connection:
            existing = {
                row[0]
                for row in connection.execute(
                    "SELECT document_id FROM batch_workspace_documents"
                )
            }
            connection.execute(
                """
                INSERT INTO batch_workspace(
                    singleton, format_version, result_version, settings_json,
                    usage_json, created_at, updated_at
                ) VALUES (1, 1, ?, ?, ?, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                    result_version=excluded.result_version,
                    settings_json=excluded.settings_json,
                    updated_at=excluded.updated_at
                """,
                (
                    result_version,
                    json.dumps(settings),
                    RunUsage().model_dump_json(exclude_computed_fields=True),
                    now,
                    now,
                ),
            )
            for ordinal, document in enumerate(documents):
                connection.execute(
                    """
                    INSERT INTO batch_workspace_documents(
                        document_id, ordinal, name, display_name, mime_type,
                        content_sha256, status, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                    ON CONFLICT(document_id) DO UPDATE SET
                        ordinal=excluded.ordinal,
                        name=excluded.name,
                        display_name=excluded.display_name,
                        mime_type=excluded.mime_type,
                        updated_at=excluded.updated_at
                    """,
                    (
                        document.id,
                        ordinal,
                        document.name,
                        document.display_name,
                        document.mime_type,
                        document.content_sha256,
                        now,
                    ),
                )
            for document_id in existing - keep:
                connection.execute(
                    "DELETE FROM batch_workspace_documents WHERE document_id = ?",
                    (document_id,),
                )
        for document_id in existing - keep:
            directory = self._directory(document_id)
            if directory.parent == self.artifact_root and directory.exists():
                for path in directory.iterdir():
                    path.unlink()
                directory.rmdir()

    def save_document(
        self,
        document_id: str,
        *,
        status: WorkspaceStatus,
        error: str | None = None,
        selection_key: str | None = None,
        analysis_key: str | None = None,
        progress: dict | None = None,
        parsed_source: bytes | None = None,
        result: ParseResult | NativeParseResult | None = None,
        analysis: AgenticAnalysis | None = None,
    ) -> None:
        directory = self._directory(document_id)
        if parsed_source is not None:
            self._write(directory / "parsed-source.bin", parsed_source)
        if result is not None and result.annotated_pdf is not None:
            self._write(directory / "annotated.pdf", result.annotated_pdf)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE batch_workspace_documents SET
                    status=?, error=?, selection_key=?, analysis_key=?,
                    progress_json=?, result_json=?, analysis_json=?, updated_at=?
                WHERE document_id=?
                """,
                (
                    status,
                    error,
                    selection_key,
                    analysis_key,
                    json.dumps(progress) if progress is not None else None,
                    json.dumps(_parse_result_payload(result)) if result is not None else None,
                    (
                        analysis.model_dump_json(exclude_computed_fields=True)
                        if analysis is not None
                        else None
                    ),
                    _now(),
                    document_id,
                ),
            )

    def save_progress(
        self,
        document_id: str,
        *,
        status: WorkspaceStatus,
        progress: dict | None,
        error: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE batch_workspace_documents SET
                    status=?, error=?, progress_json=?, updated_at=?
                WHERE document_id=?
                """,
                (
                    status,
                    error,
                    json.dumps(progress) if progress is not None else None,
                    _now(),
                    document_id,
                ),
            )

    def save_workspace(self, *, settings: dict, usage: RunUsage) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE batch_workspace SET
                    settings_json=?, usage_json=?, updated_at=?
                WHERE singleton=1
                """,
                (
                    json.dumps(settings),
                    usage.model_dump_json(exclude_computed_fields=True),
                    _now(),
                ),
            )

    def clear(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM batch_workspace_documents")
            connection.execute("DELETE FROM batch_workspace")
        root = self.artifact_root.resolve()
        expected_parent = self.database_path.parent.resolve()
        if root.parent != expected_parent or root.name != "workspaces":
            raise ValueError("workspace artifact path is outside the database directory")
        if root.exists():
            shutil.rmtree(root)

    def load(self, *, result_version: str) -> StoredWorkspace | None:
        with self._connect() as connection:
            workspace = connection.execute(
                "SELECT * FROM batch_workspace WHERE singleton = 1"
            ).fetchone()
            rows = connection.execute(
                "SELECT * FROM batch_workspace_documents ORDER BY ordinal"
            ).fetchall()
        if workspace is None or not rows:
            return None
        incompatible = workspace["result_version"] != result_version
        if incompatible:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE batch_workspace_documents SET
                        status='pending', error=NULL, selection_key=NULL,
                        analysis_key=NULL, progress_json=NULL,
                        result_json=NULL, analysis_json=NULL, updated_at=?
                    """,
                    (_now(),),
                )
                connection.execute(
                    """
                    UPDATE batch_workspace SET result_version=?, updated_at=?
                    WHERE singleton=1
                    """,
                    (result_version, _now()),
                )
        documents: list[StoredWorkspaceDocument] = []
        for row in rows:
            directory = self._directory(row["document_id"])
            source = (directory / "source.bin").read_bytes()
            result = None
            parsed_source = None
            restore_error = (
                "Saved source is corrupt or incomplete"
                if hashlib.sha256(source).hexdigest() != row["content_sha256"]
                else None
            )
            if (
                row["result_json"] is not None
                and not incompatible
                and restore_error is None
            ):
                try:
                    parsed_source = (directory / "parsed-source.bin").read_bytes()
                    result = _parse_result(
                        json.loads(row["result_json"]),
                        (directory / "annotated.pdf").read_bytes(),
                    )
                except Exception:  # noqa: BLE001 - isolate corrupt local artifacts
                    parsed_source = None
                    result = None
                    restore_error = "Saved parse result is corrupt or incomplete"
            if restore_error is not None:
                with self._connect() as connection:
                    connection.execute(
                        """
                        UPDATE batch_workspace_documents SET
                            status='failed', error=?, analysis_key=NULL,
                            result_json=NULL, analysis_json=NULL, updated_at=?
                        WHERE document_id=?
                        """,
                        (restore_error, _now(), row["document_id"]),
                    )
            status = "pending" if incompatible else row["status"]
            if restore_error is not None:
                status = "failed"
            if status == "processing":
                status = "interrupted"
                with self._connect() as connection:
                    connection.execute(
                        """
                        UPDATE batch_workspace_documents
                        SET status='interrupted', updated_at=?
                        WHERE document_id=?
                        """,
                        (_now(), row["document_id"]),
                    )
            documents.append(
                StoredWorkspaceDocument(
                    document=BatchDocument(
                        id=row["document_id"],
                        name=row["name"],
                        display_name=row["display_name"],
                        source=source,
                        mime_type=row["mime_type"],
                        content_sha256=row["content_sha256"],
                    ),
                    status=status,
                    error=(
                        restore_error
                        if restore_error is not None
                        else (None if incompatible else row["error"])
                    ),
                    selection_key=None if incompatible else row["selection_key"],
                    analysis_key=(
                        None
                        if incompatible or restore_error is not None
                        else row["analysis_key"]
                    ),
                    progress=(
                        json.loads(row["progress_json"])
                        if row["progress_json"] and not incompatible
                        else None
                    ),
                    parsed_source=parsed_source,
                    result=result,
                    analysis=(
                        AgenticAnalysis.model_validate_json(row["analysis_json"])
                        if row["analysis_json"] and result is not None
                        else None
                    ),
                )
            )
        return StoredWorkspace(
            settings=json.loads(workspace["settings_json"]),
            usage=RunUsage.model_validate_json(workspace["usage_json"]),
            documents=documents,
            updated_at=workspace["updated_at"],
        )
