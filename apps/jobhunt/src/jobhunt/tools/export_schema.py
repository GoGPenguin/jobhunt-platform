"""Write or check the committed JSON Schemas in schemas/.

The schemas describe the stored/output shape of each model and are the contract other
components read. `make schema` writes them; `make check` fails if they are stale.

    python -m jobhunt.tools.export_schema --out ../../schemas [--check]
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from jobhunt.domain.dead_letter import DeadLetter
from jobhunt.domain.job import Job

JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
SCHEMAS: dict[str, type[BaseModel]] = {
    "job.v1.json": Job,
    "dead_letter.v1.json": DeadLetter,
}


def render_schemas() -> dict[str, str]:
    """File name -> schema text, exactly as committed."""
    rendered = {}
    for name, model in SCHEMAS.items():
        schema = {"$schema": JSON_SCHEMA_DIALECT, **model.model_json_schema(mode="serialization")}
        rendered[name] = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
    return rendered


def main(argv: Sequence[str] | None = None) -> int:
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("--out", type=Path, required=True, help="the schemas/ directory")
    args.add_argument("--check", action="store_true", help="fail if committed files are stale")
    opts = args.parse_args(argv)

    if opts.check:
        stale = [
            name
            for name, text in render_schemas().items()
            if not (opts.out / name).is_file()
            or (opts.out / name).read_text(encoding="utf-8") != text
        ]
        if stale:
            print(f"Stale or missing: {', '.join(stale)}. Run: make schema", file=sys.stderr)
            return 1
        return 0

    opts.out.mkdir(parents=True, exist_ok=True)
    for name, text in render_schemas().items():
        (opts.out / name).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
