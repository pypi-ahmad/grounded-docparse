from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

from grounded_docparse.models import (
    Document,
    ExtractedField,
    ExtractionResult,
    Page,
    ParseResult,
    RunUsage,
)
from grounded_docparse.render import render_agentic_document


def test_parse_command_writes_standard_document_outputs(monkeypatch, tmp_path) -> None:
    from grounded_docparse import cli

    source = b"pdf-source"
    input_path = tmp_path / "Invoice.pdf"
    input_path.write_bytes(source)
    output_path = tmp_path / "results"
    calls = []

    class FakeParser:
        def __init__(self, config=None):
            calls.append(config)

        def parse(self, data, name):
            assert data == source
            assert name == "Invoice.pdf"
            document = Document(
                source_name=name,
                source_sha256=hashlib.sha256(data).hexdigest(),
                pages=[Page(number=1, width=612, height=792)],
            )
            rendered = render_agentic_document(document)
            return ParseResult(
                document=document,
                markdown="# Invoice\n",
                json=rendered.json,
                input_tokens=0,
                output_tokens=0,
                annotated_pdf=b"annotated",
            )

    monkeypatch.setattr(cli, "DocumentParser", FakeParser)

    exit_code = cli.main(
        ["parse", str(input_path), "--output", str(output_path)]
    )

    assert exit_code == 0
    folder = output_path / f"Invoice-{hashlib.sha256(source).hexdigest()[:8]}"
    assert (folder / "Invoice.md").read_text(encoding="utf-8") == "# Invoice\n"
    assert (folder / "Invoice.annotated.pdf").read_bytes() == b"annotated"
    full = json.loads((folder / "Invoice.full.json").read_text(encoding="utf-8"))
    assert full["schema_version"] == "4.6.0"
    manifest = json.loads((output_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == 1
    assert manifest["documents"][0]["status"] == "complete"
    assert calls and calls[0].ocr_engine.value == "glm-ocr"


def test_parse_command_applies_json_schema(monkeypatch, tmp_path) -> None:
    from grounded_docparse import cli

    input_path = tmp_path / "invoice.pdf"
    input_path.write_bytes(b"invoice")
    schema_path = tmp_path / "invoice.json"
    schema = {
        "type": "object",
        "properties": {
            "invoice_number": {"type": ["string", "null"]},
        },
        "required": ["invoice_number"],
        "additionalProperties": False,
    }
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    output_path = tmp_path / "results"

    class FakeParser:
        def __init__(self, config=None):
            pass

        def parse(self, data, name):
            document = Document(
                source_name=name,
                source_sha256=hashlib.sha256(data).hexdigest(),
                pages=[Page(number=1, width=612, height=792)],
            )
            rendered = render_agentic_document(document)
            return ParseResult(
                document=document,
                markdown=rendered.markdown,
                json=rendered.json,
                input_tokens=0,
                output_tokens=0,
                annotated_pdf=b"annotated",
            )

    class FakeAgent:
        def extract(self, result, compiled_schema):
            assert compiled_schema == schema
            return ExtractionResult(
                data={"invoice_number": "INV-42"},
                evidence={},
                json='{"invoice_number":"INV-42"}',
                warnings=[],
                input_tokens=0,
                output_tokens=0,
                usage=RunUsage(),
                trace=[],
                fields={
                    "invoice_number": ExtractedField(
                        value="INV-42",
                        confidence="high",
                    )
                },
            )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(cli, "DocumentParser", FakeParser)
    monkeypatch.setattr(cli, "DocumentAgent", FakeAgent)

    exit_code = cli.main(
        [
            "parse",
            str(input_path),
            "--schema",
            str(schema_path),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    folder = next(path for path in output_path.iterdir() if path.is_dir())
    assert json.loads((folder / "invoice.extract.json").read_text(encoding="utf-8")) == {
        "invoice_number": "INV-42"
    }
    full = json.loads((folder / "invoice.full.json").read_text(encoding="utf-8"))
    assert full["extracted_fields"]["invoice_number"]["value"] == "INV-42"


def test_directory_batch_continues_after_document_failure(
    monkeypatch, tmp_path, capsys
) -> None:
    from grounded_docparse import cli

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "good.pdf").write_bytes(b"good")
    (inputs / "bad.png").write_bytes(b"bad")
    (inputs / "ignored.txt").write_text("ignore", encoding="utf-8")
    output_path = tmp_path / "results"
    parsed = []

    class FakeParser:
        def __init__(self, config=None):
            pass

        def parse(self, data, name):
            parsed.append(name)
            if name == "bad.png":
                raise RuntimeError("broken image")
            document = Document(
                source_name=name,
                source_sha256=hashlib.sha256(data).hexdigest(),
                pages=[Page(number=1, width=10, height=10)],
            )
            rendered = render_agentic_document(document)
            return ParseResult(
                document=document,
                markdown="good",
                json=rendered.json,
                input_tokens=0,
                output_tokens=0,
                annotated_pdf=b"pdf",
            )

    monkeypatch.setattr(cli, "DocumentParser", FakeParser)

    exit_code = cli.main(["parse", str(inputs), "--output", str(output_path)])

    assert exit_code == 1
    assert parsed == ["bad.png", "good.pdf"]
    manifest = json.loads((output_path / "manifest.json").read_text(encoding="utf-8"))
    assert [item["status"] for item in manifest["documents"]] == [
        "failed",
        "complete",
    ]
    assert manifest["documents"][0]["failed_stage"] == "parse"
    assert "bad.png: RuntimeError: broken image" in capsys.readouterr().err


def test_nonempty_output_requires_overwrite_and_preserves_unrelated_files(
    monkeypatch, tmp_path, capsys
) -> None:
    from grounded_docparse import cli

    input_path = tmp_path / "notice.pdf"
    input_path.write_bytes(b"notice")
    output_path = tmp_path / "results"
    output_path.mkdir()
    unrelated = output_path / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")
    parse_calls = 0

    class FakeParser:
        def __init__(self, config=None):
            pass

        def parse(self, data, name):
            nonlocal parse_calls
            parse_calls += 1
            document = Document(
                source_name=name,
                source_sha256=hashlib.sha256(data).hexdigest(),
                pages=[Page(number=1, width=10, height=10)],
            )
            rendered = render_agentic_document(document)
            return ParseResult(
                document=document,
                markdown="notice",
                json=rendered.json,
                input_tokens=0,
                output_tokens=0,
                annotated_pdf=b"pdf",
            )

    monkeypatch.setattr(cli, "DocumentParser", FakeParser)

    refused = cli.main(["parse", str(input_path), "--output", str(output_path)])
    accepted = cli.main(
        [
            "parse",
            str(input_path),
            "--output",
            str(output_path),
            "--overwrite",
        ]
    )

    assert refused == 2
    assert accepted == 0
    assert parse_calls == 1
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert "output directory is not empty" in capsys.readouterr().err


def test_project_registers_grounded_docparse_console_command() -> None:
    project = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )

    assert project["project"]["scripts"]["grounded-docparse"] == (
        "grounded_docparse.cli:main"
    )


def test_markdown_schema_is_compiled_and_duplicate_inputs_are_deduplicated(
    monkeypatch, tmp_path
) -> None:
    from grounded_docparse import cli

    input_path = tmp_path / "invoice.pdf"
    input_path.write_bytes(b"invoice")
    schema_path = tmp_path / "invoice.md"
    schema_path.write_text(
        "# Invoice\n- invoice_number: Official invoice ID\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "results"
    parse_calls = 0
    captured_schema = None

    class FakeParser:
        def __init__(self, config=None):
            pass

        def parse(self, data, name):
            nonlocal parse_calls
            parse_calls += 1
            document = Document(
                source_name=name,
                source_sha256=hashlib.sha256(data).hexdigest(),
                pages=[Page(number=1, width=10, height=10)],
            )
            rendered = render_agentic_document(document)
            return ParseResult(
                document=document,
                markdown="invoice",
                json=rendered.json,
                input_tokens=0,
                output_tokens=0,
                annotated_pdf=b"pdf",
            )

    class FakeAgent:
        def extract(self, result, schema):
            nonlocal captured_schema
            captured_schema = schema
            return ExtractionResult(
                data={"invoice_number": None},
                evidence={},
                json='{"invoice_number":null}',
                warnings=[],
                input_tokens=0,
                output_tokens=0,
                usage=RunUsage(),
                trace=[],
            )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(cli, "DocumentParser", FakeParser)
    monkeypatch.setattr(cli, "DocumentAgent", FakeAgent)

    exit_code = cli.main(
        [
            "parse",
            str(input_path),
            str(input_path),
            "--schema",
            str(schema_path),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    assert parse_calls == 1
    assert captured_schema["properties"]["invoice_number"] == {
        "type": ["string", "null"],
        "description": "Official invoice ID",
    }


def test_preflight_rejects_schema_without_key_and_empty_input_directory(
    monkeypatch, tmp_path, capsys
) -> None:
    from grounded_docparse import cli

    input_path = tmp_path / "invoice.pdf"
    input_path.write_bytes(b"invoice")
    schema_path = tmp_path / "invoice.md"
    schema_path.write_text("# Invoice\n- id: ID\n", encoding="utf-8")
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    missing_key = cli.main(
        [
            "parse",
            str(input_path),
            "--schema",
            str(schema_path),
            "--output",
            str(tmp_path / "schema-results"),
        ]
    )
    empty_directory = cli.main(
        ["parse", str(empty), "--output", str(tmp_path / "empty-results")]
    )

    assert missing_key == 2
    assert empty_directory == 2
    errors = capsys.readouterr().err
    assert "OPENAI_API_KEY is required" in errors
    assert "no supported documents were found" in errors
