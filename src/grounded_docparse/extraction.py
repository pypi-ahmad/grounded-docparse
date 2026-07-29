from __future__ import annotations

import json
import re
from collections.abc import Callable
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from typing import Any

from .config import ParserConfig
from .gateways import OpenAIDocumentGateway
from .models import (
    ExtractedField,
    ExtractionResult,
    ParseResult,
    RunUsage,
    SchemaProposal,
)

SUPPORTED_TYPES = {"object", "array", "string", "number", "integer", "boolean", "null"}
UNSUPPORTED_KEYWORDS = {
    "allOf",
    "not",
    "dependentRequired",
    "dependentSchemas",
    "if",
    "then",
    "else",
    "patternProperties",
    "pattern",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "multipleOf",
    "minItems",
    "maxItems",
}
NUMBER_BODY = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?"
NUMERIC_LITERAL_PATTERN = re.compile(
    rf"(?<![\w.,])(?P<accounting>\()?[ \t]*(?P<sign_before>[+-])?[ \t]*"
    rf"(?P<currency>[$€£])?[ \t]*(?P<sign_after>[+-])?[ \t]*"
    rf"(?P<number>{NUMBER_BODY})[ \t]*(?(accounting)\))(?!\w|[.,]\d)"
)


def validate_extraction_schema(schema: dict[str, Any]) -> None:
    """Validate the strict, fail-closed JSON Schema subset used by Extract."""

    _validate_schema_node(schema, path="$")
    if schema.get("type") != "object":
        raise ValueError("$: extraction schema must have type object")


def _validate_schema_node(schema: Any, *, path: str) -> None:
    if not isinstance(schema, dict):
        raise ValueError(  # noqa: TRY004 - schema validation has one error contract
            f"{path}: schema node must be an object"
        )
    unsupported = UNSUPPORTED_KEYWORDS.intersection(schema)
    if unsupported:
        keyword = min(unsupported)
        raise ValueError(f"{path}: unsupported JSON Schema keyword {keyword}")

    declared = schema.get("type")
    types = [declared] if isinstance(declared, str) else declared
    if (
        not isinstance(types, list)
        or not types
        or not all(isinstance(item, str) and item in SUPPORTED_TYPES for item in types)
    ):
        raise ValueError(f"{path}: type must use the supported JSON Schema subset")

    non_null = [item for item in types if item != "null"]
    if path != "$" and "null" not in types:
        raise ValueError(f"{path}: extraction fields must be nullable")
    if len(non_null) != 1:
        raise ValueError(f"{path}: type must contain exactly one non-null type")

    kind = non_null[0]
    if kind == "object":
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            raise ValueError(f"{path}: object schemas require properties")
        if schema.get("additionalProperties") is not False:
            raise ValueError(f"{path}: additionalProperties must be false")
        required = schema.get("required")
        if not isinstance(required, list) or set(required) != set(properties):
            raise ValueError(f"{path}: every property must be required")
        for name, child in properties.items():
            _validate_schema_node(child, path=f"{path}.{name}")
    elif kind == "array":
        items = schema.get("items")
        if not isinstance(items, dict):
            raise ValueError(f"{path}: array schemas require items")
        _validate_schema_node(items, path=f"{path}[]")


