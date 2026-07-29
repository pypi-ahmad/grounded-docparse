from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from grounded_docparse.models import SchemaField, StoredSchema
from grounded_docparse.schema_store import SchemaStore, compile_json_schema


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
