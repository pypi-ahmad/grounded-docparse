import json
from pathlib import Path

from graphify.extract import collect_files, extract


def main() -> None:
    detect = json.loads(
        Path("graphify-out/.graphify_detect.json").read_text(encoding="utf-8")
    )
    code_files = []
    for filename in detect.get("files", {}).get("code", []):
        path = Path(filename)
        code_files.extend(collect_files(path) if path.is_dir() else [path])
    result = (
        extract(code_files, cache_root=Path("."))
        if code_files
        else {"nodes": [], "edges": [], "input_tokens": 0, "output_tokens": 0}
    )
    Path("graphify-out/.graphify_ast.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f'AST: {len(result["nodes"])} nodes, {len(result["edges"])} edges')


if __name__ == "__main__":
    main()
