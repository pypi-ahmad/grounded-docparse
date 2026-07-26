from __future__ import annotations

import json
import shutil
import subprocess
import threading
import uuid
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pymupdf

from .config import ParserConfig
from .models import ProgressCallback, ProgressEvent


class _TableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[dict[str, Any]]] = []
        self.current_row: list[dict[str, Any]] | None = None
        self.current_cell: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.current_row = []
        elif tag in {"td", "th"} and self.current_row is not None:
            values = dict(attrs)
            self.current_cell = {
                "text": "",
                "header": tag == "th",
                "rowspan": int(values.get("rowspan") or 1),
                "colspan": int(values.get("colspan") or 1),
            }

    def handle_data(self, data: str) -> None:
        if self.current_cell is not None:
            self.current_cell["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self.current_cell is not None:
            self.current_cell["text"] = self.current_cell["text"].strip()
            assert self.current_row is not None
            self.current_row.append(self.current_cell)
            self.current_cell = None
        elif tag == "tr" and self.current_row is not None:
            self.rows.append(self.current_row)
            self.current_row = None


def find_paddle_table_results(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        value = payload.get("table_res_list")
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        for child in payload.values():
            found = find_paddle_table_results(child)
            if found:
                return found
    elif isinstance(payload, list):
        for child in payload:
            found = find_paddle_table_results(child)
            if found:
                return found
    return []


def normalize_paddle_table(result: dict[str, Any]) -> list[list[dict[str, Any]]]:
    parser = _TableHTMLParser()
    parser.feed(str(result.get("pred_html", "")))
    cells = [cell for row in parser.rows for cell in row]
    boxes = result.get("cell_box_list", [])
    scores = result.get("cell_scores", [])
    if isinstance(boxes, list):
        for index, cell in enumerate(cells):
            if index < len(boxes) and isinstance(boxes[index], (list, tuple)):
                cell["provider_bbox"] = list(boxes[index])
            if isinstance(scores, list) and index < len(scores):
                cell["score"] = scores[index]
    return parser.rows


class PaddleUnavailable(RuntimeError):
    pass


class PaddleDockerRunner:
    def __init__(self, config: ParserConfig) -> None:
        self.config = config

    def preflight(self) -> str:
        docker = shutil.which("docker")
        if not docker:
            raise PaddleUnavailable("Docker CLI is not installed or not on PATH")
        check = subprocess.run(
            [docker, "info", "--format", "{{.OSType}}"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if check.returncode != 0 or check.stdout.strip() != "linux":
            raise PaddleUnavailable("Docker Desktop Linux engine is not running")
        image = subprocess.run(
            [docker, "image", "inspect", self.config.paddle_image],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if image.returncode != 0:
            raise PaddleUnavailable(
                "Paddle image missing. Pull it first: "
                f"docker pull {self.config.paddle_image}"
            )
        return docker

    def runtime_command(
        self,
        docker: str,
        container_name: str,
        source_path: Path,
        worker_path: Path,
        output_dir: Path,
        total_pages: int,
    ) -> list[str]:
        container_input = f"/input/source{source_path.suffix.lower()}"
        return [
            docker,
            "run",
            "--rm",
            "--name",
            container_name,
            "--gpus",
            "all",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--memory",
            "16g",
            "--pids-limit",
            "512",
            "--shm-size",
            "4g",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=2g",
            "--tmpfs",
            "/root/.cache:rw,nosuid,nodev,size=512m",
            "--mount",
            f"type=bind,source={source_path.resolve()},target={container_input},readonly",
            "--mount",
            f"type=bind,source={worker_path.resolve()},target=/worker.py,readonly",
            "--mount",
            f"type=bind,source={output_dir.resolve()},target=/output",
            "--mount",
            f"type=volume,source={self.config.paddle_cache_volume},target=/home/paddleocr/.paddlex,readonly",
            "-e",
            "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=1",
            self.config.paddle_image,
            "python",
            "/worker.py",
            "--input",
            container_input,
            "--output",
            "/output",
            "--total-pages",
            str(total_pages),
            "--max-new-tokens",
            str(self.config.paddle_max_new_tokens),
            "--window-size",
            str(self.config.page_window_size),
            *( ["--chart-recognition"] if self.config.enable_chart_recognition else [] ),
            *( ["--image-ocr"] if self.config.enable_image_ocr else [] ),
        ]

    @staticmethod
    def _terminate_container(docker: str, container_name: str) -> None:
        subprocess.run(
            [docker, "rm", "-f", container_name],
            capture_output=True,
            timeout=30,
            check=False,
        )

    def _run_single(
        self,
        source_path: Path,
        job_dir: Path,
        total_pages: int,
        progress: ProgressCallback | None = None,
    ) -> dict[int, dict[str, Any]]:
        docker = self.preflight()
        worker_source = Path(__file__).with_name("paddle_worker.py")
        worker_target = job_dir / "paddle_worker.py"
        shutil.copyfile(worker_source, worker_target)
        output_dir = job_dir / "paddle"
        output_dir.mkdir(exist_ok=True)
        container_name = f"grounded-docparse-{uuid.uuid4().hex[:12]}"
        command = self.runtime_command(
            docker,
            container_name,
            source_path,
            worker_target,
            output_dir,
            total_pages,
        )
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert process.stdout is not None
        def read_output() -> None:
            for raw_line in process.stdout:
                try:
                    event = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                if event.get("event") == "page" and progress:
                    page_number = int(event["page"])
                    progress(
                        ProgressEvent(
                            stage="paddle",
                            current=page_number,
                            total=total_pages,
                            message=f"PaddleOCR-VL parsed page {page_number}",
                        )
                    )

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()

        try:
            return_code = process.wait(timeout=self.config.paddle_timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            self._terminate_container(docker, container_name)
            process.kill()
            raise RuntimeError("PaddleOCR-VL worker timed out") from exc
        finally:
            reader.join(timeout=5)
        if return_code != 0:
            raise RuntimeError(f"PaddleOCR-VL worker failed with exit code {return_code}")

        results: dict[int, dict[str, Any]] = {}
        for path in sorted(output_dir.glob("page-*.json")):
            page_number = int(path.stem.split("-")[-1])
            results[page_number] = json.loads(path.read_text(encoding="utf-8"))
        if not results:
            raise RuntimeError("PaddleOCR-VL produced no page results")
        return results

    def run(
        self,
        source_path: Path,
        job_dir: Path,
        total_pages: int,
        progress: ProgressCallback | None = None,
    ) -> dict[int, dict[str, Any]]:
        if (
            source_path.suffix.casefold() != ".pdf"
            or total_pages <= self.config.source_chunk_pages
        ):
            return self._run_single(source_path, job_dir, total_pages, progress)
        chunks_dir = job_dir / "paddle-source-chunks"
        chunks_dir.mkdir(exist_ok=True)
        combined: dict[int, dict[str, Any]] = {}
        with pymupdf.open(source_path) as source:
            for start in range(0, total_pages, self.config.source_chunk_pages):
                end = min(total_pages, start + self.config.source_chunk_pages)
                chunk_path = chunks_dir / f"pages-{start + 1:04d}-{end:04d}.pdf"
                chunk = pymupdf.open()
                try:
                    chunk.insert_pdf(source, from_page=start, to_page=end - 1)
                    chunk.save(chunk_path, garbage=3, deflate=True)
                finally:
                    chunk.close()
                def chunk_progress(event: ProgressEvent, offset: int = start) -> None:
                    if progress is None:
                        return
                    current = min(total_pages, event.current + offset)
                    progress(
                        ProgressEvent(
                            stage=event.stage,
                            current=current,
                            total=total_pages,
                            message=f"PaddleOCR-VL parsed page {current}",
                        )
                    )

                error: Exception | None = None
                for attempt in range(1, self.config.chunk_retry_count + 2):
                    try:
                        chunk_job = chunks_dir / f"run-{start + 1:04d}-attempt-{attempt}"
                        chunk_job.mkdir()
                        local = self._run_single(
                            chunk_path, chunk_job, end - start, chunk_progress
                        )
                        combined.update(
                            {page_number + start: value for page_number, value in local.items()}
                        )
                        error = None
                        break
                    except Exception as exc:  # noqa: BLE001 - bounded chunk retry
                        error = exc
                if error is not None:
                    for page_number in range(start + 1, end + 1):
                        combined[page_number] = {
                            "_provider_error": type(error).__name__,
                            "parsing_res_list": [],
                        }
        return combined


def find_paddle_regions(payload: Any) -> list[dict[str, Any]]:
    """Find Paddle layout regions without depending on one response version."""
    if isinstance(payload, dict):
        if {
            "block_bbox",
            "block_label",
            "block_order",
        }.issubset(payload):
            return [payload]
        for key in ("parsing_res_list", "blocks", "layout", "res"):
            value = payload.get(key)
            found = find_paddle_regions(value)
            if found:
                return found
        for value in payload.values():
            found = find_paddle_regions(value)
            if found:
                return found
    elif isinstance(payload, list):
        direct = [item for item in payload if isinstance(item, dict) and "block_bbox" in item]
        if direct:
            return direct
        for item in payload:
            found = find_paddle_regions(item)
            if found:
                return found
    return []
