"""Perps configuration: venue costs and owner risk limits (ADR-025, UD-23).

No defaults exist here. Every value is either ``TBD`` (unresolved) or owner-approved with
an approver and a date. Any unresolved value makes the whole configuration unusable, and
callers exit 3 with the unresolved keys (handoff rule 3: never invent risk values).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trader.common.paths import configs_root as default_configs_root
from trader.profiles.loader import load_yaml


class PerpValue(BaseModel):
    """One configured number with its provenance."""

    model_config = ConfigDict(extra="forbid")

    value: Decimal | Literal["TBD"]
    status: Literal["unresolved", "approved"]
    ref: str
    approved_by: str | None = None
    approved_on: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> PerpValue:
        if (self.value == "TBD") != (self.status == "unresolved"):
            raise ValueError("status must be 'unresolved' if and only if the value is TBD")
        if self.status == "approved" and not (self.approved_by and self.approved_on):
            raise ValueError("approved values need approved_by and approved_on")
        return self


# The markets Jupiter Perps lists; a ``jupiter_perps`` file may name no other.
JUPITER_MARKETS = ("SOL", "ETH", "BTC")


class PerpMarketCfg(BaseModel):
    """A tradable perps market; a Jupiter market also names the mint its price is read from."""

    model_config = ConfigDict(extra="forbid")

    market: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,9}$")
    price_mint: str | None = Field(default=None, min_length=32, max_length=44)


class PerpsConfigFile(BaseModel):
    """Shape of a file under ``configs/perps/`` (one per paper account)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"]
    kind: Literal["PerpsConfig"]
    version: int = Field(ge=1)
    # ``generic_perps`` (ADR-051) models no particular venue: any coin with public candles,
    # at the costs the file states. It has no price mints because nothing is read on-chain.
    venue: Literal["jupiter_perps", "generic_perps"]
    # Reason: paper is the only mode; a live mode needs its own ADR and gates.
    mode: Literal["paper"]
    starting_collateral_usd: PerpValue
    markets: list[PerpMarketCfg] = Field(min_length=1)
    costs: dict[str, PerpValue]
    venue_limits: dict[str, PerpValue]
    risk: dict[str, PerpValue]

    @model_validator(mode="after")
    def _markets_fit_venue(self) -> PerpsConfigFile:
        names = [m.market for m in self.markets]
        if len(set(names)) != len(names):
            # Reason: a repeated market would silently collapse into one position slot.
            raise ValueError("markets must not repeat")
        for m in self.markets:
            if self.venue == "jupiter_perps":
                if m.market not in JUPITER_MARKETS:
                    raise ValueError(f"jupiter_perps lists only {JUPITER_MARKETS}, not {m.market}")
                if m.price_mint is None:
                    raise ValueError(f"jupiter_perps market {m.market} needs a price_mint")
            elif m.price_mint is not None:
                raise ValueError(f"generic_perps market {m.market} takes no price_mint")
        return self

    def price_mints(self) -> dict[str, str]:
        """Market to price mint, for the markets that have one (Jupiter files: all of them)."""
        return {m.market: m.price_mint for m in self.markets if m.price_mint is not None}


COST_KEYS = ("open_fee_bps", "close_fee_bps", "borrow_rate_pct_per_hour")
VENUE_KEYS = ("maintenance_bps", "venue_max_leverage")
RISK_KEYS = (
    "max_leverage",
    "target_leverage",
    "max_collateral_per_position_pct",
    "max_total_size_pct_of_equity",
    "min_liquidation_distance_pct",
    "max_open_positions",
    "daily_loss_limit_pct",
)


@dataclass(frozen=True)
class PerpsParams:
    """Resolved perps values. Only built when every value is approved."""

    version: int
    starting_collateral_usd: Decimal
    # Market to price mint, in the file's order (the order decisions are taken in); the mint
    # is "" for a ``generic_perps`` market.
    markets: dict[str, str]
    open_fee_bps: Decimal
    close_fee_bps: Decimal
    borrow_rate_pct_per_hour: Decimal
    maintenance_bps: Decimal
    venue_max_leverage: Decimal
    max_leverage: Decimal
    target_leverage: Decimal
    max_collateral_per_position_pct: Decimal
    max_total_size_pct_of_equity: Decimal
    min_liquidation_distance_pct: Decimal
    max_open_positions: int
    daily_loss_limit_pct: Decimal
    # Optional (ADR-032): when set, each new position's leverage is assessed from the
    # market's recent volatility, with ``target_leverage`` as the ceiling.
    liquidation_buffer_daily_moves: Decimal | None = None
    # ADR-038, required in every config file since ADR-042: a position closes once it has
    # lost this share of its collateral (fees included), and that market opens nothing more
    # until the next UTC day. ``resolve`` refuses a file without it (exit 3); None remains
    # only for parameters built in code (research replays).
    stop_loss_pct_of_collateral: Decimal | None = None
    # Optional (ADR-045, UD-32): a three-step take-profit ladder measured in R, the distance
    # from entry to the opening stop. Each entry is (level in R, % of the opening size
    # closed there); the last step closes whatever is left. TP1 moves the stop to breakeven
    # (fees covered), TP2 moves it to TP1. None means no ladder.
    take_profits: tuple[tuple[Decimal, Decimal], ...] | None = None
    # Optional (ADR-053): after a trade that lost money (fees included) closes, its market
    # opens nothing for this many hours, counted from the candle that closed it. None
    # means no cooldown.
    cooldown_after_loss_hours: Decimal | None = None


