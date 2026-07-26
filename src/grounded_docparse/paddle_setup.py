from __future__ import annotations

import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from PIL import Image, ImageDraw

from .config import ParserConfig
from .paddle import PaddleDockerRunner


def main() -> None:
    config = ParserConfig.from_env()
    runner = PaddleDockerRunner(config)
    docker = runner.preflight()
    name = f"grounded-docparse-setup-{uuid.uuid4().hex[:12]}"
    with tempfile.TemporaryDirectory(prefix="grounded-docparse-setup-") as temporary:
        root = Path(temporary)
        source = root / "warmup.png"
        output = root / "output"
        worker = root / "worker.py"
        output.mkdir()
        image = Image.new("RGB", (256, 128), "white")
        ImageDraw.Draw(image).text((16, 48), "PaddleOCR-VL cache warm-up", fill="black")
        image.save(source)
        shutil.copyfile(Path(__file__).with_name("paddle_worker.py"), worker)
        command = [
            docker,
            "run",
            "--rm",
            "--name",
            name,
            "--user",
            "root",
            "--gpus",
            "all",
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
            "--mount",
            f"type=bind,source={source.resolve()},target=/input/warmup.png,readonly",
            "--mount",
            f"type=bind,source={worker.resolve()},target=/worker.py,readonly",
            "--mount",
            f"type=bind,source={output.resolve()},target=/output",
            "--mount",
            f"type=volume,source={config.paddle_cache_volume},target=/home/paddleocr/.paddlex",
            config.paddle_image,
            "python",
            "/worker.py",
            "--input",
            "/input/warmup.png",
            "--output",
            "/output",
            "--total-pages",
            "1",
            "--max-new-tokens",
            str(config.paddle_max_new_tokens),
        ]
        ownership_command = [
            docker,
            "run",
            "--rm",
            "--user",
            "root",
            "--mount",
            f"type=volume,source={config.paddle_cache_volume},target=/home/paddleocr/.paddlex",
            "--entrypoint",
            "/bin/chown",
            config.paddle_image,
            "-R",
            "paddleocr:paddleocr",
            "/home/paddleocr/.paddlex",
        ]
        try:
            subprocess.run(command, check=True, timeout=config.paddle_timeout_seconds)
            subprocess.run(ownership_command, check=True, timeout=60)
        except subprocess.TimeoutExpired:
            runner._terminate_container(docker, name)
            raise SystemExit("Paddle cache warm-up timed out") from None
        except subprocess.CalledProcessError as exc:
            raise SystemExit(f"Paddle cache warm-up failed with exit code {exc.returncode}") from None
    print(f"Paddle cache ready: {config.paddle_cache_volume}")
