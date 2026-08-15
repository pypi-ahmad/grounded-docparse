from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from .config import LUNA_MODEL, LUNA_REASONING_EFFORT, ParserConfig
from .models import AgentTraceEvent, RunUsage, StoredSchema
from .native import (
    CharacterInterval,
    NativeExtractedValue,
    NativeExtractionEvidence,
    NativeExtractionResult,
    NativeParseResult,
)
from .schema_store import compile_json_schema

_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_INTEGER = re.compile(r"^[+-]?\d+$")


@dataclass(frozen=True, slots=True)
class ExtractionFieldSpec:
    extraction_class: str
    pointer_template: str
    value_type: str
    description: str
    enum: tuple[Any, ...] | None
    array_pointer: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractionGroupSpec:
    fields: tuple[ExtractionFieldSpec, ...]
    array_pointer: str | None = None
    item_schema: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class TranslatedExtractionSchema:
    source_schema: dict[str, Any]
    output_schema: dict[str, Any]
    groups: tuple[ExtractionGroupSpec, ...]
    fields_by_class: dict[str, ExtractionFieldSpec]
    prompt: str


def _types(schema: dict[str, Any]) -> list[str]:
    declared = schema["type"]
    return [declared] if isinstance(declared, str) else list(declared)


def _kind(schema: dict[str, Any]) -> str:
    return next(value for value in _types(schema) if value != "null")


def _escape_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _join_pointer(pointer: str, name: str) -> str:
    return f"{pointer}/{_escape_pointer(name)}"


def _collect_extraction_groups(
    compiled: dict[str, Any],
) -> list[ExtractionGroupSpec]:
    groups: list[ExtractionGroupSpec] = []
    counter = 0

    def field_spec(
        node: dict[str, Any], pointer: str, *, array_pointer: str | None = None
    ) -> ExtractionFieldSpec:
        nonlocal counter
        counter += 1
        return ExtractionFieldSpec(
            extraction_class=f"field_{counter:04d}",
            pointer_template=pointer,
            value_type=_kind(node),
            description=str(node.get("description", "")).strip(),
            enum=tuple(node["enum"]) if isinstance(node.get("enum"), list) else None,
            array_pointer=array_pointer,
        )

    def object_fields(
        node: dict[str, Any], pointer: str, *, array_pointer: str
    ) -> tuple[ExtractionFieldSpec, ...]:
        values: list[ExtractionFieldSpec] = []
        for name, child in node["properties"].items():
            child_pointer = _join_pointer(pointer, name)
            child_kind = _kind(child)
            if child_kind == "array":
                raise ValueError(
                    f"{child_pointer}: nested arrays are not supported by native extraction"
                )
            if child_kind == "object":
                values.extend(
                    object_fields(
                        child,
                        child_pointer,
                        array_pointer=array_pointer,
                    )
                )
            else:
                values.append(
                    field_spec(child, child_pointer, array_pointer=array_pointer)
                )
        return tuple(values)

    def walk(node: dict[str, Any], pointer: str) -> None:
        node_kind = _kind(node)
        if node_kind == "object":
            for name, child in node["properties"].items():
                child_pointer = _join_pointer(pointer, name)
                child_kind = _kind(child)
                if child_kind == "object":
                    walk(child, child_pointer)
                elif child_kind == "array":
                    item = child["items"]
                    item_kind = _kind(item)
                    if item_kind == "array":
                        raise ValueError(
                            f"{child_pointer}: nested arrays are not supported by native extraction"
                        )
                    if item_kind == "object":
                        fields = object_fields(
                            item,
                            f"{child_pointer}/*",
                            array_pointer=child_pointer,
                        )
                    else:
                        fields = (
                            field_spec(
                                item,
                                f"{child_pointer}/*",
                                array_pointer=child_pointer,
                            ),
                        )
                    groups.append(
                        ExtractionGroupSpec(
                            fields=fields,
                            array_pointer=child_pointer,
                            item_schema=item,
                        )
                    )
                else:
                    groups.append(
                        ExtractionGroupSpec(fields=(field_spec(child, child_pointer),))
                    )
        else:
            raise ValueError("native extraction schema must have an object root")

    walk(compiled, "")
    if not groups:
        raise ValueError("native extraction schema has no extractable fields")
    return groups


