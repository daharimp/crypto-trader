"""Deployment config stays safe (ADR-023, ADR-026, ADR-036).

The dashboard stays private and read-only, and every service runs the one shared image.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
SHARED_IMAGE = "crypto-trader:local"


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


def test_perps_service_is_paper_practice_with_no_ports() -> None:
    perps = _compose()["services"]["perps"]
    assert perps["command"] == ["perps", "paper", "run"]
    assert "ports" not in perps and "profiles" not in perps


def _image_problems(compose: dict[str, Any]) -> list[str]:
    """Why some service could run older code than the others after `docker compose build`.

    Args:
        compose: The parsed compose file.

    Returns:
        One message per problem; empty when every service runs the shared image.
    """
    services: dict[str, dict[str, Any]] = compose["services"]
    problems = [
        f"{name}: image {svc.get('image')!r}, pull_policy {svc.get('pull_policy')!r}"
        for name, svc in services.items()
        if svc.get("image") != SHARED_IMAGE or svc.get("pull_policy") != "never"
    ]
    builders = [name for name, svc in services.items() if "build" in svc]
    if len(builders) != 1:
        problems.append(f"expected exactly one service with build, found {builders}")
    # Reason: a plain `docker compose build` skips profile-gated services (found 2026-11-14,
    # when `cli` still ran pre-perps code), so the one build must sit on an ungated service.
    problems += [
        f"{name}: build is behind profiles" for name in builders if "profiles" in services[name]
    ]
    return problems


def test_every_service_runs_the_one_shared_image() -> None:
    compose = _compose()
    assert _image_problems(compose) == []
    assert {"paper", "perps", "dashboard", "live", "cli", "builder"} <= set(compose["services"])
    assert "build" in compose["services"]["paper"]


def test_old_per_service_image_layout_is_rejected() -> None:
    # Reason: the layout before ADR-036; each service got its own crypto-trader-<name> image.
    old = {"services": {"paper": {"build": "."}, "cli": {"build": ".", "profiles": ["cli"]}}}
    problems = _image_problems(old)
    assert any(p.startswith("cli: image None") for p in problems)
    assert any("exactly one service with build" in p for p in problems)


def test_build_on_a_profile_gated_service_is_rejected() -> None:
    gated = {
        "services": {
            "cli": {
                "image": SHARED_IMAGE,
                "pull_policy": "never",
                "build": ".",
                "profiles": ["cli"],
            }
        }
    }
    assert _image_problems(gated) == ["cli: build is behind profiles"]


def test_shared_image_is_never_pulled_from_a_registry() -> None:
    compose = _compose()
    compose["services"]["live"]["pull_policy"] = "missing"
    assert _image_problems(compose) == ["live: image 'crypto-trader:local', pull_policy 'missing'"]


def test_only_the_builder_may_write_configs() -> None:
    for name, svc in _compose()["services"].items():
        config_mounts = [v for v in svc["volumes"] if v.split(":")[1] == "/app/configs"]
        assert len(config_mounts) == 1, name
        assert config_mounts[0].endswith(":ro") == (name != "builder"), name
