from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .models import ClassifierCategory, ClassifierProfile, SchemaField, StoredSchema

DEFAULT_DATABASE_PATH = Path("data/document_studio.sqlite3")
MAX_MARKDOWN_SCHEMA_BYTES = 1024 * 1024
SUPPORTED_FIELD_TYPES = {"string", "number", "integer", "boolean", "date"}
_HEADING = re.compile(r"^#\s+(.+?)\s*#*\s*$")
_BULLET = re.compile(
    r"^\s*[-*+]\s+([A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s+\(([A-Za-z]+)\))?\s*:\s*(.*)$"
)
_BULLET_PREFIX = re.compile(r"^\s*[-*+]\s+")
_TABLE_SEPARATOR = re.compile(r"^:?-{3,}:?$")
_ROUTING_BULLET = re.compile(
    r"^\s*[-*+]\s+([A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s+\[extract=([^\]]+)\])?\s*:\s*(.+)$"
)


def _table_cells(line: str) -> list[str]:
    value = line.strip()
    value = value.removeprefix("|")
    if value.endswith("|") and not value.endswith(r"\|"):
        value = value[:-1]
    cells: list[str] = []
    current: list[str] = []
    index = 0
    while index < len(value):
        if value[index : index + 2] == r"\|":
            current.append("|")
            index += 2
        elif value[index] == "|":
            cells.append("".join(current).strip())
            current = []
            index += 1
        else:
            current.append(value[index])
            index += 1
    cells.append("".join(current).strip())
    return cells


def _field(name: str, description: str, field_type: str) -> SchemaField:
    normalized_type = field_type.strip().casefold() or "string"
    if normalized_type not in SUPPORTED_FIELD_TYPES:
        raise ValueError(f"Unsupported field type: {field_type}")
    return SchemaField(
        name=name.strip(),
        description=description.strip(),
        type=normalized_type,
    )


def parse_markdown_schema(data: bytes, filename: str) -> StoredSchema:
    if Path(filename).suffix.casefold() != ".md":
        raise ValueError("Markdown schema must use the .md extension")
    if len(data) > MAX_MARKDOWN_SCHEMA_BYTES:
        raise ValueError("Markdown schema exceeds 1 MB")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Markdown schema must be UTF-8") from exc

    lines = text.splitlines()
    heading = next(
        (match.group(1).strip() for line in lines if (match := _HEADING.match(line))),
        None,
    )
    schema_name = heading or Path(filename).stem.strip()

    table_start: int | None = None
    table_width = 0
    for index, line in enumerate(lines[:-1]):
        cells = [cell.casefold() for cell in _table_cells(line)]
        if cells not in (
            ["field name", "description"],
            ["field name", "description", "type"],
        ):
            continue
        separator = _table_cells(lines[index + 1])
        if len(separator) == len(cells) and all(
            _TABLE_SEPARATOR.fullmatch(cell) for cell in separator
        ):
            table_start = index + 2
            table_width = len(cells)
            break

    bullet_lines = [line for line in lines if _BULLET_PREFIX.match(line)]
    if table_start is not None and bullet_lines:
        raise ValueError("Markdown schema cannot mix table and bullet fields")

    fields: list[SchemaField] = []
    if table_start is not None:
        for line in lines[table_start:]:
            if not line.strip():
                break
            cells = _table_cells(line)
            if len(cells) != table_width:
                raise ValueError("Malformed Markdown schema table row")
            fields.append(
                _field(
                    cells[0],
                    cells[1],
                    cells[2] if table_width == 3 else "string",
                )
            )
    else:
        for line in bullet_lines:
            match = _BULLET.fullmatch(line)
            if match is None:
                raise ValueError("Malformed Markdown schema bullet")
            fields.append(
                _field(match.group(1), match.group(3), match.group(2) or "string")
            )

    if not fields:
        raise ValueError("Markdown schema contains no fields")
    return StoredSchema(name=schema_name, fields=fields)


def _markdown_text(data: bytes, filename: str, kind: str) -> tuple[list[str], str]:
    if Path(filename).suffix.casefold() != ".md":
        raise ValueError(f"{kind} must use the .md extension")
    if len(data) > MAX_MARKDOWN_SCHEMA_BYTES:
        raise ValueError(f"{kind} exceeds 1 MB")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{kind} must be UTF-8") from exc
    lines = text.splitlines()
    heading = next(
        (match.group(1).strip() for line in lines if (match := _HEADING.match(line))),
        None,
    )
    return lines, heading or Path(filename).stem.strip()