def _build_extraction_contract(
    groups: list[ExtractionGroupSpec],
) -> tuple[dict[str, Any], dict[str, ExtractionFieldSpec], str]:
    item_schemas = []
    prompt_lines = [
        "Extract only literal text that appears verbatim in the source document.",
        "Never infer, normalize, calculate, paraphrase, or copy values from instructions.",
        "Use the extraction classes below exactly as named.",
    ]
    fields_by_class: dict[str, ExtractionFieldSpec] = {}
    for group in groups:
        properties = {}
        required = []
        for field in group.fields:
            fields_by_class[field.extraction_class] = field
            properties[field.extraction_class] = {"type": "string"}
            required.append(field.extraction_class)
            details = f" -> {field.pointer_template} ({field.value_type})"
            if field.description:
                details += f": {field.description}"
            prompt_lines.append(field.extraction_class + details)
        item_schemas.append(
            {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            }
        )
    output_schema = {
        "type": "object",
        "properties": {
            "extractions": {
                "type": "array",
                "items": (
                    item_schemas[0]
                    if len(item_schemas) == 1
                    else {"anyOf": item_schemas}
                ),
            }
        },
        "required": ["extractions"],
        "additionalProperties": False,
    }
    return output_schema, fields_by_class, "\n".join(prompt_lines)


def translate_stored_schema(schema: StoredSchema) -> TranslatedExtractionSchema:
    compiled = compile_json_schema(schema)
    groups = _collect_extraction_groups(compiled)
    output_schema, fields_by_class, prompt = _build_extraction_contract(groups)
    return TranslatedExtractionSchema(
        source_schema=compiled,
        output_schema=output_schema,
        groups=tuple(groups),
        fields_by_class=fields_by_class,
        prompt=prompt,
    )


def _schema_fingerprint(schema: StoredSchema) -> str:
    canonical = json.dumps(
        schema.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _coerce(value: str, field: ExtractionFieldSpec) -> Any:
    kind = field.value_type
    if kind == "string":
        converted: Any = value
    elif kind == "integer":
        if not _INTEGER.fullmatch(value):
            raise ValueError("is not an exact integer literal")
        converted = int(value)
    elif kind == "number":
        if not _NUMBER.fullmatch(value):
            raise ValueError("is not an exact number literal")
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("is not an exact number literal") from exc
        if not number.is_finite():
            raise ValueError("is not a finite number literal")
        converted = int(number) if number == number.to_integral() else float(number)
    elif kind == "boolean":
        literal = value.casefold()
        if literal not in {"true", "false"}:
            raise ValueError("is not the literal true or false")
        converted = literal == "true"
    else:
        raise ValueError(f"unsupported extracted value type {kind}")
    if field.enum is not None and converted not in field.enum:
        raise ValueError("is outside the schema enum")
    return converted


def _skeleton(node: dict[str, Any]) -> Any:
    node_kind = _kind(node)
    if node_kind == "object":
        return {name: _skeleton(child) for name, child in node["properties"].items()}
    if node_kind == "array":
        return []
    return None


def _pointer_parts(pointer: str) -> list[str]:
    return [
        part.replace("~1", "/").replace("~0", "~")
        for part in pointer.split("/")[1:]
    ]


def _set_pointer(document: Any, pointer: str, value: Any) -> None:
    parts = _pointer_parts(pointer)
    target = document
    for part in parts[:-1]:
        target = target[int(part)] if isinstance(target, list) else target[part]
    if isinstance(target, list):
        target[int(parts[-1])] = value
    else:
        target[parts[-1]] = value


def _get_pointer(document: Any, pointer: str) -> Any:
    target = document
    for part in _pointer_parts(pointer):
        target = target[int(part)] if isinstance(target, list) else target[part]
    return target


def _covered_by_spans(
    source_text: str, start: int, spans: list[Any]
) -> bool:
    for offset, character in enumerate(source_text, start=start):
        if character.isspace():
            continue
        if not any(span.start <= offset < span.end for span in spans):
            return False
    return True


@dataclass(frozen=True, slots=True)
class _Accepted:
    field: ExtractionFieldSpec
    extraction_class: str
    value: Any
    start: int
    end: int
    group_index: int | None
    evidence: NativeExtractionEvidence


def _grounded_candidates(
    annotated: Any,
    translated: TranslatedExtractionSchema,
    parse_result: NativeParseResult,
) -> tuple[list[_Accepted], list[str]]:
    accepted: list[_Accepted] = []
    warnings: list[str] = []
    base_text = parse_result.document.base_text
    for extraction in getattr(annotated, "extractions", []) or []:
        extraction_class = str(getattr(extraction, "extraction_class", ""))
        field = translated.fields_by_class.get(extraction_class)
        if field is None:
            warnings.append(f"rejected unknown extraction class {extraction_class!r}")
            continue
        interval = getattr(extraction, "char_interval", None)
        start = getattr(interval, "start_pos", None)
        end = getattr(interval, "end_pos", None)
        source_text = str(getattr(extraction, "extraction_text", ""))
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end <= start
            or end > len(base_text)
        ):
            warnings.append(
                f"{field.pointer_template}: rejected missing or invalid char_interval"
            )
            continue
        if base_text[start:end] != source_text:
            warnings.append(f"{field.pointer_template}: rejected non-exact source text")
            continue
        spans = parse_result.document.source_spans_for(start, end)
        if not spans or not _covered_by_spans(source_text, start, spans):
            warnings.append(f"{field.pointer_template}: rejected unresolved source anchor")
            continue
        try:
            value = _coerce(source_text, field)
        except ValueError as exc:
            warnings.append(f"{field.pointer_template}: rejected value that {exc}")
            continue
        evidence = NativeExtractionEvidence(
            source_text=source_text,
            char_interval=CharacterInterval(start=start, end=end),
            source_spans=spans,
        )
        accepted.append(
            _Accepted(
                field=field,
                extraction_class=extraction_class,
                value=value,
                start=start,
                end=end,
                group_index=getattr(extraction, "group_index", None),
                evidence=evidence,
            )
        )
    return accepted, warnings


