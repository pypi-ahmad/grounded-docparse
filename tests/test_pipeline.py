from __future__ import annotations

import io
import json
import zipfile

import pymupdf
import pytest
from PIL import Image

from grounded_docparse import DocumentParser, ParserConfig
from grounded_docparse.models import (
    DocumentResolution,
    PageVerification,
    ProcessingProfile,
    RecognitionCandidate,
    RunRecord,
    VerificationDecision,
)


def offline_config() -> ParserConfig:
    return ParserConfig(
        enable_paddle=False,
        enable_glm=False,
        enable_openai=False,
        render_dpi=150,
    )


def test_offline_pipeline_is_deterministic(simple_pdf: bytes) -> None:
    parser = DocumentParser(offline_config())
    first = parser.parse(simple_pdf, "test.pdf")
    second = parser.parse(simple_pdf, "test.pdf")
    assert first.markdown == second.markdown
    assert first.json == second.json
    assert "Grounded source paragraph" in first.markdown
    payload = json.loads(first.json)
    assert payload["schema_version"] == "1.9.0"
    assert payload["processing_profile"] == "local-only"
    assert len(payload["pages"]) == 1
    assert "format: grounded-llm-markdown-v1" in first.llm_markdown
    assert "<!-- source citation=" in first.llm_markdown
    with zipfile.ZipFile(io.BytesIO(first.bundle)) as archive:
        assert "test.llm.md" in archive.namelist()
        assert "test.audit.json" in archive.namelist()
        assert "test.failures.jsonl" in archive.namelist()
        assert "test.quality.json" in archive.namelist()
        assert "test.annotated.pdf" in archive.namelist()
    assert first.bundle.startswith(b"PK")


def test_offline_pipeline_preserves_progress_event_order(simple_pdf: bytes) -> None:
    events = []

    DocumentParser(offline_config()).parse(
        simple_pdf,
        "test.pdf",
        events.append,
    )

    assert [
        (event.stage, event.current, event.total, event.message) for event in events
    ] == [
        ("ingest", 0, 1, "Validating document"),
        ("ingest", 1, 1, "Prepared 1 pages"),
        ("complete", 1, 1, "Exports ready"),
    ]


def test_every_child_reference_exists(simple_pdf: bytes) -> None:
    result = DocumentParser(offline_config()).parse(simple_pdf, "test.pdf")
    ids = set(result.tree.nodes)
    for node in result.tree.nodes.values():
        assert set(node.children_ids) <= ids
        assert all(relation.target_id in ids for relation in node.relationships)
        for child_id in node.children_ids:
            assert result.tree.nodes[child_id].parent_id == node.id


def test_pipeline_builds_semantic_sections_and_node_markdown(simple_pdf: bytes) -> None:
    result = DocumentParser(offline_config()).parse(simple_pdf, "test.pdf")
    sections = [node for node in result.tree.nodes.values() if node.type == "Section"]
    headings = [node for node in result.tree.nodes.values() if node.type == "Heading"]
    assert sections
    assert headings
    assert result.tree.nodes[headings[0].parent_id].type == "Section"
    assert all(node.markdown is not None for node in result.tree.nodes.values())


def test_table_rows_and_cells_are_nodes(simple_pdf: bytes, monkeypatch) -> None:
    payload = {
        1: {
            "parsing_res_list": [
                {
                    "block_bbox": [0.1, 0.1, 0.9, 0.5],
                    "block_label": "table",
                    "block_order": 0,
                    "block_content": "A B",
                    "score": 0.9,
                    "table_rows": [[{"text": "A"}, {"text": "B"}]],
                }
            ]
        }
    }
    monkeypatch.setattr(
        "grounded_docparse.pipeline.PaddleDockerRunner.run",
        lambda *_args, **_kwargs: payload,
    )
    config = ParserConfig(
        enable_paddle=True, enable_glm=False, enable_openai=False, render_dpi=150
    )
    result = DocumentParser(config).parse(simple_pdf, "test.pdf")
    tree = result.tree
    table = next(node for node in tree.nodes.values() if node.type == "Table")
    row = tree.nodes[table.children_ids[0]]
    assert row.type == "TableRow"
    assert [tree.nodes[item].type for item in row.children_ids] == [
        "TableCell",
        "TableCell",
    ]


def test_cloud_requires_explicit_consent(simple_pdf: bytes, monkeypatch) -> None:
    called = False

    class ForbiddenGateway:
        def __init__(self, _config):
            nonlocal called
            called = True

    monkeypatch.setattr(
        "grounded_docparse.pipeline.OpenAIDocumentGateway", ForbiddenGateway
    )
    config = ParserConfig(
        enable_paddle=False,
        enable_glm=False,
        enable_openai=True,
        render_dpi=150,
    )
    DocumentParser(config).parse(simple_pdf, "test.pdf")
    assert not called


