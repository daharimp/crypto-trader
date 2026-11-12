"""Release-time changelog builder: folds per-PR notes into CHANGELOG.md."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from build_changelog import fold, read_notes  # noqa: E402

LOG = (
    "# Changelog\n\n## [Unreleased]\n\n### Added\n- old thing\n\n## [0.1.0]\n\n### Added\n- first\n"
)


def _note(folder: Path, name: str, text: str) -> None:
    folder.mkdir(exist_ok=True)
    (folder / name).write_text(text)


def test_notes_are_appended_under_matching_headings_and_new_ones_created(tmp_path: Path) -> None:
    ch = tmp_path / "changes"
    _note(ch, "b.md", "### Fixed\n- a fix\n")
    _note(ch, "a.md", "### Added\n- new thing\n  wrapped line\n")
    _note(ch, "README.md", "ignored")
    notes, files = read_notes(ch)
    assert [f.name for f in files] == ["a.md", "b.md"]
    out = fold(LOG, notes)
    assert "- old thing\n- new thing\n  wrapped line\n" in out
    assert out.index("### Fixed\n- a fix") < out.index("## [0.1.0]")
    assert out.count("- first") == 1 and out.endswith("- first\n")


def test_no_notes_leaves_the_changelog_unchanged(tmp_path: Path) -> None:
    (tmp_path / "changes").mkdir()
    notes, files = read_notes(tmp_path / "changes")
    assert files == [] and fold(LOG, notes) == LOG


@pytest.mark.parametrize("text", ["- bullet without heading\n", "### Removed\n- x\n"])
def test_malformed_notes_are_rejected(tmp_path: Path, text: str) -> None:
    _note(tmp_path / "changes", "bad.md", text)
    with pytest.raises(ValueError, match="bad.md"):
        read_notes(tmp_path / "changes")


def test_changelog_without_unreleased_section_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unreleased"):
        fold("# Changelog\n", {"Added": ["- x"], "Changed": [], "Fixed": []})


def test_script_folds_and_deletes_notes(tmp_path: Path) -> None:
    (tmp_path / "CHANGELOG.md").write_text(LOG)
    _note(tmp_path / "changes", "x.md", "### Changed\n- changed thing\n")
    script = ROOT / "scripts" / "build_changelog.py"
    r = subprocess.run(  # noqa: S603
        [sys.executable, str(script), "--root", str(tmp_path)], capture_output=True, text=True
    )
    assert r.returncode == 0 and "folded 1 note" in r.stdout
    assert "### Changed\n- changed thing" in (tmp_path / "CHANGELOG.md").read_text()
    assert not (tmp_path / "changes" / "x.md").exists()


def test_repository_notes_are_well_formed() -> None:
    read_notes(ROOT / "changes")  # raises on a malformed note in this repository
