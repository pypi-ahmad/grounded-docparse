from __future__ import annotations

import json
import re
from collections.abc import Callable
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any

from .config import ParserConfig
from .gateways import OpenAIDocumentGateway
from .models import ExtractionResult, ParseResult, RunUsage, SchemaProposal

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
    rf"(?P<number>{NUMBER_BODY})[ \t]*(?(accounting)\))(?![\w.,])"
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
    if not isinstance(types, list) or not types or not all(
        isinstance(item, str) and item in SUPPORTED_TYPES for item in types
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
        schema_json = raw.get("schema_json") if isinstance(raw, dict) else raw.schema_text
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
    ) -> ExtractionResult:
        validate_extraction_schema(schema)
        parse_payload = _extraction_payload(json.loads(parse_result.json))
        draft = self.gateway.extract_document(
            parse_payload,
            schema,
            use_terra=False,
            issues=None,
        )
        issues, evidence = _validate_and_resolve(draft, schema, parse_payload)
        if issues:
            draft = self.gateway.extract_document(
                parse_payload,
                schema,
                use_terra=True,
                issues=issues,
            )
            issues, evidence = _validate_and_resolve(draft, schema, parse_payload)

        data = deepcopy(draft.get("data", {}))
        warnings: list[str] = []
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

        usage = _usage(self.gateway).model_copy(deep=True)
        trace = list(getattr(self.gateway, "trace", []))
        payload = {
            "schema_version": "1.0.0",
            "schema": schema,
            "data": data,
            "evidence": evidence,
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
        )


def _usage(gateway: object) -> RunUsage:
    usage = getattr(gateway, "usage", None)
    return usage if isinstance(usage, RunUsage) else RunUsage()


def _extraction_payload(parse_payload: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(parse_payload)
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        metadata.pop("warnings", None)
        metadata.pop("trace", None)
    for page in payload.get("document", {}).get("pages", []):
        page["blocks"] = [
            block
            for block in page.get("blocks", [])
            if block.get("rendered") is not False
            and block.get("status") != "rejected"
        ]
        for block in page["blocks"]:
            block.pop("correction_lineage", None)
            block.pop("reason", None)
            block.pop("verification_reason", None)
        page.pop("specialist_audit", None)
        page.pop("warnings", None)
    return payload


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
            if (
                block.get("rendered") is False
                or block.get("status") == "rejected"
            ):
                continue
            blocks[block["id"]] = block
            for atom in block.get("atoms", []):
                atoms[atom["id"]] = (block["id"], atom)

    resolved: dict[str, list[dict]] = {}
    markdown = parse_payload.get("markdown", "")
    for item in draft.get("evidence", []):
        pointer = item.get("pointer")
        if not isinstance(pointer, str) or not _pointer_exists(data, pointer):
            issues.append(f"invalid evidence pointer {pointer!r}")
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
    grounded = " ".join(" ".join(cited_text).split()).replace(r"\|", "|")
    folded = grounded.casefold()
    if isinstance(value, bool):
        literals = ("true", "yes") if value else ("false", "no")
        literal = any(re.search(rf"\b{item}\b", folded) for item in literals)
        checkbox = (
            re.search(r"\[(?:x|✓)\]", folded)
            if value
            else re.search(r"\[\s\]", folded)
        )
        return literal or checkbox is not None
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
    return bool(expected and expected in folded)


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
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
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
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


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
