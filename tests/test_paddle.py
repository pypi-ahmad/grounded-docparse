import subprocess
from pathlib import Path

import pytest

from grounded_docparse import ParserConfig
from grounded_docparse import paddle_setup
from grounded_docparse.paddle import (
    PaddleDockerRunner,
    find_paddle_regions,
    find_paddle_table_results,
    normalize_paddle_table,
)


def test_finds_version_tolerant_paddle_regions() -> None:
    payload = {
        "res": {
            "parsing_res_list": [
                {
                    "block_bbox": [1, 2, 3, 4],
                    "block_label": "text",
                    "block_order": 0,
                    "block_content": "hello",
                }
            ]
        }
    }
    assert find_paddle_regions(payload)[0]["block_content"] == "hello"


def test_normalizes_paddle_table_html_and_cell_boxes() -> None:
    payload = {
        "res": {
            "table_res_list": [
                {
                    "pred_html": (
                        "<table><tr><th colspan='2'>Heading</th></tr>"
                        "<tr><td>A</td><td>B</td></tr></table>"
                    ),
                    "cell_box_list": [[10, 20, 90, 40], [10, 40, 50, 60], [50, 40, 90, 60]],
                    "cell_scores": [0.99, 0.98, 0.97],
                }
            ]
        }
    }
    table = find_paddle_table_results(payload)[0]
    rows = normalize_paddle_table(table)
    assert rows[0][0] == {
        "text": "Heading",
        "header": True,
        "rowspan": 1,
        "colspan": 2,
        "provider_bbox": [10, 20, 90, 40],
        "score": 0.99,
    }
    assert [cell["text"] for cell in rows[1]] == ["A", "B"]


def test_runtime_command_is_offline_and_least_privilege(tmp_path: Path) -> None:
    config = ParserConfig(enable_glm=False, enable_openai=False)
    source = tmp_path / "input.pdf"
    worker = tmp_path / "worker.py"
    output = tmp_path / "output"
    output.mkdir()
    command = PaddleDockerRunner(config).runtime_command(
        "docker", "job-name", source, worker, output, 1
    )
    joined = " ".join(command)
    assert "--network none" in joined
    assert "--cap-drop ALL" in joined
    assert "no-new-privileges" in joined
    assert "readonly" in joined
    assert "target=/home/paddleocr/.paddlex,readonly" in joined
    assert "@sha256:" in config.paddle_image


def test_setup_initializes_the_paddle_cache_as_root(monkeypatch) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(PaddleDockerRunner, "preflight", lambda _self: "docker")
    monkeypatch.setattr(
        "grounded_docparse.paddle_setup.subprocess.run",
        lambda command, **_kwargs: commands.append(command),
    )

    paddle_setup.main()

    command = commands[0]
    assert ["--user", "root"] == command[command.index("--user") : command.index("--user") + 2]
    assert any(
        "target=/home/paddleocr/.paddlex" in argument for argument in command
    )
    ownership_command = commands[1]
    assert ["--entrypoint", "/bin/chown"] == ownership_command[
        ownership_command.index("--entrypoint") : ownership_command.index("--entrypoint") + 2
    ]
    assert ownership_command[-2:] == ["paddleocr:paddleocr", "/home/paddleocr/.paddlex"]


def test_timeout_forcibly_removes_container(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "input.pdf"
    source.write_bytes(b"%PDF-1.7")
    removed: list[str] = []

    class Process:
        def __init__(self):
            self.stdout = []

        def wait(self, timeout):
            raise subprocess.TimeoutExpired("docker", timeout)

        def kill(self):
            pass

    monkeypatch.setattr(PaddleDockerRunner, "preflight", lambda _self: "docker")
    monkeypatch.setattr("grounded_docparse.paddle.subprocess.Popen", lambda *_a, **_k: Process())
    monkeypatch.setattr(
        PaddleDockerRunner,
        "_terminate_container",
        staticmethod(lambda _docker, name: removed.append(name)),
    )
    config = ParserConfig(paddle_timeout_seconds=1)
    with pytest.raises(RuntimeError, match="timed out"):
        PaddleDockerRunner(config).run(source, tmp_path, 1)
    assert removed and removed[0].startswith("grounded-docparse-")


def test_large_pdf_is_sent_to_paddle_in_source_chunks(
    tmp_path: Path, monkeypatch
) -> None:
    import pymupdf

    source = tmp_path / "batch.pdf"
    document = pymupdf.open()
    for _ in range(51):
        document.new_page()
    document.save(source)
    document.close()
    calls: list[int] = []

    def run_single(_self, source_path, _job_dir, total_pages, _progress=None):
        with pymupdf.open(source_path) as chunk:
            calls.append(chunk.page_count)
        return {page: {"page": page} for page in range(1, total_pages + 1)}

    monkeypatch.setattr(PaddleDockerRunner, "_run_single", run_single)
    config = ParserConfig(source_chunk_pages=25, chunk_retry_count=2)
    results = PaddleDockerRunner(config).run(source, tmp_path, 51)
    assert calls == [25, 25, 1]
    assert list(results) == list(range(1, 52))