class DocumentExtractor:
    def __init__(
        self,
        config: ParserConfig | None = None,
        *,
        gateway_factory: Callable[[ParserConfig], object] = OpenAIDocumentGateway,
    ) -> None:
        self.config = config or ParserConfig.from_env()
        self.gateway = gateway_factory(self.config)

    def propose_schema(
        self,
        instruction: str,
        parse_result: ParseResult,
    ) -> SchemaProposal:
        instruction = instruction.strip()
        if not instruction:
            raise ValueError("extraction instruction is required")
        payload = _extraction_payload(json.loads(parse_result.json))
        raw = self.gateway.propose_schema(instruction, payload)
        schema_json = (
            raw.get("schema_json") if isinstance(raw, dict) else raw.schema_text
        )
        try:
            schema = json.loads(schema_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("schema architect returned invalid JSON") from exc
        validate_extraction_schema(schema)
        return SchemaProposal(
            instruction=instruction,
            json_schema=schema,
            usage=_usage(self.gateway).model_copy(deep=True),
        )

    def extract(
        self,
        parse_result: ParseResult,
        schema: dict[str, Any],
        *,
        allow_inferred: bool = False,
    ) -> ExtractionResult:
        validate_extraction_schema(schema)
        parse_payload = _extraction_payload(json.loads(parse_result.json))
        model_context = _model_extraction_context(parse_payload)
        draft = self.gateway.extract_document(
            model_context,
            schema,
            repair=False,
            issues=None,
        )
        issues, evidence = _validate_and_resolve(draft, schema, parse_payload)
        if issues:
            draft = self.gateway.extract_document(
                model_context,
                schema,
                repair=True,
                issues=issues,
            )
            issues, evidence = _validate_and_resolve(draft, schema, parse_payload)

        data = deepcopy(draft.get("data", {}))
        warnings: list[str] = []
        if issues and allow_inferred:
            inferred = _resolve_inferred_evidence(data, draft, parse_payload)
            evidence.update(inferred)
            inferred_pointers = set(inferred)
            issues = [
                issue
                for issue in issues
                if not (
                    _issue_pointer(issue) in inferred_pointers
                    and any(
                        marker in issue
                        for marker in (
                            "missing evidence",
                            "cited evidence does not contain",
                            "unknown block",
                            "unknown atom",
                        )
                    )
                )
            ]
        if issues:
            for issue in issues:
                pointer = _issue_pointer(issue)
                if pointer is not None:
                    _set_pointer(data, pointer, None)
                warnings.append(issue)
            _validate_instance(data, schema, path="$")
            _, evidence = _validate_and_resolve(
                {"data": data, "evidence": draft.get("evidence", [])},
                schema,
                parse_payload,
                require_all=False,
            )

        fields = _extracted_fields(data, evidence, parse_payload)

        usage = _usage(self.gateway).model_copy(deep=True)
        trace = list(getattr(self.gateway, "trace", []))
        payload = {
            "schema_version": "1.1.0",
            "schema": schema,
            "data": data,
            "evidence": evidence,
            "fields": {
                name: field.model_dump(mode="json") for name, field in fields.items()
            },
            "warnings": warnings,
            "metadata": {
                "usage": usage.model_dump(mode="json"),
                "trace": [item.model_dump(mode="json") for item in trace],
            },
        }
        return ExtractionResult(
            data=data,
            evidence=evidence,
            json=json.dumps(payload, ensure_ascii=False, indent=2),
            warnings=warnings,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            usage=usage,
            trace=trace,
            fields=fields,
        )


def _usage(gateway: object) -> RunUsage:
    usage = getattr(gateway, "usage", None)
    return usage if isinstance(usage, RunUsage) else RunUsage()


def _extraction_payload(parse_payload: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(parse_payload)
    refined_markdown = payload.get("markdown", "")
    payload["markdown"] = payload.get("base_markdown", refined_markdown)
    payload["refined_markdown"] = refined_markdown
    active_block_ids: set[str] = set()
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        metadata.pop("warnings", None)
        metadata.pop("trace", None)
    for page in payload.get("document", {}).get("pages", []):
        page["blocks"] = [
            block
            for block in page.get("blocks", [])
            if block.get("rendered") is not False and block.get("status") != "rejected"
        ]
        for block in page["blocks"]:
            active_block_ids.add(block["id"])
            block.pop("correction_lineage", None)
            block.pop("reason", None)
            block.pop("verification_reason", None)
        page.pop("warnings", None)
    if isinstance(payload.get("elements"), list):
        payload["elements"] = [
            element
            for element in payload["elements"]
            if element.get("id") in active_block_ids
        ]
    return payload


def _model_extraction_context(parse_payload: dict[str, Any]) -> dict[str, Any]:
    """Build the compact, identifier-rich context sent to Luna."""

    layout = []
    for page in parse_payload.get("document", {}).get("pages", []):
        page_number = page.get("number")
        for block in page.get("blocks", []):
            layout.append(
                {
                    "id": block.get("id"),
                    "type": block.get("type"),
                    "page": page_number,
                    "order": block.get("reading_order"),
                    "text": block.get("text", ""),
                    "atoms": [
                        {
                            "id": atom.get("id"),
                            "text": atom.get("text", ""),
                        }
                        for atom in block.get("atoms", [])
                    ],
                }
            )
    return {
        "document_markdown": parse_payload.get(
            "refined_markdown", parse_payload.get("markdown", "")
        ),
        "layout_tree": layout,
    }


def _validate_and_resolve(
    draft: dict[str, Any],
    schema: dict[str, Any],
    parse_payload: dict[str, Any],
    *,
    require_all: bool = True,
) -> tuple[list[str], dict[str, list[dict]]]:
    data = draft.get("data")
    issues: list[str] = []
    try:
        _validate_instance(data, schema, path="$")
    except ValueError as exc:
        issues.append(str(exc))
        return issues, {}

    blocks: dict[str, dict] = {}
    atoms: dict[str, tuple[str, dict]] = {}
    for page in parse_payload.get("document", {}).get("pages", []):
        for block in page.get("blocks", []):
            if block.get("rendered") is False or block.get("status") == "rejected":
                continue
            blocks[block["id"]] = block
            for atom in block.get("atoms", []):
                atoms[atom["id"]] = (block["id"], atom)

    resolved: dict[str, list[dict]] = {}
    markdown = parse_payload.get("markdown", "")
    for item in draft.get("evidence", []):
        raw_pointer = item.get("pointer")
        pointer = _canonical_evidence_pointer(data, raw_pointer)
        if pointer is None:
            issues.append(f"invalid evidence pointer {raw_pointer!r}")
            continue
        citations: list[dict] = []
        atom_ids = item.get("atom_ids", [])
        block_ids = item.get("block_ids", [])
        for atom_id in atom_ids:
            record = atoms.get(atom_id)
            if record is None:
                issues.append(f"{pointer}: unknown atom {atom_id}")
                continue
            block_id, atom = record
            source = atom["source"]
            citations.append(
                {
                    "block_id": block_id,
                    "atom_id": atom_id,
                    "page": source["page"],
                    "span": source["span"],
                    "bbox": source["bbox"],
                }
            )
        if not atom_ids:
            for block_id in block_ids:
                block = blocks.get(block_id)
                if block is None:
                    issues.append(f"{pointer}: unknown block {block_id}")
                    continue
                source = block["source"]
                citations.append(
                    {
                        "block_id": block_id,
                        "atom_id": None,
                        "page": source["page"],
                        "span": source["span"],
                        "bbox": source["bbox"],
                    }
                )
        value = _pointer_value(data, pointer)
        if citations and not _citations_contain_value(value, citations, markdown):
            issues.append(f"{pointer}: cited evidence does not contain extracted value")
            continue
        if citations:
            resolved[pointer] = citations

    if require_all:
        for pointer, value in _non_null_leaves(data):
            if pointer not in resolved:
                issues.append(f"{pointer}: missing evidence")
    return issues, resolved


def _active_blocks(parse_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        block["id"]: block
        for page in parse_payload.get("document", {}).get("pages", [])
        for block in page.get("blocks", [])
        if block.get("rendered") is not False and block.get("status") != "rejected"
    }


def _resolve_inferred_evidence(
    data: dict[str, Any],
    draft: dict[str, Any],
    parse_payload: dict[str, Any],
) -> dict[str, list[dict]]:
    blocks = _active_blocks(parse_payload)
    requested: dict[str, list[str]] = {}
    for item in draft.get("evidence", []):
        pointer = _canonical_evidence_pointer(data, item.get("pointer"))
        if pointer is not None:
            requested[pointer] = [
                block_id
                for block_id in item.get("block_ids", [])
                if block_id in blocks
            ]

    inferred: dict[str, list[dict]] = {}
    candidates = [
        block for block in blocks.values() if str(block.get("text", "")).strip()
    ]
    for pointer, value in _non_null_leaves(data):
        block = next(
            (blocks[block_id] for block_id in requested.get(pointer, [])),
            None,
        )
        if block is None and candidates:
            needle = str(value).casefold()
            block = max(
                candidates,
                key=lambda item: SequenceMatcher(
                    None,
                    needle,
                    str(item.get("text", "")).casefold()[:1_000],
                ).ratio(),
            )
        if block is None:
            continue
        source = block["source"]
        inferred[pointer] = [
            {
                "block_id": block["id"],
                "atom_id": None,
                "page": source["page"],
                "span": source["span"],
                "bbox": source["bbox"],
                "confidence": "inferred",
            }
        ]
    return inferred


def _bbox_tuple(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, dict):
        return None
    coordinates = tuple(value.get(name) for name in ("x0", "y0", "x1", "y1"))
    if not all(isinstance(item, (int, float)) for item in coordinates):
        return None
    return coordinates  # type: ignore[return-value]


def _extracted_fields(
    data: dict[str, Any],
    evidence: dict[str, list[dict]],
    parse_payload: dict[str, Any],
) -> dict[str, ExtractedField]:
    blocks = _active_blocks(parse_payload)
    fields: dict[str, ExtractedField] = {}
    for name, value in data.items():
        escaped = name.replace("~", "~0").replace("/", "~1")
        field_pointer = f"/{escaped}"
        citations = list(evidence.get(field_pointer, []))
        if not citations:
            citations = [
                citation
                for pointer, pointer_citations in evidence.items()
                if pointer.startswith(f"{field_pointer}/")
                for citation in pointer_citations
            ]
        if value is None or not citations:
            fields[name] = ExtractedField(value=value, confidence="not_found")
            continue
        citation = citations[0]
        block = blocks.get(citation.get("block_id"), {})
        source_text = str(block.get("text", ""))
        confidence = citation.get("confidence")
        if confidence != "inferred":
            confidence = (
                "high"
                if str(value).casefold() in source_text.casefold()
                else "medium"
            )
        fields[name] = ExtractedField(
            value=value,
            page=citation.get("page"),
            bbox=_bbox_tuple(citation.get("bbox")),
            confidence=confidence,
            element_id=citation.get("block_id"),
            source_text=source_text,
        )
    return fields


def _canonical_evidence_pointer(data: Any, pointer: Any) -> str | None:
    if not isinstance(pointer, str):
        return None
    if _pointer_exists(data, pointer):
        return pointer
    if pointer.startswith("/data/"):
        relative = pointer.removeprefix("/data")
        if _pointer_exists(data, relative):
            return relative
    return None


def _pointer_value(value: Any, pointer: str) -> Any:
    current = value
    for part in _pointer_parts(pointer):
        current = current[int(part)] if isinstance(current, list) else current[part]
    return current


def _citations_contain_value(
    value: Any,
    citations: list[dict],
    markdown: str,
) -> bool:
    if isinstance(value, (dict, list)):
        return True
    cited_text: list[str] = []
    for citation in citations:
        span = citation.get("span")
        if not isinstance(span, dict):
            continue
        start = span.get("start")
        end = span.get("end")
        if (
            isinstance(start, int)
            and isinstance(end, int)
            and 0 <= start <= end <= len(markdown)
        ):
            cited_text.append(markdown[start:end])
    if isinstance(value, bool):
        return any(
            _evidence_contains_boolean(evidence, value) for evidence in cited_text
        )
    if isinstance(value, (int, float)):
        try:
            expected_number = Decimal(str(value))
        except InvalidOperation:
            return False
        for evidence in cited_text:
            for match in NUMERIC_LITERAL_PATTERN.finditer(evidence.replace(r"\|", "|")):
                sign_before = match.group("sign_before")
                sign_after = match.group("sign_after")
                explicit_signs = [sign for sign in (sign_before, sign_after) if sign]
                if len(explicit_signs) > 1:
                    continue
                if match.group("accounting") and explicit_signs:
                    continue
                literal = match.group("number").replace(",", "")
                try:
                    parsed = Decimal(literal)
                    if match.group("accounting") or explicit_signs == ["-"]:
                        parsed = -parsed
                    if parsed == expected_number:
                        return True
                except InvalidOperation:
                    continue
        return False
    expected = " ".join(str(value).split()).casefold()
    return bool(
        expected
        and any(
            expected in " ".join(evidence.split()).replace(r"\|", "|").casefold()
            for evidence in cited_text
        )
    )


def _strip_markdown_emphasis(value: str) -> str:
    value = value.strip()
    while True:
        for marker in ("**", "__", "*", "_"):
            if (
                value.startswith(marker)
                and value.endswith(marker)
                and len(value) > 2 * len(marker)
            ):
                value = value[len(marker) : -len(marker)].strip()
                break
        else:
            return value


def _boolean_token(value: str) -> tuple[str, str] | None:
    normalized = _strip_markdown_emphasis(value)
    match = re.fullmatch(
        r"(?P<value>yes|no)(?P<punct>[.!?,;:]?)", normalized, re.IGNORECASE
    )
    if match is None:
        return None
    return match.group("value").casefold(), match.group("punct")


def _markdown_table_cells(line: str) -> list[str] | None:
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return None
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for character in stripped[1:-1]:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            current.append(character)
            escaped = True
        elif character == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(character)
    cells.append("".join(current).strip())
    return cells


def _separator_row(cells: list[str] | None) -> bool:
    return bool(cells) and all(
        re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) is not None for cell in cells
    )


def _evidence_contains_boolean(evidence: str, value: bool) -> bool:
    normalized = evidence
    folded = normalized.replace(r"\|", "|").casefold()
    if re.search(rf"\b{str(value).casefold()}\b", folded):
        return True
    if value and re.search(r"\[(?:x|✓)\]", folded):
        return True
    if not value and re.search(r"\[\s\]", folded):
        return True

    expected = "yes" if value else "no"
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    table_rows = [_markdown_table_cells(line) for line in lines]
    for index, cells in enumerate(table_rows):
        if cells is None or _separator_row(cells):
            continue
        next_cells = table_rows[index + 1] if index + 1 < len(table_rows) else None
        if _separator_row(next_cells):
            continue
        for cell_index, cell in enumerate(cells):
            token = _boolean_token(cell)
            if (
                cell_index > 0
                and token is not None
                and token[0] == expected
                and any(previous.strip() for previous in cells[:cell_index])
            ):
                return True

    for line in lines:
        if _markdown_table_cells(line) is not None:
            continue
        label, separator, candidate = (
            line.replace("**", "").replace("__", "").partition(":")
        )
        if separator and label.strip():
            token = _boolean_token(candidate)
            if token is not None and token[0] == expected:
                return True
        token = _boolean_token(line)
        if token is not None and token[0] == expected and token != ("no", "."):
            return True
    return False


def _validate_instance(value: Any, schema: dict[str, Any], *, path: str) -> None:
    declared = schema["type"]
    types = [declared] if isinstance(declared, str) else declared
    if value is None:
        if "null" not in types:
            raise ValueError(f"{path}: null is not allowed")
        return
    kind = next(item for item in types if item != "null")
    valid = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "number": lambda item: (
            isinstance(item, (int, float)) and not isinstance(item, bool)
        ),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
    }[kind](value)
    if not valid:
        raise ValueError(f"{path}: expected {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}: value is not in enum")
    if kind == "object":
        properties = schema["properties"]
        if set(value) != set(properties):
            raise ValueError(f"{path}: object keys do not match schema")
        for name, child in properties.items():
            _validate_instance(value[name], child, path=f"{path}.{name}")
    elif kind == "array":
        for index, item in enumerate(value):
            _validate_instance(item, schema["items"], path=f"{path}[{index}]")


