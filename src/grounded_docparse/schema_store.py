from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .models import StoredSchema

DEFAULT_DATABASE_PATH = Path("data/document_studio.sqlite3")


class SchemaStore:
    def __init__(self, path: str | Path = DEFAULT_DATABASE_PATH) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schemas (
                name TEXT PRIMARY KEY COLLATE NOCASE,
                fields_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        return connection

    def list(self) -> list[StoredSchema]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT name, fields_json FROM schemas ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [
            StoredSchema(name=name, fields=json.loads(fields_json))
            for name, fields_json in rows
        ]

    def get(self, name: str) -> StoredSchema | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT name, fields_json FROM schemas WHERE name = ? COLLATE NOCASE",
                (name,),
            ).fetchone()
        if row is None:
            return None
        return StoredSchema(name=row[0], fields=json.loads(row[1]))

    def save(self, schema: StoredSchema) -> None:
        now = datetime.now(UTC).isoformat()
        fields_json = json.dumps(
            [field.model_dump(mode="json") for field in schema.fields],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO schemas(name, fields_json, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    fields_json = excluded.fields_json,
                    updated_at = excluded.updated_at
                """,
                (schema.name, fields_json, now, now),
            )

def compile_json_schema(schema: StoredSchema) -> dict:
    properties = {}
    for field in schema.fields:
        field_type = "string" if field.type == "date" else field.type
        description = field.description.strip()
        if field.type == "date":
            description = f"{description} Return an ISO 8601 date.".strip()
        properties[field.name] = {
            "type": [field_type, "null"],
            "description": description,
        }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }
