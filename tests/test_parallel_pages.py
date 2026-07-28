from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from grounded_docparse import pipeline
from grounded_docparse.config import ParserConfig
from grounded_docparse.ingest import IngestedDocument, PageEvidence
from grounded_docparse.models import (
    AgentTraceEvent,
    AgentUsage,
    NodeType,
    PageDraft,
    RegionDraft,
    RunUsage,
)


def _stub_document(monkeypatch, tmp_path: Path, page_count: int) -> None:
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(b"%PDF-stub")
    pages = []
    for number in range(1, page_count + 1):
        image_path = tmp_path / f"page-{number}.png"
        image_path.write_bytes(b"image")
        pages.append(
            PageEvidence(
                number=number,
                width=100,
                height=100,
                dpi=72,
                image_path=image_path,
                scanned=True,
            )
        )
    document = IngestedDocument(
        name="parallel.pdf",
        sha256="a" * 64,
        source_path=source_path,
        pages=pages,
    )
    monkeypatch.setattr(pipeline, "ingest_document", lambda *_args, **_kwargs: document)
    monkeypatch.setattr(pipeline, "render_annotated_pdf", lambda *_args, **_kwargs: b"%PDF")


class ConcurrencyTracker:
    def __init__(self, release_at: int) -> None:
        self.condition = threading.Condition()
        self.active = 0
        self.maximum = 0
        self.release_at = release_at

    def enter(self) -> None:
        with self.condition:
            self.active += 1
            self.maximum = max(self.maximum, self.active)
            if self.active >= self.release_at:
                self.condition.notify_all()
            else:
                self.condition.wait_for(
                    lambda: self.maximum >= self.release_at,
                    timeout=0.5,
                )

    def leave(self) -> None:
        with self.condition:
            self.active -= 1


class ParallelGateway:
    def __init__(self, tracker: ConcurrencyTracker | None = None) -> None:
        self.tracker = tracker
        self.input_tokens = 0
        self.output_tokens = 0
        self.usage = RunUsage()
        self.trace: list[AgentTraceEvent] = []

    def draft_page(self, page: PageEvidence) -> PageDraft:
        if self.tracker is not None:
            self.tracker.enter()
        try:
            time.sleep(0.01)
            self.input_tokens = page.number
            self.output_tokens = 1
            self.usage = RunUsage(
                calls=[
                    AgentUsage(
                        agent=f"page-{page.number}",
                        model="fake",
                        input_tokens=page.number,
                        output_tokens=1,
                    )
                ]
            )
            self.trace = [
                AgentTraceEvent(
                    agent=f"page-{page.number}",
                    model="fake",
                    action="page_draft",
                    status="completed",
                    page=page.number,
                )
            ]
            node_type = NodeType.HEADING if page.number == 1 else NodeType.PARAGRAPH
            return PageDraft(
                regions=[
                    RegionDraft(
                        type=node_type,
                        text="Section" if page.number == 1 else f"Page {page.number}",
                        confidence=1,
                        reading_order=0,
                        heading_level=1 if page.number == 1 else None,
                    )
                ]
            )
        finally:
            if self.tracker is not None:
                self.tracker.leave()

    def inspect_crops(self, *_args, **_kwargs):
        raise AssertionError("crop inspection was not requested")


def test_parallel_page_config_defaults_and_environment(monkeypatch) -> None:
    assert ParserConfig().page_batch_size == 16
    assert ParserConfig().max_page_concurrency == 8

    monkeypatch.setenv("DOCPARSE_PAGE_BATCH_SIZE", "8")
    monkeypatch.setenv("DOCPARSE_MAX_PAGE_CONCURRENCY", "4")

    config = ParserConfig.from_env()

    assert config.page_batch_size == 8
    assert config.max_page_concurrency == 4


def test_parallel_page_config_rejects_concurrency_above_batch_size() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        ParserConfig(page_batch_size=4, max_page_concurrency=5)


def test_parser_processes_pages_concurrently_and_aggregates_in_page_order(
    monkeypatch, tmp_path: Path
) -> None:
    _stub_document(monkeypatch, tmp_path, page_count=6)
    tracker = ConcurrencyTracker(release_at=3)
    gateways: list[ParallelGateway] = []

    def gateway_factory(_config: ParserConfig) -> ParallelGateway:
        gateway = ParallelGateway(tracker)
        gateways.append(gateway)
        return gateway

    result = pipeline.DocumentParser(
        ParserConfig(page_batch_size=6, max_page_concurrency=3),
        gateway_factory=gateway_factory,
    ).parse(b"pdf", "parallel.pdf")

    assert tracker.maximum == 3
    assert len(gateways) == 6
    assert [page.number for page in result.document.pages] == list(range(1, 7))
    assert [call.agent for call in result.usage.calls] == [f"page-{n}" for n in range(1, 7)]
    assert result.input_tokens == sum(range(1, 7))
    assert result.output_tokens == 6
    assert [event.page for event in result.trace] == list(range(1, 7))


def test_parser_waits_for_a_batch_before_starting_the_next(
    monkeypatch, tmp_path: Path
) -> None:
    _stub_document(monkeypatch, tmp_path, page_count=3)
    started: set[int] = set()
    violation = threading.Event()
    lock = threading.Lock()

    class BatchGateway(ParallelGateway):
        def draft_page(self, page: PageEvidence) -> PageDraft:
            with lock:
                started.add(page.number)
            if page.number == 2:
                time.sleep(0.05)
                with lock:
                    if 3 in started:
                        violation.set()
            return super().draft_page(page)

    pipeline.DocumentParser(
        ParserConfig(page_batch_size=2, max_page_concurrency=2),
        gateway_factory=lambda _config: BatchGateway(),
    ).parse(b"pdf", "parallel.pdf")

    assert not violation.is_set()
    assert started == {1, 2, 3}


def test_parser_finalizes_cross_page_hierarchy_and_progress_on_caller_thread(
    monkeypatch, tmp_path: Path
) -> None:
    _stub_document(monkeypatch, tmp_path, page_count=3)
    caller_thread = threading.get_ident()
    callback_threads: list[int] = []

    result = pipeline.DocumentParser(
        ParserConfig(page_batch_size=2, max_page_concurrency=2),
        gateway_factory=lambda _config: ParallelGateway(),
    ).parse(
        b"pdf",
        "parallel.pdf",
        progress_callback=lambda _event: callback_threads.append(threading.get_ident()),
    )

    assert result.document.pages[1].blocks[0].section_path == ["Section"]
    assert result.document.pages[2].blocks[0].section_path == ["Section"]
    assert callback_threads
    assert set(callback_threads) == {caller_thread}


def test_parser_does_not_start_later_batches_after_a_fatal_page_error(
    monkeypatch, tmp_path: Path
) -> None:
    _stub_document(monkeypatch, tmp_path, page_count=4)
    started: list[int] = []
    lock = threading.Lock()

    class FailingGateway(ParallelGateway):
        def draft_page(self, page: PageEvidence) -> PageDraft:
            with lock:
                started.append(page.number)
            if page.number == 2:
                raise RuntimeError("page two failed")
            return super().draft_page(page)

    parser = pipeline.DocumentParser(
        ParserConfig(page_batch_size=2, max_page_concurrency=2),
        gateway_factory=lambda _config: FailingGateway(),
    )

    with pytest.raises(RuntimeError, match="page two failed"):
        parser.parse(b"pdf", "parallel.pdf")

    assert set(started).issubset({1, 2})
