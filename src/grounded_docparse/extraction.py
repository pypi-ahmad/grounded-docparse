from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from difflib import SequenceMatcher
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .models import (
    DocumentNode,
    DocumentTree,
    ExtractionDecisions,
    ExtractionProvenance,
    LogicalTable,
    Relationship,
    SchemaExtraction,
    ValueCitation,
)

MAX_SCHEMA_BYTES = 256 * 1024
MAX_SCHEMA_DEPTH = 12
MAX_SCHEMA_PROPERTIES = 500
SUPPORTED_KEYS = {
    "$schema",
    "title",
    "description",
    "type",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "enum",
    "format",
    "minimum",
    "maximum",
    "minItems",
    "maxItems",
    "x-docparse-aliases",
    "x-docparse-kind",
    "x-docparse-table-title",
}


def validate_extraction_schema(schema: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(schema, ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_SCHEMA_BYTES:
        raise ValueError("Extraction schema exceeds 256 KB")
    if schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
        raise ValueError("Extraction schema root must be an object with properties")
    property_count = 0

    def visit(value: Any, depth: int) -> None:
        nonlocal property_count
        if depth > MAX_SCHEMA_DEPTH:
            raise ValueError("Extraction schema exceeds maximum depth 12")
        if isinstance(value, dict):
            unsupported = set(value) - SUPPORTED_KEYS
            if unsupported:
                names = ", ".join(sorted(unsupported))
                raise ValueError(f"Unsupported extraction schema keywords: {names}")
            if "$ref" in value:
                raise ValueError("Schema references are not supported")
            properties = value.get("properties")
            if isinstance(properties, dict):
                property_count += len(properties)
                if property_count > MAX_SCHEMA_PROPERTIES:
                    raise ValueError("Extraction schema exceeds 500 properties")
                for child in properties.values():
                    visit(child, depth + 1)
            if "items" in value:
                visit(value["items"], depth + 1)
        elif isinstance(value, list):
            for child in value:
                visit(child, depth + 1)

    visit(schema, 0)
    Draft202012Validator.check_schema(schema)
    return schema


def _normalize_label(value: str) -> str:
    return " ".join(re.findall(r"[\w]+", value.casefold(), flags=re.UNICODE))


def _aliases(name: str, definition: dict[str, Any]) -> set[str]:
    values = [name.replace("_", " "), definition.get("title", "")]
    raw = definition.get("x-docparse-aliases", [])
    if isinstance(raw, list):
        values.extend(str(item) for item in raw)
    return {_normalize_label(value) for value in values if value}


def _content_nodes(tree: DocumentTree) -> list[DocumentNode]:
    return [
        tree.nodes[node_id]
        for page in tree.pages
        for node_id in page.content_node_ids
        if tree.nodes[node_id].text
    ]


def _citation(node: DocumentNode) -> ValueCitation:
    citation = node.citations[0]
    return ValueCitation(
        citation_id=citation.id,
        node_id=node.id,
        page_number=citation.page_number,
        segment_page_number=citation.segment_page_number,
        bbox=citation.bbox,
        source_bbox=citation.source_bbox,
        grounding_scope=citation.grounding_scope,
        confidence=citation.confidence,
    )


def _table_rows(tree: DocumentTree, table_id: str) -> list[list[DocumentNode]]:
    table = tree.nodes[table_id]
    physical = [
        [tree.nodes[cell_id] for cell_id in tree.nodes[row_id].children_ids]
        for row_id in table.children_ids
    ]
    expanded: list[list[DocumentNode]] = []
    pending: dict[int, tuple[int, DocumentNode]] = {}

    def span(cell: DocumentNode, name: str, maximum: int) -> int:
        try:
            return max(1, min(maximum, int(cell.attributes.get(name, 1))))
        except (TypeError, ValueError):
            return 1

    for cells in physical:
        row: list[DocumentNode] = []
        column = 0
        for cell in cells:
            while column in pending:
                remaining, inherited = pending[column]
                row.append(inherited)
                if remaining <= 1:
                    del pending[column]
                else:
                    pending[column] = (remaining - 1, inherited)
                column += 1
            colspan = span(cell, "colspan", 200)
            rowspan = span(cell, "rowspan", len(physical))
            for _ in range(colspan):
                row.append(cell)
                if rowspan > 1:
                    pending[column] = (rowspan - 1, cell)
                column += 1
        while column in pending:
            remaining, inherited = pending[column]
            row.append(inherited)
            if remaining <= 1:
                del pending[column]
            else:
                pending[column] = (remaining - 1, inherited)
            column += 1
        expanded.append(row)
    return expanded


def _header_signature(tree: DocumentTree, table_id: str) -> tuple[str, ...]:
    rows = _table_rows(tree, table_id)
    if not rows:
        return ()
    return tuple(_normalize_label(cell.text or "") for cell in rows[0])


def _is_header_row(row: list[DocumentNode]) -> bool:
    if not row:
        return False
    if any(bool(cell.attributes.get("header")) for cell in row):
        return True
    texts = [(cell.text or "").strip() for cell in row]
    return bool(texts) and all(texts) and sum(bool(re.search(r"\d", text)) for text in texts) <= len(texts) // 3


def build_logical_tables(tree: DocumentTree) -> None:
    tables_by_page: list[list[DocumentNode]] = []
    for page in tree.pages:
        tables_by_page.append(
            [tree.nodes[node_id] for node_id in page.content_node_ids if tree.nodes[node_id].type == "Table"]
        )
    groups: list[list[DocumentNode]] = []
    for page_tables in tables_by_page:
        for table in page_tables:
            if not groups:
                groups.append([table])
                continue
            previous = groups[-1][-1]
            adjacent_pages = table.page_number == (previous.page_number or 0) + 1
            explicitly_continues = any(
                relation.type in {"continues", "same_table"}
                and relation.target_id == table.id
                for relation in previous.relationships
            )
            left_signature = _header_signature(tree, previous.id)
            right_signature = _header_signature(tree, table.id)
            same_columns = bool(left_signature) and len(left_signature) == len(right_signature)
            header_similarity = (
                SequenceMatcher(None, "|".join(left_signature), "|".join(right_signature)).ratio()
                if same_columns
                else 0.0
            )
            aligned = bool(
                previous.bbox
                and table.bbox
                and abs(previous.bbox.x0 - table.bbox.x0) <= 0.08
                and abs(previous.bbox.x1 - table.bbox.x1) <= 0.08
            )
            if adjacent_pages and aligned and (
                (explicitly_continues and same_columns) or header_similarity >= 0.8
            ):
                groups[-1].append(table)
            else:
                groups.append([table])

    logical_tables: list[LogicalTable] = []
    for group in groups:
        first_rows = _table_rows(tree, group[0].id)
        header_rows = 1 if first_rows and _is_header_row(first_rows[0]) else 0
        first_signature = _header_signature(tree, group[0].id)
        row_count = 0
        for index, table in enumerate(group):
            rows = _table_rows(tree, table.id)
            repeated = 0
            if index and header_rows and _header_signature(tree, table.id) == first_signature:
                repeated = 1
            table.attributes["repeated_header_rows"] = repeated
            row_count += max(0, len(rows) - repeated)
        logical_id = "lt-" + hashlib.sha256(
            f"{tree.source_sha256}:{group[0].id}".encode()
        ).hexdigest()[:16]
        for index, table in enumerate(group):
            table.attributes["logical_table_id"] = logical_id
            table.attributes["continuation_index"] = index
            if index and not any(
                relation.type == "same_table" and relation.target_id == table.id
                for relation in group[index - 1].relationships
            ):
                group[index - 1].relationships.append(
                    Relationship(type="same_table", target_id=table.id, confidence=0.9)
                )
        logical_tables.append(
            LogicalTable(
                id=logical_id,
                source_table_node_ids=[table.id for table in group],
                column_count=max((len(row) for row in first_rows), default=0),
                row_count=max(0, row_count - header_rows),
                header_rows=header_rows,
                confidence=0.9 if len(group) > 1 else 1.0,
                status="stitched" if len(group) > 1 else "physical",
            )
        )
    tree.logical_tables = logical_tables


def _coerce(value: str, expected: str) -> Any:
    value = value.strip()
    if expected == "string":
        return value
    if expected == "integer" and re.fullmatch(r"[-+]?\d+", value.replace(",", "")):
        return int(value.replace(",", ""))
    if expected == "number":
        numeric = re.sub(r"[^\d,.-]", "", value).replace(",", "")
        if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", numeric):
            return float(numeric)
    if expected == "boolean":
        normalized = value.casefold()
        if normalized in {"true", "yes", "checked", "1"}:
            return True
        if normalized in {"false", "no", "unchecked", "0"}:
            return False
    raise ValueError("Value cannot be conservatively coerced")


def _labeled_values(tree: DocumentTree) -> list[tuple[str, str, DocumentNode]]:
    values: list[tuple[str, str, DocumentNode]] = []
    for node in _content_nodes(tree):
        if node.form_field and node.form_field.label:
            values.append((node.form_field.label, node.form_field.value, node))
        match = re.match(r"^\s*([^:\n]{1,200})\s*:\s*(.{1,100000})\s*$", node.text or "")
        if match:
            values.append((match.group(1), match.group(2), node))
    for field in tree.grounded_fields:
        node = tree.nodes[field.source_node_ids[0]]
        values.append((field.path, field.normalized_value or field.raw_value, node))
    return values


def extract_schema_data(
    tree: DocumentTree,
    schema: dict[str, Any],
    *,
    subdocument_id: str | None = None,
) -> SchemaExtraction:
    schema = validate_extraction_schema(schema)
    labeled = _labeled_values(tree)
    data: dict[str, Any] = {}
    provenance: dict[str, ExtractionProvenance] = {}

    used_tables: set[str] = set()

    def logical_rows(logical: LogicalTable) -> list[list[DocumentNode]]:
        output: list[list[DocumentNode]] = []
        for table_id in logical.source_table_node_ids:
            table = tree.nodes[table_id]
            rows = _table_rows(tree, table_id)
            output.extend(rows[int(table.attributes.get("repeated_header_rows", 0)) :])
        return output

    def extract_table(
        name: str, definition: dict[str, Any], pointer: str
    ) -> list[dict[str, Any]]:
        item = definition.get("items")
        if not isinstance(item, dict) or item.get("type") != "object":
            return []
        columns = item.get("properties", {})
        if not isinstance(columns, dict) or not columns:
            return []
        candidates: list[tuple[float, LogicalTable, dict[str, int]]] = []
        title_aliases = _aliases(name, definition)
        table_title = definition.get("x-docparse-table-title")
        if isinstance(table_title, str):
            title_aliases.add(_normalize_label(table_title))
        for logical in tree.logical_tables:
            if logical.id in used_tables:
                continue
            rows = logical_rows(logical)
            if not rows:
                continue
            header = rows[0] if logical.header_rows else []
            mapping: dict[str, int] = {}
            for column_name, column in columns.items():
                aliases = _aliases(column_name, column)
                match = next(
                    (index for index, cell in enumerate(header) if _normalize_label(cell.text or "") in aliases),
                    None,
                )
                if match is not None:
                    mapping[column_name] = match
            score = len(mapping) / len(columns)
            table_text = " ".join(
                _normalize_label(tree.nodes[table_id].text or "")
                for table_id in logical.source_table_node_ids
            )
            if any(alias and alias in table_text for alias in title_aliases):
                score += 0.25
            if not header and logical.column_count == len(columns):
                mapping = {column_name: index for index, column_name in enumerate(columns)}
                score = 0.6
            candidates.append((score, logical, mapping))
        if not candidates:
            return []
        score, logical, mapping = max(candidates, key=lambda candidate: candidate[0])
        if score <= 0 and len(candidates) != 1:
            return []
        if not mapping and logical.column_count == len(columns):
            mapping = {column_name: index for index, column_name in enumerate(columns)}
        if not mapping:
            return []
        used_tables.add(logical.id)
        rows = logical_rows(logical)
        start = logical.header_rows
        extracted: list[dict[str, Any]] = []
        for source_row in rows[start:]:
            row_data: dict[str, Any] = {}
            row_index = len(extracted)
            for column_name, column_index in mapping.items():
                if column_index >= len(source_row):
                    continue
                cell = source_row[column_index]
                try:
                    value = _coerce(cell.text or "", str(columns[column_name].get("type")))
                except ValueError:
                    continue
                row_data[column_name] = value
                path = f"{pointer}/{row_index}/{column_name.replace('~', '~0').replace('/', '~1')}"
                citation = _citation(cell)
                citation.logical_table_id = logical.id
                citation.row_index = row_index
                citation.column_name = column_name
                provenance[path] = ExtractionProvenance(
                    path=path,
                    citations=[citation],
                    confidence=citation.confidence,
                    status="normalized" if value != (cell.text or "") else "literal",
                )
            if row_data:
                extracted.append(row_data)
        return extracted

    def extract_object(
        definition: dict[str, Any], target: dict[str, Any], pointer: str
    ) -> None:
        properties = definition.get("properties", {})
        for name, child in properties.items():
            child_pointer = f"{pointer}/{name.replace('~', '~0').replace('/', '~1')}"
            kind = child.get("type")
            if kind == "object":
                nested: dict[str, Any] = {}
                extract_object(child, nested, child_pointer)
                if nested:
                    target[name] = nested
                continue
            if kind == "array":
                if child.get("x-docparse-kind") == "table":
                    rows = extract_table(name, child, child_pointer)
                    if rows:
                        target[name] = rows
                else:
                    item_type = child.get("items", {}).get("type") if isinstance(child.get("items"), dict) else None
                    if item_type in {"string", "number", "integer", "boolean"}:
                        matches = [
                            (value, node)
                            for label, value, node in labeled
                            if _normalize_label(label) in _aliases(name, child)
                        ]
                        values = []
                        for index, (raw, node) in enumerate(matches):
                            try:
                                value = _coerce(raw, str(item_type))
                            except ValueError:
                                continue
                            values.append(value)
                            citation = _citation(node)
                            path = f"{child_pointer}/{index}"
                            provenance[path] = ExtractionProvenance(
                                path=path, citations=[citation], confidence=citation.confidence
                            )
                        if values:
                            target[name] = values
                continue
            aliases = _aliases(name, child)
            match = next(
                (
                    (value, node)
                    for label, value, node in labeled
                    if _normalize_label(label) in aliases
                ),
                None,
            )
            if match is None:
                continue
            raw, node = match
            try:
                value = _coerce(raw, str(kind))
            except ValueError:
                continue
            target[name] = value
            citation = _citation(node)
            provenance[child_pointer] = ExtractionProvenance(
                path=child_pointer,
                citations=[citation],
                confidence=citation.confidence,
                status="normalized" if value != raw else "literal",
            )

    extract_object(schema, data, "")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(error.message for error in validator.iter_errors(data))
    digest = hashlib.sha256(
        json.dumps(schema, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return SchemaExtraction(
        schema_name=str(schema.get("title") or "Custom extraction"),
        schema_sha256=digest,
        document_id=tree.document_id,
        subdocument_id=subdocument_id,
        status="complete" if not errors else "partial",
        data=data,
        provenance=provenance,
        validation_errors=errors,
    )


def build_table_exports(
    extraction: SchemaExtraction, schema: dict[str, Any]
) -> dict[str, bytes]:
    exports: dict[str, bytes] = {}

    def walk(definition: dict[str, Any], value: Any, pointer: str) -> None:
        if definition.get("type") == "object" and isinstance(value, dict):
            for name, child in definition.get("properties", {}).items():
                if name in value:
                    walk(child, value[name], f"{pointer}/{name.replace('~', '~0').replace('/', '~1')}")
            return
        if definition.get("type") != "array" or definition.get("x-docparse-kind") != "table":
            return
        if not isinstance(value, list):
            return
        table_id = next(
            (
                citation.logical_table_id
                for path, entry in extraction.provenance.items()
                if path.startswith(pointer + "/")
                for citation in entry.citations
                if citation.logical_table_id
            ),
            None,
        )
        if table_id is None:
            return
        jsonl = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in value)
        exports[f"tables/{table_id}.jsonl"] = jsonl.encode("utf-8")
        columns = list(definition.get("items", {}).get("properties", {}))
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in value:
            safe = {
                key: "'" + cell
                if isinstance(cell, str) and cell.lstrip().startswith(("=", "+", "-", "@"))
                else cell
                for key, cell in row.items()
            }
            writer.writerow(safe)
        exports[f"tables/{table_id}.csv"] = output.getvalue().encode("utf-8-sig")

    walk(schema, extraction.data, "")
    return exports


def extraction_evidence(tree: DocumentTree) -> list[dict[str, Any]]:
    return [
        {
            "id": node.id,
            "page": node.page_number,
            "type": node.type,
            "role": node.semantic_role,
            "text": (node.text or "")[:2_000],
        }
        for node in _content_nodes(tree)[:10_000]
    ]


def schema_scalar_paths(schema: dict[str, Any]) -> list[str]:
    paths: list[str] = []

    def walk(definition: dict[str, Any], pointer: str) -> None:
        if definition.get("type") == "object":
            for name, child in definition.get("properties", {}).items():
                escaped = name.replace("~", "~0").replace("/", "~1")
                walk(child, f"{pointer}/{escaped}")
        elif definition.get("type") in {"string", "number", "integer", "boolean"}:
            paths.append(pointer)

    walk(schema, "")
    return paths


def _definition_at_pointer(
    schema: dict[str, Any], pointer: str
) -> dict[str, Any] | None:
    current = schema
    for token in pointer.strip("/").split("/") if pointer.strip("/") else []:
        token = token.replace("~1", "/").replace("~0", "~")
        if token.isdigit() or current.get("type") != "object":
            return None
        properties = current.get("properties", {})
        if token not in properties:
            return None
        current = properties[token]
    return current


def _set_pointer(data: dict[str, Any], pointer: str, value: Any) -> None:
    tokens = [
        token.replace("~1", "/").replace("~0", "~")
        for token in pointer.strip("/").split("/")
        if token
    ]
    current = data
    for token in tokens[:-1]:
        child = current.get(token)
        if not isinstance(child, dict):
            child = {}
            current[token] = child
        current = child
    if tokens:
        current[tokens[-1]] = value


def apply_extraction_decisions(
    tree: DocumentTree,
    schema: dict[str, Any],
    extraction: SchemaExtraction,
    decisions: ExtractionDecisions,
    *,
    method: str,
) -> None:
    for selection in decisions.selections:
        definition = _definition_at_pointer(schema, selection.path)
        if definition is None or definition.get("type") not in {
            "string",
            "number",
            "integer",
            "boolean",
        }:
            continue
        nodes = [tree.nodes.get(node_id) for node_id in selection.source_node_ids]
        if any(node is None or not node.citations for node in nodes):
            continue
        source_nodes = [node for node in nodes if node is not None]
        evidence = "\n".join(node.text or "" for node in source_nodes)
        raw = selection.literal_value.strip()
        literal_match = " ".join(raw.casefold().split()) in " ".join(
            evidence.casefold().split()
        )
        try:
            value = _coerce(raw, str(definition["type"]))
        except ValueError:
            continue
        if not literal_match:
            candidates = re.findall(r"[$€£]?\s*[-+]?\d[\d,.]*", evidence)
            supported = False
            for candidate in candidates:
                try:
                    supported = _coerce(candidate, str(definition["type"])) == value
                except ValueError:
                    continue
                if supported:
                    break
            if not supported:
                continue
        _set_pointer(extraction.data, selection.path, value)
        citations = [_citation(node) for node in source_nodes]
        extraction.provenance[selection.path] = ExtractionProvenance(
            path=selection.path,
            citations=citations,
            confidence=min(selection.confidence, min(item.confidence for item in citations)),
            status="verified",
            method=method,
        )
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    extraction.validation_errors = sorted(
        error.message for error in validator.iter_errors(extraction.data)
    )
    extraction.status = "complete" if not extraction.validation_errors else "partial"