def _routing_category(
    key: str, description: str, extract_value: str = "", schema_name: str = ""
) -> ClassifierCategory:
    normalized = extract_value.strip().casefold()
    if normalized not in {"", "yes", "no", "true", "false"}:
        raise ValueError(f"Invalid Extract value for category {key}: {extract_value}")
    extract = normalized in {"yes", "true"}
    schema = schema_name.strip() or None
    return ClassifierCategory(
        key=key.strip(),
        description=description.strip(),
        extract=extract,
        schema_name=schema,
    )


def parse_markdown_classifier_profile(data: bytes, filename: str) -> ClassifierProfile:
    lines, profile_name = _markdown_text(data, filename, "Classifier profile")
    instructions = "\n".join(
        line.lstrip()[1:].strip() for line in lines if line.lstrip().startswith(">")
    ).strip()

    table_start: int | None = None
    for index, line in enumerate(lines[:-1]):
        cells = [cell.casefold() for cell in _table_cells(line)]
        if cells != ["category", "description", "extract", "schema"]:
            continue
        separator = _table_cells(lines[index + 1])
        if len(separator) == 4 and all(
            _TABLE_SEPARATOR.fullmatch(cell) for cell in separator
        ):
            table_start = index + 2
            break

    bullet_lines = [line for line in lines if _BULLET_PREFIX.match(line)]
    if table_start is not None and bullet_lines:
        raise ValueError("Classifier profile cannot mix table and bullet categories")

    categories: list[ClassifierCategory] = []
    if table_start is not None:
        for line in lines[table_start:]:
            if not line.strip():
                break
            cells = _table_cells(line)
            if len(cells) != 4:
                raise ValueError("Malformed classifier profile table row")
            categories.append(_routing_category(cells[0], cells[1], cells[2], cells[3]))
    else:
        for line in bullet_lines:
            match = _ROUTING_BULLET.fullmatch(line)
            if match is None:
                raise ValueError("Malformed classifier profile bullet")
            schema_name = (match.group(2) or "").strip()
            categories.append(
                _routing_category(
                    match.group(1),
                    match.group(3),
                    "yes" if schema_name else "no",
                    schema_name,
                )
            )

    if not categories:
        raise ValueError("Classifier profile contains no categories")
    return ClassifierProfile(
        name=profile_name,
        instructions=instructions,
        categories=categories,
    )


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
        return [_stored_schema(name, fields_json) for name, fields_json in rows]

    def get(self, name: str) -> StoredSchema | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT name, fields_json FROM schemas WHERE name = ? COLLATE NOCASE",
                (name,),
            ).fetchone()
        if row is None:
            return None
        return _stored_schema(row[0], row[1])

    def save(self, schema: StoredSchema) -> None:
        now = datetime.now(UTC).isoformat()
        stored_payload = (
            [field.model_dump(mode="json") for field in schema.fields]
            if schema.version == 1
            else schema.model_dump(mode="json", exclude={"name"})
        )
        fields_json = json.dumps(
            stored_payload,
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


class ClassifierProfileStore:
    def __init__(self, path: str | Path = DEFAULT_DATABASE_PATH) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS classifier_profiles (
                name TEXT PRIMARY KEY COLLATE NOCASE,
                profile_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        return connection

    def list(self) -> list[ClassifierProfile]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT profile_json FROM classifier_profiles ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [ClassifierProfile.model_validate_json(row[0]) for row in rows]

    def get(self, name: str) -> ClassifierProfile | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT profile_json FROM classifier_profiles WHERE name = ? COLLATE NOCASE",
                (name,),
            ).fetchone()
        return ClassifierProfile.model_validate_json(row[0]) if row else None

    def save(self, profile: ClassifierProfile) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO classifier_profiles(name, profile_json, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    profile_json = excluded.profile_json,
                    updated_at = excluded.updated_at
                """,
                (profile.name, profile.model_dump_json(), now, now),
            )


def _stored_schema(name: str, payload: str) -> StoredSchema:
    value = json.loads(payload)
    if isinstance(value, list):
        return StoredSchema(name=name, fields=value)
    if isinstance(value, dict):
        return StoredSchema.model_validate({"name": name, **value})
    raise ValueError(f"Stored schema {name!r} has an invalid payload")


def compile_json_schema(schema: StoredSchema) -> dict:
    if schema.version == 2:
        from .extraction import validate_extraction_schema

        compiled = json.loads(json.dumps(schema.json_schema))
        validate_extraction_schema(compiled)
        return compiled
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