def _non_null_leaves(value: Any, pointer: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            escaped = key.replace("~", "~0").replace("/", "~1")
            yield from _non_null_leaves(child, f"{pointer}/{escaped}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _non_null_leaves(child, f"{pointer}/{index}")
    elif value is not None:
        yield pointer or "/", value


def _pointer_parts(pointer: str) -> list[str]:
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise ValueError("JSON Pointer must start with /")
    return [
        part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")
    ]


def _pointer_exists(value: Any, pointer: str) -> bool:
    try:
        current = value
        for part in _pointer_parts(pointer):
            current = current[int(part)] if isinstance(current, list) else current[part]
        return True
    except (KeyError, IndexError, TypeError, ValueError):
        return False


def _set_pointer(value: Any, pointer: str, replacement: Any) -> None:
    parts = _pointer_parts(pointer)
    if not parts:
        raise ValueError("cannot replace the extraction root")
    current = value
    for part in parts[:-1]:
        current = current[int(part)] if isinstance(current, list) else current[part]
    last = parts[-1]
    if isinstance(current, list):
        current[int(last)] = replacement
    else:
        current[last] = replacement


def _issue_pointer(issue: str) -> str | None:
    prefix, separator, _detail = issue.partition(":")
    return prefix if separator and prefix.startswith("/") else None