def test_glm_unloads_after_failure(monkeypatch) -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (100, 100), "white").save(buffer, "PNG")
    unloaded = False

    class FailingGlm:
        def __init__(self, _config):
            pass

        def recognize_region(self, _path, _node_type, **_kwargs):
            raise RuntimeError("do-not-export-123")

        def unload(self):
            nonlocal unloaded
            unloaded = True

    monkeypatch.setattr("grounded_docparse.pipeline.GlmOcrGateway", FailingGlm)
    config = ParserConfig(
        enable_paddle=False, enable_glm=True, enable_openai=False, render_dpi=72
    )
    result = DocumentParser(config).parse(buffer.getvalue(), "scan.png")
    assert unloaded
    assert "do-not-export-123" not in result.failures_jsonl
    assert "provider_page_error" in result.failures_jsonl


def test_full_page_fallback_triggers_high_dpi_layout_retry(monkeypatch) -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (200, 200), "white").save(buffer, "PNG")
    calls = 0

    def fake_paddle(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {}
        return {
            1: {
                "parsing_res_list": [
                    {
                        "block_bbox": [0.1, 0.1, 0.9, 0.3],
                        "block_label": "text",
                        "block_order": 0,
                        "block_content": "Recovered at high resolution",
                    }
                ]
            }
        }

    monkeypatch.setattr(
        "grounded_docparse.pipeline.PaddleDockerRunner.run", fake_paddle
    )
    result = DocumentParser(
        ParserConfig(
            enable_paddle=True,
            enable_glm=False,
            enable_openai=False,
            render_dpi=72,
        )
    ).parse(buffer.getvalue(), "scan.png")
    assert calls == 2
    assert result.tree.adaptive_retries[0].scope == "page"
    assert result.tree.adaptive_retries[0].outcome == "applied"
    node = result.tree.nodes[result.tree.pages[0].content_node_ids[0]]
    assert node.text == "Recovered at high resolution"


def test_scanned_page_routes_every_paddle_region_through_glm(monkeypatch) -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (400, 400), "white").save(buffer, "PNG")
    blocks = [
        {
            "block_bbox": [0.1, 0.1, 0.9, 0.25],
            "block_label": "text",
            "block_order": 0,
            "block_content": "Paddle text",
        },
        {
            "block_bbox": [0.1, 0.3, 0.9, 0.55],
            "block_label": "table",
            "block_order": 1,
            "block_content": "A 1",
        },
        {
            "block_bbox": [0.1, 0.6, 0.9, 0.8],
            "block_label": "formula",
            "block_order": 2,
            "block_content": "x=1",
        },
    ]
    monkeypatch.setattr(
        "grounded_docparse.pipeline.PaddleDockerRunner.run",
        lambda *_args, **_kwargs: {1: {"parsing_res_list": blocks}},
    )
    calls = []

    class FakeGlm:
        def __init__(self, _config):
            pass

        def recognize_region(self, _path, node_type, *, region_id, pass_number):
            calls.append(node_type.value)
            return (
                RecognitionCandidate(
                    id=f"{region_id}:glm:{pass_number}",
                    source="glm",
                    task="test",
                    prompt_version="test-v1",
                    pass_number=pass_number,
                    text=f"GLM {node_type.value}",
                ),
                RunRecord(
                    provider="ollama",
                    model="glm-ocr",
                    stage="region_ocr",
                    region_id=region_id,
                ),
            )

        def unload(self):
            pass

    monkeypatch.setattr("grounded_docparse.pipeline.GlmOcrGateway", FakeGlm)
    config = ParserConfig(
        enable_paddle=True, enable_glm=True, enable_openai=False, render_dpi=72
    )
    tree = DocumentParser(config).parse(buffer.getvalue(), "scan.png").tree
    content = [tree.nodes[node_id] for node_id in tree.pages[0].content_node_ids]
    assert calls[:3] == ["Paragraph", "Table", "Formula"]
    assert calls[3:] == ["Paragraph", "Table", "Formula"]
    assert len(tree.adaptive_retries) == 3
    assert all(
        any(item.source == "glm" for item in node.recognition_candidates)
        for node in content
    )
    assert all(
        node.selected_candidate_id and ":glm:" in node.selected_candidate_id
        for node in content
    )


