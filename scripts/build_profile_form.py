"""Build docs/profile-builder/index.html from the template and the live question bank.

Run after changing the question bank, strategies, or assets:
``uv run python scripts/build_profile_form.py``. A test fails if the page is out of date.
"""

from __future__ import annotations

import json
from pathlib import Path

from trader.profiles.builder import registry_coins, runnable_strategies
from trader.profiles.questions import bank_json

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "docs" / "profile-builder" / "template.html"
OUT = ROOT / "docs" / "profile-builder" / "index.html"
MARK = "/*BANK*/null/*END*/"


def render(configs: Path = ROOT / "configs") -> str:
    """
    The form with the bank embedded.

    Args:
        configs (Path): Configuration directory.

    Returns:
        str: HTML.
    """
    bank = bank_json(runnable_strategies(configs), registry_coins(configs))
    # Reason: "</" inside JSON could close the <script> element early.
    data = json.dumps(bank, default=str, separators=(",", ":")).replace("</", "<\\/")
    return TEMPLATE.read_text().replace(MARK, data)


if __name__ == "__main__":
    OUT.write_text(render())
    print(f"wrote {OUT}")
