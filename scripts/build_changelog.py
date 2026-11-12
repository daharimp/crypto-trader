"""Fold the per-pull-request notes in ``changes/`` into ``CHANGELOG.md`` (release-time tool).

Each note is a Markdown file with one or more ``### Added|Changed|Fixed`` headings followed
by bullets. Bullets are appended under the matching heading of the ``## [Unreleased]``
section (the heading is created if missing) and the note files are deleted.

Usage: uv run python scripts/build_changelog.py [--root .]
"""

from __future__ import annotations

import argparse
from pathlib import Path

KINDS = ("Added", "Changed", "Fixed")
UNRELEASED = "## [Unreleased]"


def read_notes(folder: Path) -> tuple[dict[str, list[str]], list[Path]]:
    """
    Collect bullets per kind from every note file, in file-name order.

    Args:
        folder (Path): The ``changes`` folder.

    Returns:
        tuple[dict[str, list[str]], list[Path]]: Lines per kind, and the files read.

    Raises:
        ValueError: If a note has text before its first heading or an unknown heading.
    """
    out: dict[str, list[str]] = {k: [] for k in KINDS}
    files = sorted(p for p in folder.glob("*.md") if p.name != "README.md")
    for f in files:
        kind = None
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.startswith("### "):
                kind = line[4:].strip()
                if kind not in KINDS:
                    raise ValueError(f"{f.name}: unknown heading {line!r}")
            elif line.strip():
                if kind is None:
                    raise ValueError(f"{f.name}: text before a '### Added|Changed|Fixed' heading")
                out[kind].append(line)
    return out, files


def fold(changelog: str, notes: dict[str, list[str]]) -> str:
    """
    Insert the notes into the Unreleased section of the changelog text.

    Args:
        changelog (str): Current ``CHANGELOG.md`` text.
        notes (dict[str, list[str]]): Lines per kind.

    Returns:
        str: Updated text.

    Raises:
        ValueError: If the changelog has no ``## [Unreleased]`` section.
    """
    lines = changelog.splitlines()
    if UNRELEASED not in lines:
        raise ValueError(f"CHANGELOG.md has no '{UNRELEASED}' section")
    start = lines.index(UNRELEASED)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    for kind in KINDS:
        if not notes[kind]:
            continue
        head = f"### {kind}"
        section = lines[start:end]
        if head in section:
            at = start + section.index(head) + 1
            # Reason: append after the heading's existing bullets, before the next heading.
            while at < end and not lines[at].startswith("#") and lines[at].strip():
                at += 1
            new = notes[kind]
        else:
            at, new = end, [head, *notes[kind], ""]
            if lines[end - 1].strip():
                new = ["", *new]
        lines[at:at] = new
        end += len(new)
    return "\n".join(lines) + "\n"


def main() -> None:
    """Fold the notes and delete the note files."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path("."))
    root = ap.parse_args().root
    notes, files = read_notes(root / "changes")
    if not files:
        print("no change notes to fold")
        return
    path = root / "CHANGELOG.md"
    path.write_text(fold(path.read_text(encoding="utf-8"), notes), encoding="utf-8")
    for f in files:
        f.unlink()
    print(f"folded {len(files)} note(s) into {path}")


if __name__ == "__main__":
    main()