def _assemble_values(
    translated: TranslatedExtractionSchema,
    accepted: list[_Accepted],
    warnings: list[str],
) -> tuple[
    dict[str, Any],
    list[NativeExtractedValue],
    dict[str, list[dict[str, Any]]],
]:
    data = _skeleton(translated.source_schema)
    values: list[NativeExtractedValue] = []
    evidence_by_pointer: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def add_value(item: _Accepted, pointer: str) -> None:
        values.append(
            NativeExtractedValue(
                pointer=pointer,
                extraction_class=item.extraction_class,
                value=item.value,
                evidence=item.evidence,
            )
        )
        evidence_by_pointer[pointer].append(item.evidence.model_dump(mode="json"))

    scalar_candidates: dict[str, list[_Accepted]] = defaultdict(list)
    array_candidates: dict[str, list[_Accepted]] = defaultdict(list)
    for item in accepted:
        if item.field.array_pointer is None:
            scalar_candidates[item.field.pointer_template].append(item)
        else:
            array_candidates[item.field.array_pointer].append(item)

    for pointer, candidates in scalar_candidates.items():
        candidates.sort(key=lambda item: (item.start, item.end))
        chosen = candidates[0]
        _set_pointer(data, pointer, chosen.value)
        add_value(chosen, pointer)
        if len(candidates) > 1:
            warnings.append(f"{pointer}: ignored duplicate grounded values")

    group_specs = {
        group.array_pointer: group
        for group in translated.groups
        if group.array_pointer is not None
    }
    for array_pointer, candidates in array_candidates.items():
        group_spec = group_specs[array_pointer]
        if group_spec.item_schema is None:
            raise RuntimeError(f"{array_pointer}: missing translated item schema")
        item_schema = group_spec.item_schema
        grouped: dict[tuple[str, int], list[_Accepted]] = defaultdict(list)
        for sequence, item in enumerate(
            sorted(candidates, key=lambda value: value.start)
        ):
            group_key = item.group_index if item.group_index is not None else sequence
            grouped[(array_pointer, group_key)].append(item)
        ordered_groups = sorted(
            grouped.values(), key=lambda group: min(item.start for item in group)
        )
        target_array = _get_pointer(data, array_pointer)
        for group in ordered_groups:
            if _kind(item_schema) == "object":
                target = _skeleton(item_schema)
                relative_records: list[tuple[_Accepted, str]] = []
                for item in sorted(group, key=lambda value: value.start):
                    relative = item.field.pointer_template.removeprefix(
                        f"{array_pointer}/*"
                    )
                    if any(path == relative for _old, path in relative_records):
                        warnings.append(
                            f"{item.field.pointer_template}: ignored duplicate grouped value"
                        )
                        continue
                    _set_pointer(target, relative, item.value)
                    relative_records.append((item, relative))
                target_array.append(target)
                index = len(target_array) - 1
                for item, relative in relative_records:
                    add_value(item, f"{array_pointer}/{index}{relative}")
            else:
                item = min(group, key=lambda value: value.start)
                target_array.append(item.value)
                add_value(item, f"{array_pointer}/{len(target_array) - 1}")

    values.sort(key=lambda item: item.evidence.char_interval.start)
    return data, values, dict(evidence_by_pointer)


