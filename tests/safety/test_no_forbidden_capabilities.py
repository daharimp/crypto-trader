"""T-46: no withdrawal, transfer, margin, leverage, or live-order capability exists."""

from __future__ import annotations

import ast
from pathlib import Path

from trader.execution.adapters.registry import ALLOWED_ADAPTERS

SRC = Path(__file__).resolve().parents[2] / "src"
WORDS = ("withdraw", "transfer", "leverage", "margin", "create_order", "fetch_balance", "private_")
# Reason: the only permitted occurrences are the always-false *_allowed safety constants.
ALLOWED_NAMES = {"withdrawals_allowed", "transfers_allowed", "leverage_allowed", "margin_allowed"}


def _bad(name: str) -> bool:
    low = name.lower()
    return name not in ALLOWED_NAMES and any(w in low for w in WORDS)


def test_t46_ast_scan() -> None:
    """T-46: no definitions or calls with forbidden names; no apiKey/secret assignments."""
    problems: list[str] = []
    files = list(SRC.rglob("*.py"))
    assert len(files) > 50
    for f in files:
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if _bad(node.name):
                    problems.append(f"{f.name}: def {node.name}")
            elif isinstance(node, ast.Call):
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if _bad(name):
                    problems.append(f"{f.name}: call {name}")
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    tname = t.id if isinstance(t, ast.Name) else getattr(t, "attr", "")
                    if tname.lower() in ("apikey", "api_key", "secret"):
                        problems.append(f"{f.name}: assigns {tname}")
            elif isinstance(node, ast.Dict):
                for k in node.keys:
                    if isinstance(k, ast.Constant) and k.value in ("apiKey", "secret"):
                        problems.append(f"{f.name}: dict key {k.value}")
            elif isinstance(node, ast.Attribute) and _bad(node.attr):
                problems.append(f"{f.name}: attribute {node.attr}")
    assert problems == []


def test_t46_adapter_allowlist_is_simulated_only() -> None:
    """T-46: the adapter allowlist equals {'simulated'}."""
    assert ALLOWED_ADAPTERS == frozenset({"simulated"})


def test_t46_safety_constants_are_literal_false() -> None:
    """T-46: the *_allowed fields are Literal[False] in both contracts."""
    from trader.domain.profiles import Execution
    from trader.domain.risk_profile import GlobalHardConstraints

    for model in (Execution, GlobalHardConstraints):
        for name, field in model.model_fields.items():
            if name.endswith("_allowed") or name == "real_money_enabled":
                assert str(field.annotation) in ("typing.Literal[False]",), (name, field)
