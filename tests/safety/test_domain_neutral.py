"""T-47: ``trader.domain`` imports only the standard library and Pydantic (D-44)."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

DOMAIN = Path(__file__).resolve().parents[2] / "src" / "trader" / "domain"
ALLOWED_THIRD_PARTY = {"pydantic"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods.add(node.module.split(".")[0])
    return mods


def test_t47_domain_imports_only_stdlib_and_pydantic() -> None:
    """T-47: every absolute import is stdlib or pydantic; relative imports stay in domain."""
    files = list(DOMAIN.glob("*.py"))
    assert len(files) >= 15
    for f in files:
        for mod in _imports(f):
            assert mod in sys.stdlib_module_names or mod in ALLOWED_THIRD_PARTY, (f.name, mod)


def test_domain_has_no_relative_escape() -> None:
    """Edge: no ``from ..`` imports reach outside the domain package."""
    for f in DOMAIN.glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert node.level <= 1, f.name