class LangExtractNativeExtractor:
    def __init__(
        self,
        config: ParserConfig | None = None,
        *,
        extract_func: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config or ParserConfig.from_env()
        self.extract_func = extract_func

    def extract(
        self,
        parse_result: NativeParseResult,
        schema: StoredSchema,
    ) -> NativeExtractionResult:
        model = self.config.cloud_model.value
        api_key = os.getenv(self.config.cloud_model.api_key_name)
        if not api_key:
            raise ValueError(f"{self.config.cloud_model.api_key_name} is required for native extraction")
        translated = translate_stored_schema(schema)
        provider_kwargs = {
            "api_key": api_key,
            "max_workers": self.config.provider_concurrency,
        }
        provider = "gemini" if model.startswith("gemini-") else "openai"
        if provider == "openai":
            provider_kwargs.update(
                base_url=(
                    os.getenv("AGNES_BASE_URL", "https://apihub.agnes-ai.com/v1")
                    if model == "agnes-2.5-flash"
                    else os.getenv("OPENAI_BASE_URL") or None
                ),
                reasoning_effort=self.config.cloud_model.reasoning_effort,
            )
        if self.extract_func is None:
            try:
                import langextract as lx
                from langextract.factory import ModelConfig
            except ImportError as exc:
                raise RuntimeError(
                    "native extraction requires grounded-docparse[native]"
                ) from exc
            extract_func = lx.extract
            model_config = ModelConfig(
                model_id=model,
                provider=provider,
                provider_kwargs=provider_kwargs,
            )
        else:
            extract_func = self.extract_func
            model_config = {
                "model_id": model,
                "provider": provider,
                "provider_kwargs": provider_kwargs,
            }

        started = time.perf_counter()
        annotated = extract_func(
            text_or_documents=parse_result.document.base_text,
            prompt_description=translated.prompt,
            examples=None,
            config=model_config,
            output_schema=translated.output_schema,
            use_schema_constraints=True,
            max_char_buffer=8_000,
            batch_length=self.config.provider_concurrency,
            max_workers=self.config.provider_concurrency,
            extraction_passes=1,
            fetch_urls=False,
            show_progress=False,
            resolver_params={
                "enable_fuzzy_alignment": False,
                "accept_match_lesser": False,
                "suppress_parse_errors": False,
            },
        )
        if isinstance(annotated, list):
            if len(annotated) != 1:
                raise ValueError("LangExtract returned an unexpected document count")
            annotated = annotated[0]

        accepted, warnings = _grounded_candidates(
            annotated,
            translated,
            parse_result,
        )
        data, values, evidence_by_pointer = _assemble_values(
            translated,
            accepted,
            warnings,
        )
        fingerprint = _schema_fingerprint(schema)
        usage = RunUsage()
        trace = [
            AgentTraceEvent(
                agent="langextract",
                model=model,
                action="native_extraction",
                status="completed",
                target_ids=[item.pointer for item in values],
                duration_ms=round((time.perf_counter() - started) * 1000),
                reasoning_effort=self.config.cloud_model.reasoning_effort,
                prompt_version="langextract-native-v1",
                summary=f"accepted={len(values)} rejected={len(warnings)}",
            )
        ]
        payload = {
            "schema_version": "1.0.0",
            "schema": schema.model_dump(mode="json"),
            "schema_fingerprint": fingerprint,
            "data": data,
            "values": [item.model_dump(mode="json") for item in values],
            "evidence": evidence_by_pointer,
            "warnings": warnings,
            "metadata": {
                "model": model,
                "reasoning_effort": self.config.cloud_model.reasoning_effort,
                "range_target": "base_text",
                "range_units": "unicode_codepoints",
                "usage": usage.model_dump(mode="json"),
                "trace": [item.model_dump(mode="json") for item in trace],
            },
        }
        return NativeExtractionResult(
            schema=schema,
            schema_fingerprint=fingerprint,
            data=data,
            values=values,
            evidence=evidence_by_pointer,
            json=json.dumps(payload, ensure_ascii=False, indent=2),
            warnings=warnings,
            usage=usage,
            trace=trace,
        )
