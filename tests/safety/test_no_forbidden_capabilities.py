"""T-46 (amended by ADR-023): spot only; no withdrawal, transfer, margin, or leverage paths.

Real orders exist only in the Kraken live adapter; credentials are read only in the Kraken
client factory. Everything else in ``src/`` must not place orders or touch keys.
"""

from __future__ import annotations

import ast
from pathlib import Path

from trader.execution.adapters.kraken_live import _ALLOWED_PARAMS
from trader.execution.adapters.registry import ALLOWED_ADAPTERS

SRC = Path(__file__).resolve().parents[2] / "src"
NEVER = ("withdraw", "transfer", "leverage", "margin", "private_")
ORDER_CALLS = ("create_order", "fetch_balance")
LIVE_ADAPTER = SRC / "trader" / "execution" / "adapters" / "kraken_live.py"
KEY_FACTORY = SRC / "trader" / "session" / "market_data.py"
# Files on the credential path: read from environment variables -> pass to KEY_FACTORY.
KEY_PATH = {
    KEY_FACTORY,
    SRC / "trader" / "session" / "config.py",
    SRC / "trader" / "session" / "factory.py",
    SRC / "trader" / "cli" / "live.py",
}
# Reason: the only permitted occurrences are the always-false *_allowed safety constants.
ALLOWED_NAMES = {"withdrawals_allowed", "transfers_allowed", "leverage_allowed", "margin_allowed"}


def _names(node: ast.AST) -> list[str]:
    """Identifier-like names a node defines, calls, assigns, or accesses."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, ast.Call):
        fn = node.func
        return [fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    if isinstance(node, ast.Name):
        return [node.id]
    return []


def test_t46_ast_scan() -> None:
    """No margin/leverage/withdraw/transfer anywhere; orders and keys only where allowed."""
    problems: list[str] = []
    files = list(SRC.rglob("*.py"))
    assert len(files) > 60
    for f in files:
        for node in ast.walk(ast.parse(f.read_text())):
            for name in _names(node):
                low = name.lower()
                if name not in ALLOWED_NAMES and any(w in low for w in NEVER):
                    problems.append(f"{f.name}: {name}")
                if any(w in low for w in ORDER_CALLS) and f != LIVE_ADAPTER:
                    problems.append(f"{f.name}: order/balance call {name} outside live adapter")
                if name in ("apiKey", "secret", "api_key", "api_secret") and f not in KEY_PATH:
                    problems.append(f"{f.name}: credential access {name}")
            if (
                isinstance(node, ast.Attribute)
                and node.attr in ("apiKey", "secret")
                and f != KEY_FACTORY
            ):
                problems.append(f"{f.name}: sets client credential {node.attr}")
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and (
                    node.value.startswith(("API-Key", "API-Sign"))
                    or len(node.value) > 60
                    and node.value.isalnum()
                )
            ):
                problems.append(f"{f.name}: possible hard-coded credential")
            if isinstance(node, ast.Dict):
                for k in node.keys:
                    if isinstance(k, ast.Constant) and k.value in (
                        "apiKey",
                        "secret",
                        "leverage",
                        "margin",
                    ):
                        problems.append(f"{f.name}: dict key {k.value}")
    assert problems == []


def test_t46_adapter_allowlist() -> None:
    """T-46: exactly the simulator and the Kraken live adapter."""
    assert ALLOWED_ADAPTERS == frozenset({"simulated", "kraken_live"})


def test_live_adapter_parameter_allowlist_is_spot_only() -> None:
    """The live adapter can send only these Kraken parameters (no margin/leverage)."""
    assert frozenset({"oflags", "userref", "stopLossPrice", "validate"}) == _ALLOWED_PARAMS


def test_t46_safety_constants() -> None:
    """Leverage, margin, shorting, withdrawals, transfers stay Literal[False] in both contracts;
    real_money_enabled is a validated switch tied to the live environment."""
    from trader.domain.profiles import Execution
    from trader.domain.risk_profile import GlobalHardConstraints

    for model in (Execution, GlobalHardConstraints):
        for name, field in model.model_fields.items():
            if name.endswith("_allowed"):
                assert str(field.annotation) == "typing.Literal[False]", (name, field)
    assert Execution.model_fields["real_money_enabled"].annotation is bool
