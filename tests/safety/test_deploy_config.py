"""Deployment config stays safe (ADR-023, ADR-026): dashboard private and read-only."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _compose() -> dict:  # type: ignore[type-arg]
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text())


def test_dashboard_publishes_on_localhost_only() -> None:
    dash = _compose()["services"]["dashboard"]
    assert dash["ports"] == ["127.0.0.1:8787:8787"]
    assert dash["command"][:2] == ["ui", "serve"]


def test_dashboard_mounts_are_read_only() -> None:
    vols = _compose()["services"]["dashboard"]["volumes"]
    assert vols and all(v.endswith(":ro") for v in vols)


def test_live_service_needs_explicit_profile_and_project_is_named() -> None:
    c = _compose()
    assert c["services"]["live"]["profiles"] == ["live"]
    assert c["name"] == "crypto-trader"
    assert "ports" not in c["services"]["paper"]


def test_ui_static_files_ship_in_the_package() -> None:
    static = resources.files("trader.ui").joinpath("static")
    assert static.joinpath("index.html").is_file()
    assert static.joinpath("vendor/lightweight-charts-4.2.0.js").is_file()
    assert static.joinpath("vendor/LIGHTWEIGHT-CHARTS-LICENSE.txt").is_file()


def _copied_before_sync() -> set[str]:
    """Files the Dockerfile copies into /app before its first `uv sync`."""
    files: set[str] = set()
    for line in (ROOT / "Dockerfile").read_text().splitlines():
        if line.startswith("RUN") and "uv sync" in line:
            return files
        if line.startswith("COPY "):
            files.update(line.split()[1:-1])
    raise AssertionError("Dockerfile has no `uv sync` step")


def test_docker_build_has_every_file_package_metadata_needs() -> None:
    # Reason: hatchling reads the readme and license files while building the project; a
    # missing one fails `docker compose build` on the server (found 2026-11-12).
    import tomllib

    meta = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    needed = {"pyproject.toml", "uv.lock", meta["readme"], meta["license"]["file"]}
    assert needed <= _copied_before_sync()
    assert all((ROOT / f).is_file() for f in needed)