def test_cloud_proposal_requires_confirming_glm_retry(monkeypatch) -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (200, 200), "white").save(buffer, "PNG")
    passes = []

    class FakeGlm:
        def __init__(self, _config):
            pass

        def recognize_region(self, _path, _node_type, *, region_id, pass_number):
            passes.append(pass_number)
            text = "Total 100.00" if pass_number == 1 else "Total 108.00"
            return RecognitionCandidate(
                id=f"{region_id}:glm:{pass_number}",
                source="glm",
                task="text",
                prompt_version="test-v1",
                pass_number=pass_number,
                text=text,
            ), RunRecord(provider="ollama", model="glm-ocr", stage="region_ocr")

        def unload(self):
            pass

    class FakeOpenAI:
        def __init__(self, _config):
            pass

        def verify_page(self, _page, regions):
            return PageVerification(
                decisions=[
                    VerificationDecision(
                        region_id=regions[0].id,
                        proposed_text="Total 108.00",
                        needs_retry=True,
                    )
                ]
            ), RunRecord(provider="openai", model="luna", stage="page_verification")

    monkeypatch.setattr("grounded_docparse.pipeline.GlmOcrGateway", FakeGlm)
    monkeypatch.setattr("grounded_docparse.pipeline.OpenAIDocumentGateway", FakeOpenAI)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    config = ParserConfig(
        enable_paddle=False, enable_glm=True, enable_openai=True, render_dpi=72
    )
    tree = (
        DocumentParser(config)
        .parse(buffer.getvalue(), "scan.png", allow_cloud=True)
        .tree
    )
    node = tree.nodes[tree.pages[0].content_node_ids[0]]
    assert passes == [1, 2]
    assert node.text == "Total 108.00"
    assert node.verification_status == "retry_confirmed"
    assert node.selected_candidate_id.endswith(":glm:2")


def test_hybrid_sends_only_uncertain_regions_to_luna(monkeypatch) -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (300, 300), "white").save(buffer, "PNG")
    blocks = [
        {
            "block_bbox": [0.1, 0.1, 0.9, 0.3],
            "block_label": "text",
            "block_order": 0,
            "block_content": "Agreed text",
        },
        {
            "block_bbox": [0.1, 0.5, 0.9, 0.7],
            "block_label": "text",
            "block_order": 1,
            "block_content": "Paddle text",
        },
    ]
    monkeypatch.setattr(
        "grounded_docparse.pipeline.PaddleDockerRunner.run",
        lambda *_args, **_kwargs: {1: {"parsing_res_list": blocks}},
    )

    glm_calls = 0

    class FakeGlm:
        def __init__(self, _config):
            pass

        def recognize_region(self, _path, _node_type, *, region_id, pass_number):
            nonlocal glm_calls
            glm_calls += 1
            text = "Agreed text" if glm_calls == 1 else "Different text"
            return RecognitionCandidate(
                id=f"{region_id}:glm:{pass_number}",
                source="glm",
                task="text",
                prompt_version="test-v1",
                pass_number=pass_number,
                text=text,
            ), RunRecord(provider="ollama", model="glm-ocr", stage="region_ocr")

        def unload(self):
            pass

    verified: list[list[str]] = []

    class FakeOpenAI:
        def __init__(self, _config):
            pass

        def verify_page(self, _page, regions):
            verified.append([region.id for region in regions])
            return PageVerification(), RunRecord(
                provider="openai", model="luna", stage="page_verification"
            )

        def resolve_document(self, _summary):
            raise AssertionError("Hybrid must not call Terra")

    monkeypatch.setattr("grounded_docparse.pipeline.GlmOcrGateway", FakeGlm)
    monkeypatch.setattr("grounded_docparse.pipeline.OpenAIDocumentGateway", FakeOpenAI)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    config = ParserConfig(enable_paddle=True, enable_glm=True, render_dpi=72)
    result = DocumentParser(config).parse(
        buffer.getvalue(), "scan.png", profile=ProcessingProfile.HYBRID
    )
    assert len(verified) == 1
    assert len(verified[0]) == 1
    assert result.tree.processing_profile == "hybrid"


def test_maximum_accuracy_verifies_all_pages_and_uses_terra(monkeypatch) -> None:
    source = pymupdf.open()
    for number in range(2):
        page = source.new_page()
        page.insert_text((72, 72), f"Page {number + 1} grounded text")
    data = source.tobytes()
    source.close()
    verified_pages: list[int] = []
    terra_calls = 0

    class FakeOpenAI:
        def __init__(self, _config):
            pass

        def verify_page(self, page, _regions):
            verified_pages.append(page.number)
            return PageVerification(), RunRecord(
                provider="openai", model="luna", stage="page_verification"
            )

        def resolve_document(self, _summary):
            nonlocal terra_calls
            terra_calls += 1
            return DocumentResolution(), RunRecord(
                provider="openai", model="terra", stage="document_resolution"
            )

    monkeypatch.setattr("grounded_docparse.pipeline.OpenAIDocumentGateway", FakeOpenAI)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    config = ParserConfig(
        enable_paddle=False, enable_glm=False, enable_openai=True, render_dpi=72
    )
    result = DocumentParser(config).parse(
        data, "two-pages.pdf", profile=ProcessingProfile.MAXIMUM_ACCURACY
    )
    assert verified_pages == [1, 2]
    assert terra_calls == 1
    assert result.tree.processing_profile == "maximum-accuracy"