BUFFER_KEY = "liquidation_buffer_daily_moves"
STOP_KEY = "stop_loss_pct_of_collateral"
COOLDOWN_KEY = "cooldown_after_loss_hours"
# Reason: a wait longer than a week is almost certainly a typing mistake.
COOLDOWN_MAX_HOURS = Decimal(168)
DEFAULT_FILE = "jupiter.yaml"
# ADR-045: all five or none; the third level closes the rest of the position.
LADDER_KEYS = (
    "take_profit_1_r",
    "take_profit_1_close_pct",
    "take_profit_2_r",
    "take_profit_2_close_pct",
    "take_profit_3_r",
)


class PerpsConfigUnresolvedError(Exception):
    """Raised when any perps value is unresolved (exit 3)."""

    def __init__(self, keys: list[str], refs: list[str]) -> None:
        """
        Store what is missing.

        Args:
            keys (list[str]): Unresolved keys.
            refs (list[str]): Decision IDs that resolve them.
        """
        super().__init__(f"PERPS_CONFIG_UNRESOLVED: {', '.join(keys)} ({', '.join(refs)})")
        self.keys, self.refs = keys, refs


def load_perps_file(
    configs_root: Path | None = None, file_name: str = DEFAULT_FILE
) -> PerpsConfigFile:
    """
    Load and validate a perps configuration file.

    Args:
        configs_root (Path | None): Config root. Defaults to ``TRADER_CONFIGS_DIR``/``configs``.
        file_name (str): File under ``perps/``; each paper account has its own (ADR-038).

    Returns:
        PerpsConfigFile: Validated file.

    Raises:
        ValueError: If ``file_name`` is not a plain YAML file name.
    """
    if "/" in file_name or "\\" in file_name or not file_name.endswith(".yaml"):
        raise ValueError(f"perps config must be a plain .yaml file name, got {file_name!r}")
    raw: dict[str, Any] = load_yaml((configs_root or default_configs_root()) / "perps" / file_name)
    return PerpsConfigFile.model_validate(raw)


def resolve(cfg: PerpsConfigFile) -> PerpsParams:
    """
    Turn a validated file into parameters, failing closed on anything unresolved.

    Args:
        cfg (PerpsConfigFile): Validated file.

    Returns:
        PerpsParams: Parameters.

    Raises:
        PerpsConfigUnresolvedError: If any value is TBD or a required key is missing.
    """
    groups = {
        "costs": (cfg.costs, COST_KEYS),
        "venue_limits": (cfg.venue_limits, VENUE_KEYS),
        "risk": (cfg.risk, RISK_KEYS),
    }
    missing: list[str] = []
    refs: set[str] = set()
    values: dict[str, Decimal] = {}
    for group, (entries, keys) in groups.items():
        for k in keys:
            pv = entries.get(k)
            if pv is None or pv.value == "TBD":
                missing.append(f"{group}.{k}")
                refs.add(pv.ref if pv else "UD-23")
            else:
                values[k] = Decimal(pv.value)
    for key, top in ((BUFFER_KEY, None), (STOP_KEY, Decimal(100)), (COOLDOWN_KEY, None)):
        opt = cfg.risk.get(key)
        if opt is None:
            if key == STOP_KEY:
                # Reason: owner rule (2026-11-19, ADR-042): every perps account assesses a
                # stop-loss; an account without one fails closed instead of running unguarded.
                missing.append(f"risk.{key}")
                refs.add("UD-31")
            continue
        if opt.value == "TBD":
            missing.append(f"risk.{key}")
            refs.add(opt.ref)
        elif Decimal(opt.value) <= 0 or (top is not None and Decimal(opt.value) >= top):
            raise ValueError(f"risk.{key} must be positive" + (f" and below {top}" if top else ""))
        else:
            values[key] = Decimal(opt.value)
    if values.get(COOLDOWN_KEY, Decimal(0)) > COOLDOWN_MAX_HOURS:
        raise ValueError(f"risk.{COOLDOWN_KEY} must be at most {COOLDOWN_MAX_HOURS} hours")
    known = {*RISK_KEYS, *LADDER_KEYS, BUFFER_KEY, STOP_KEY, COOLDOWN_KEY}
    if unknown := sorted(set(cfg.risk) - known):
        # Reason: a misspelled optional key would otherwise switch its protection off
        # without a word; refuse the file instead (ADR-053).
        raise ValueError(f"unknown risk settings: {unknown}")
    ladder = _ladder(cfg, missing, refs, STOP_KEY in values)
    start = cfg.starting_collateral_usd
    if start.value == "TBD":
        missing.append("starting_collateral_usd")
        refs.add(start.ref)
    if missing:
        raise PerpsConfigUnresolvedError(missing, sorted(refs))
    if values["max_leverage"] > values["venue_max_leverage"]:
        raise ValueError("risk.max_leverage must not exceed venue_limits.venue_max_leverage")
    if not Decimal(1) <= values["target_leverage"] <= values["max_leverage"]:
        raise ValueError("risk.target_leverage must be between 1 and risk.max_leverage")
    return PerpsParams(
        version=cfg.version,
        starting_collateral_usd=Decimal(start.value),
        markets={m.market: m.price_mint or "" for m in cfg.markets},
        max_open_positions=int(values.pop("max_open_positions")),
        take_profits=ladder,
        **values,
    )


