"""Export/check the deterministic v1 contract without starting a server or connecting to a database."""

import argparse
import json
from pathlib import Path

from app.main import app

OUTPUT = Path(__file__).resolve().parents[3] / "docs" / "openapi" / "v1.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the committed contract is out of date")
    args = parser.parse_args()
    content = json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != content:
            parser.exit(1, "OpenAPI v1 is stale. Run: uv run python -m scripts.export_openapi\n")
        print("OpenAPI v1 matches the application.")
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(content, encoding="utf-8", newline="\n")
        print(f"Exported {OUTPUT}")


if __name__ == "__main__":
    main()