def test_profile_validation_happens_before_processing(simple_pdf: bytes, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    parser = DocumentParser(
        ParserConfig(enable_paddle=False, enable_glm=False, enable_openai=True)
    )
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        parser.parse(simple_pdf, "test.pdf", profile=ProcessingProfile.HYBRID)
    with pytest.raises(ValueError, match="cannot be used together"):
        parser.parse(
            simple_pdf,
            "test.pdf",
            profile=ProcessingProfile.LOCAL_ONLY,
            allow_cloud=False,
        )


def test_digital_page_limits_glm_to_complex_regions(monkeypatch) -> None:
    source = pymupdf.open()
    page = source.new_page()
    digital_text = "Grounded source paragraph " * 20
    page.insert_textbox(pymupdf.Rect(50, 50, 550, 500), digital_text, fontsize=12)
    simple_pdf = source.tobytes()
    source.close()
    blocks = [
        {
            "block_bbox": [0.0, 0.0, 1.0, 0.4],
            "block_label": "text",
            "block_order": 0,
            "block_content": digital_text,
        },
        {
            "block_bbox": [0.1, 0.5, 0.9, 0.8],
            "block_label": "table",
            "block_order": 1,
            "block_content": "A 1",
        },
    ]
    monkeypatch.setattr(
        "grounded_docparse.pipeline.PaddleDockerRunner.run",
        lambda *_args, **_kwargs: {1: {"parsing_res_list": blocks}},
    )
    calls = []

    class FakeGlm:
        def __init__(self, _config):
            pass

        def recognize_region(self, _path, node_type, *, region_id, pass_number):
            calls.append(node_type.value)
            return RecognitionCandidate(
                id=f"{region_id}:glm:{pass_number}",
                source="glm",
                task="table",
                prompt_version="test-v1",
                pass_number=pass_number,
                text="A | 1",
            ), RunRecord(provider="ollama", model="glm-ocr", stage="region_ocr")

        def unload(self):
            pass

    monkeypatch.setattr("grounded_docparse.pipeline.GlmOcrGateway", FakeGlm)
    config = ParserConfig(
        enable_paddle=True, enable_glm=True, enable_openai=False, render_dpi=150
    )
    result = DocumentParser(config).parse(simple_pdf, "digital.pdf")
    assert calls == ["Table", "Table"]
    assert result.tree.adaptive_retries[0].scope == "region"


def test_safe_pdf_link_is_preserved() -> None:
    source = pymupdf.open()
    page = source.new_page()
    page.insert_text((72, 72), "Official source")
    page.insert_link(
        {
            "kind": pymupdf.LINK_URI,
            "from": pymupdf.Rect(70, 55, 180, 80),
            "uri": "https://example.com/source",
        }
    )
    data = source.tobytes()
    source.close()
    result = DocumentParser(offline_config()).parse(data, "linked.pdf")
    links = [link.uri for node in result.tree.nodes.values() for link in node.links]
    assert links == ["https://example.com/source"]
    assert 'href="https://example.com/source"' in result.markdown


def test_lists_and_captions_have_semantic_parents(
    simple_pdf: bytes, monkeypatch
) -> None:
    blocks = [
        {
            "block_bbox": [0.1, 0.1, 0.8, 0.4],
            "block_label": "figure",
            "block_order": 0,
            "block_content": "",
        },
        {
            "block_bbox": [0.1, 0.41, 0.8, 0.5],
            "block_label": "caption",
            "block_order": 1,
            "block_content": "Figure one",
        },
        {
            "block_bbox": [0.1, 0.6, 0.8, 0.7],
            "block_label": "list_item",
            "block_order": 2,
            "block_content": "First",
        },
        {
            "block_bbox": [0.1, 0.7, 0.8, 0.8],
            "block_label": "list_item",
            "block_order": 3,
            "block_content": "Second",
        },
    ]
    monkeypatch.setattr(
        "grounded_docparse.pipeline.PaddleDockerRunner.run",
        lambda *_args, **_kwargs: {1: {"parsing_res_list": blocks}},
    )
    config = ParserConfig(
        enable_paddle=True, enable_glm=False, enable_openai=False, render_dpi=150
    )
    result = DocumentParser(config).parse(simple_pdf, "test.pdf")
    tree = result.tree
    figure = next(node for node in tree.nodes.values() if node.type == "Figure")
    caption = next(node for node in tree.nodes.values() if node.type == "Caption")
    list_node = next(node for node in tree.nodes.values() if node.type == "List")
    assert caption.parent_id == figure.id
    assert [tree.nodes[item].type for item in list_node.children_ids] == [
        "ListItem",
        "ListItem",
    ]
    assert f"node={figure.id}" in result.llm_markdown
    assert f"node={caption.id}" in result.llm_markdown
