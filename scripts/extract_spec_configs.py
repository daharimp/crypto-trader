"""Split the multi-document spec YAML files into schemas and configs (handoff §6.1).

Usage:
    uv run python scripts/extract_spec_configs.py [--spec docs/spec] [--root .]

Documents are copied as raw text so comments and decision references are preserved.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

_SEP = re.compile(r"^---[ \t]*$", re.MULTILINE)


def split_documents(text: str) -> list[str]:
    """
    Split YAML text into its documents, dropping the comment-only preamble.

    Args:
        text (str): Raw multi-document YAML.

    Returns:
        list[str]: Raw text of each non-empty document.
    """
    parts = _SEP.split(text)
    docs = [p.strip("\n") + "\n" for p in parts]
    return [d for d in docs if yaml.safe_load(d) is not None]


def extract(spec_dir: Path, root: Path) -> list[Path]:
    """
    Write schema and config files from the spec documents.

    Args:
        spec_dir (Path): Directory holding the specification package.
        root (Path): Repository root to write into.

    Returns:
        list[Path]: Files written.

    Raises:
        ValueError: If a document's ``kind`` or ID is not what the spec says.
    """
    plan = {
        "trading-profile.schema.yaml": [
            "schemas/trading-profile.schema.yaml",
            "configs/profiles/balanced-paper.yaml",
        ],
        "risk-profile.schema.yaml": [
            "schemas/risk-profile.schema.yaml",
            "configs/risk/conservative.yaml",
            "configs/risk/balanced.yaml",
            "configs/risk/aggressive.yaml",
        ],
    }
    written: list[Path] = []
    for src, targets in plan.items():
        docs = split_documents((spec_dir / src).read_text(encoding="utf-8"))
        if len(docs) != len(targets):
            raise ValueError(f"{src}: expected {len(targets)} documents, found {len(docs)}")
        for doc, target in zip(docs, targets, strict=True):
            data = yaml.safe_load(doc)
            stem = Path(target).name.split(".")[0]
            if target.startswith("configs/risk/") and data.get("risk_profile_id") != stem:
                raise ValueError(f"{target}: risk_profile_id is {data.get('risk_profile_id')}")
            out = root / target
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(doc, encoding="utf-8")
            written.append(out)
    return written


def main() -> None:
    """Parse arguments and run the extraction."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", type=Path, default=Path("docs/spec"))
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--force", action="store_true", help="Overwrite existing files.")
    args = ap.parse_args()
    # Reason: the spec documents hold the original all-TBD values; overwriting configs/ would
    # silently discard the owner's approved decisions (product-requirements.md section 10.2).
    existing = [t for t in ("configs/risk/balanced.yaml", "configs/profiles/balanced-paper.yaml")
                if (args.root / t).exists()]
    if existing and not args.force:
        raise SystemExit(f"refusing to overwrite owner-approved configs {existing}; use --force")
    for p in extract(args.spec, args.root):
        print(p)


if __name__ == "__main__":
    main()
