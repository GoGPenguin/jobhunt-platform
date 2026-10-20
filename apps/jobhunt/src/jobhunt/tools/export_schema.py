"""Write or check the committed JSON Schemas in schemas/.

The schemas are the contract other components and people read: stored data in its output
shape, config files in their input shape. `make schema` writes them; `make check` fails if
they are stale.

    python -m jobhunt.tools.export_schema --out ../../schemas [--check]
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from jobhunt.domain.dead_letter import DeadLetter
from jobhunt.domain.job import Job
from jobhunt.profile.aliases import SkillAliasesFile
from jobhunt.sources.config import SourcesConfig

JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
# Stored data is described as serialized (every field present); config people write is
# described as input (defaults optional, YAML key names).
SCHEMAS: dict[str, tuple[type[BaseModel], Literal["serialization", "validation"]]] = {
    "job.v1.json": (Job, "serialization"),
    "dead_letter.v1.json": (DeadLetter, "serialization"),
    "sources.v1.json": (SourcesConfig, "validation"),
    "skill_aliases.v1.json": (SkillAliasesFile, "validation"),
}


def render_schemas() -> dict[str, str]:
    """File name -> schema text, exactly as committed."""
    rendered = {}
    for name, (model, mode) in SCHEMAS.items():
        schema = {"$schema": JSON_SCHEMA_DIALECT, **model.model_json_schema(mode=mode)}
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