def _ladder(
    cfg: PerpsConfigFile, missing: list[str], refs: set[str], has_stop: bool
) -> tuple[tuple[Decimal, Decimal], ...] | None:
    """
    Read the optional take-profit ladder (ADR-045).

    Args:
        cfg (PerpsConfigFile): Validated file.
        missing (list[str]): Unresolved keys so far; a TBD ladder key is added here.
        refs (set[str]): Decision IDs that resolve them.
        has_stop (bool): Whether the stop resolved (the ladder is measured from it).

    Returns:
        tuple | None: ``((r1, pct1), (r2, pct2), (r3, rest))`` or None without a ladder.

    Raises:
        ValueError: If only some keys are present, or the values are not usable.
    """
    present = [k for k in LADDER_KEYS if k in cfg.risk]
    if not present:
        return None
    if len(present) != len(LADDER_KEYS):
        absent = sorted(set(LADDER_KEYS) - set(present))
        raise ValueError(f"take-profit ladder needs all of {LADDER_KEYS}; missing {absent}")
    pending = [k for k in LADDER_KEYS if cfg.risk[k].value == "TBD"]
    if pending:
        missing += [f"risk.{k}" for k in pending]
        refs.update(cfg.risk[k].ref for k in pending)
        return None
    v = {k: Decimal(cfg.risk[k].value) for k in LADDER_KEYS}
    r1, r2, r3 = v["take_profit_1_r"], v["take_profit_2_r"], v["take_profit_3_r"]
    p1, p2 = v["take_profit_1_close_pct"], v["take_profit_2_close_pct"]
    if not Decimal(0) < r1 < r2 < r3:
        raise ValueError("take-profit levels must be positive and increasing")
    if p1 <= 0 or p2 <= 0 or p1 + p2 >= 100:
        raise ValueError("take-profit close % must be positive and leave part for TP3")
    if not has_stop:
        # Reason: R is the distance to the opening stop; without a stop there is no R.
        raise ValueError("a take-profit ladder needs risk.stop_loss_pct_of_collateral")
    return ((r1, p1), (r2, p2), (r3, Decimal(100) - p1 - p2))


def load_perps_params(
    configs_root: Path | None = None, file_name: str = DEFAULT_FILE
) -> PerpsParams:
    """
    Load, validate, and resolve a perps configuration.

    Args:
        configs_root (Path | None): Config root.
        file_name (str): File under ``perps/`` (ADR-038).

    Returns:
        PerpsParams: Parameters.

    Raises:
        PerpsConfigUnresolvedError: If any value is unresolved.
    """
    return resolve(load_perps_file(configs_root, file_name))


def settings_summary(p: PerpsParams) -> dict[str, Any]:
    """
    The adjustable account settings, as text, for the read-only dashboard (ADR-038).

    Args:
        p (PerpsParams): Resolved parameters.

    Returns:
        dict[str, Any]: Version, collateral %, buffer, leverage cap, stop %, daily limit,
        take-profit ladder, cooldown; an optional setting that is off is None.
    """
    opt = (p.liquidation_buffer_daily_moves, p.stop_loss_pct_of_collateral)
    cooldown = p.cooldown_after_loss_hours
    return {
        "config_version": p.version,
        "collateral_pct": str(p.max_collateral_per_position_pct),
        "buffer_daily_moves": None if opt[0] is None else str(opt[0]),
        "max_leverage": str(p.target_leverage),
        "stop_pct_of_collateral": None if opt[1] is None else str(opt[1]),
        "daily_loss_limit_pct": str(p.daily_loss_limit_pct),
        "take_profits": None
        if p.take_profits is None
        else [{"at_r": str(r), "close_pct": str(pct)} for r, pct in p.take_profits],
        "cooldown_after_loss_hours": None if cooldown is None else str(cooldown),
    }
