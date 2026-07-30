from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from grounded_docparse.models import ClassifierProfile, SchemaField, StoredSchema
from grounded_docparse.schema_store import (
    MAX_MARKDOWN_SCHEMA_BYTES,
    ClassifierProfileStore,
    SchemaStore,
    compile_json_schema,
    parse_markdown_classifier_profile,
    parse_markdown_schema,
)


def _schema() -> StoredSchema:
    return StoredSchema(
        name="Invoice",
        fields=[
            SchemaField(
                name="invoice_number",
                description="Official invoice ID",
                type="string",
            ),
            SchemaField(
                name="due_date",
                description="Payment due date",
                type="date",
            ),
        ],
    )


def test_schema_store_save_list_get_and_case_insensitive_replacement(tmp_path) -> None:
    store = SchemaStore(tmp_path / "studio.sqlite3")
    store.save(_schema())

    assert store.get("invoice").name == "Invoice"
    assert [item.name for item in store.list()] == ["Invoice"]

    replacement = _schema().model_copy(update={"name": "invoice"})
    replacement.fields[0].description = "Updated"
    store.save(replacement)
    assert len(store.list()) == 1
    assert store.get("INVOICE").fields[0].description == "Updated"

def test_date_compiles_to_nullable_iso_string() -> None:
    compiled = compile_json_schema(_schema())

    assert compiled["properties"]["due_date"]["type"] == ["string", "null"]
    assert "ISO 8601" in compiled["properties"]["due_date"]["description"]
    assert compiled["additionalProperties"] is False


def test_schema_json_round_trip_and_validation() -> None:
    payload = _schema().model_dump_json(indent=2)
    assert StoredSchema.model_validate_json(payload) == _schema()

    invalid = json.loads(payload)
    invalid["fields"].append(invalid["fields"][0])
    with pytest.raises(ValidationError, match="unique"):
        StoredSchema.model_validate_json(json.dumps(invalid))


def test_parse_markdown_schema_table() -> None:
    schema = parse_markdown_schema(
        b"""# Invoice
| Field name | Description | Type |
| --- | --- | --- |
| invoice_number | Official invoice ID | |
| total_amount | Total \\| including tax | number |
""",
        "ignored.md",
    )

    assert schema.name == "Invoice"
    assert [field.model_dump() for field in schema.fields] == [
        {
            "name": "invoice_number",
            "description": "Official invoice ID",
            "type": "string",
        },
        {
            "name": "total_amount",
            "description": "Total | including tax",
            "type": "number",
        },
    ]


def test_parse_markdown_schema_bullets_uses_filename_fallback() -> None:
    schema = parse_markdown_schema(
        b"""- invoice_number: Official invoice ID: printed near the top
- due_date (date): Payment due date
""",
        "invoice-fields.md",
    )

    assert schema.name == "invoice-fields"
    assert [field.type for field in schema.fields] == ["string", "date"]
    assert schema.fields[0].description == "Official invoice ID: printed near the top"


@pytest.mark.parametrize(
    "content, message",
    [
        (b"- bad-name: Invalid field", "Malformed"),
        (b"- amount (currency): Total", "Unsupported field type"),
        (b"- name: First\n- NAME: Second", "unique"),
        (
            b"| Field name | Description |\n| --- | --- |\n| name | Value |\n- other: Value",
            "cannot mix",
        ),
        (b"- name missing colon", "Malformed"),
    ],
)
def test_parse_markdown_schema_rejects_invalid_fields(
    content: bytes, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        parse_markdown_schema(content, "fields.md")


def test_parse_markdown_schema_rejects_invalid_file_input() -> None:
    with pytest.raises(ValueError, match="UTF-8"):
        parse_markdown_schema(b"\xff", "fields.md")
    with pytest.raises(ValueError, match=".md extension"):
        parse_markdown_schema(b"- name: Value", "fields.txt")
    with pytest.raises(ValueError, match="exceeds 1 MB"):
        parse_markdown_schema(b"x" * (MAX_MARKDOWN_SCHEMA_BYTES + 1), "fields.md")


def test_classifier_profile_store_and_markdown_table(tmp_path) -> None:
    profile = parse_markdown_classifier_profile(
        b"""# Medical fax routing
> Treat cover sheets as part of the following form.
| Category | Description | Extract | Schema |
| --- | --- | --- | --- |
| newauth | Initial authorization request | yes | New Authorization |
| authupdate | Existing authorization update | no | |
""",
        "routing.md",
    )
    store = ClassifierProfileStore(tmp_path / "studio.sqlite3")
    store.save(profile)

    assert profile.instructions == "Treat cover sheets as part of the following form."
    assert profile.categories[0].schema_name == "New Authorization"
    assert store.get("MEDICAL FAX ROUTING") == profile
    assert store.list() == [profile]


def test_classifier_profile_markdown_bullets() -> None:
    profile = parse_markdown_classifier_profile(
        b"""# Routing
- newauth [extract=New Authorization]: Initial authorization request
- medical_records: Records without an authorization request
""",
        "routing.md",
    )

    assert profile == ClassifierProfile.model_validate(
        {
            "name": "Routing",
            "categories": [
                {
                    "key": "newauth",
                    "description": "Initial authorization request",
                    "extract": True,
                    "schema_name": "New Authorization",
                },
                {
                    "key": "medical_records",
                    "description": "Records without an authorization request",
                },
            ],
        }
    )


@pytest.mark.parametrize(
    "content, message",
    [
        (b"- other: Reserved", "reserved"),
        (b"- newauth [extract=Missing]: A\n- NEWAUTH: B", "unique"),
        (
            (
                b"| Category | Description | Extract | Schema |\n"
                b"| --- | --- | --- | --- |\n"
                b"| newauth | Request | maybe | Schema |"
            ),
            "Invalid Extract",
        ),
    ],
)
def test_classifier_profile_markdown_rejects_invalid_profiles(
    content: bytes, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        parse_markdown_classifier_profile(content, "routing.md")
