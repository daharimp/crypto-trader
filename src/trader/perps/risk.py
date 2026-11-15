"""Deterministic perps risk checks and sizing (ADR-025).

Strategies only say long, short, or flat. This module alone decides whether a position may
open and how large it is, from owner-approved limits (UD-23). A rejection lists every
failed rule so the journal shows why.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal

from .math import PerpSide, fee_usd, leverage_for_buffer, liquidation_price
from .params import PerpsParams

HUNDRED = Decimal(100)


@dataclass(frozen=True)
class AccountView:
    """What the risk checks need to know about the paper account."""

    free_cash_usd: Decimal
    equity_usd: Decimal
    day_start_equity_usd: Decimal
    open_markets: frozenset[str]
    gross_size_usd: Decimal
    halted: bool


@dataclass(frozen=True)
class OpenProposal:
    """A sized proposal to open a position."""

    market: str
    side: PerpSide
    collateral_usd: Decimal
    size_usd: Decimal
    entry_price: Decimal
    liquidation_price: Decimal
    leverage: Decimal = Decimal(0)


@dataclass(frozen=True)
class PerpRiskDecision:
    """Approve or reject an open, with reasons."""

    approved: bool
    proposal: OpenProposal | None
    reasons: list[str] = field(default_factory=list)


def opening_leverage(params: PerpsParams, daily_move: Decimal | None) -> Decimal:
    """
    Leverage for a new position: fixed, or assessed from the market's volatility.

    Without ``liquidation_buffer_daily_moves`` every position opens at the owner's target
    leverage. With it, the leverage is the one that keeps liquidation that many typical
    daily moves away, never above the target leverage; when the volatility is unknown the
    answer is 0, which sizes the position to nothing so the open is refused (fail closed).

    Args:
        params (PerpsParams): Resolved parameters.
        daily_move (Decimal | None): The market's typical daily move as a fraction.

    Returns:
        Decimal: Leverage, or 0 when it cannot be assessed.
    """
    if params.liquidation_buffer_daily_moves is None:
        return params.target_leverage
    if daily_move is None or daily_move <= 0:
        return Decimal(0)
    return leverage_for_buffer(
        daily_move,
        params.liquidation_buffer_daily_moves,
        params.close_fee_bps,
        params.maintenance_bps,
        params.target_leverage,
    )


def size_open(
    params: PerpsParams,
    account: AccountView,
    market: str,
    side: PerpSide,
    mark: Decimal,
    daily_move: Decimal | None = None,
) -> OpenProposal:
    """
    Size a new position deterministically.

    Collateral is the per-position cap applied to equity, limited by free cash after the
    opening fee; size is collateral times the opening leverage (see ``opening_leverage``).

    Args:
        params (PerpsParams): Resolved parameters.
        account (AccountView): Account state.
        market (str): Market, e.g. ``SOL``.
        side (PerpSide): Direction.
        mark (Decimal): Current mark price used as the entry price.
        daily_move (Decimal | None): The market's typical daily move as a fraction; needed
            only when leverage is assessed from volatility.

    Returns:
        OpenProposal: Proposal (may still fail the checks).
    """
    lev = opening_leverage(params, daily_move)
    cap = account.equity_usd * params.max_collateral_per_position_pct / HUNDRED
    # Reason: the opening fee is charged on size, so leave room for it in free cash.
    fee_share = lev * params.open_fee_bps / Decimal(10_000)
    affordable = account.free_cash_usd / (1 + fee_share)
    # Reason: round down so rounding can never push collateral past the cap or free cash.
    collateral = max(min(cap, affordable), Decimal(0)).quantize(Decimal("0.01"), ROUND_DOWN)
    size = (collateral * lev).quantize(Decimal("0.01"), ROUND_DOWN)
    liq = (
        liquidation_price(
            side, size, collateral, mark, params.close_fee_bps, Decimal(0), params.maintenance_bps
        )
        if size > 0
        else Decimal(0)
    )
    return OpenProposal(market, side, collateral, size, mark, liq, lev)


def check_open(
    params: PerpsParams, account: AccountView, proposal: OpenProposal
) -> PerpRiskDecision:
    """
    Apply every perps open rule.

    Args:
        params (PerpsParams): Resolved parameters.
        account (AccountView): Account state.
        proposal (OpenProposal): Sized proposal.

    Returns:
        PerpRiskDecision: Decision with every failed rule.
    """
    r: list[str] = []
    p = proposal
    if account.halted:
        r.append("PERP_KILL_SWITCH_ENGAGED")
    if p.market not in params.markets:
        r.append("PERP_MARKET_NOT_ALLOWED")
    if p.market in account.open_markets:
        r.append("PERP_POSITION_ALREADY_OPEN")
    if len(account.open_markets) >= params.max_open_positions:
        r.append("PERP_MAX_OPEN_POSITIONS")
    day_loss = account.day_start_equity_usd - account.equity_usd
    if day_loss >= account.day_start_equity_usd * params.daily_loss_limit_pct / HUNDRED:
        r.append("PERP_DAILY_LOSS_LIMIT")
    if params.liquidation_buffer_daily_moves is not None and p.leverage <= 0:
        r.append("PERP_VOLATILITY_UNAVAILABLE")
        return PerpRiskDecision(False, None, r)
    if p.collateral_usd <= 0 or p.size_usd <= 0:
        r.append("PERP_NO_COLLATERAL_AVAILABLE")
        return PerpRiskDecision(False, None, r)
    if p.size_usd / p.collateral_usd > params.max_leverage:
        r.append("PERP_LEVERAGE_ABOVE_MAX")
    if p.collateral_usd > account.equity_usd * params.max_collateral_per_position_pct / HUNDRED:
        r.append("PERP_COLLATERAL_ABOVE_CAP")
    if p.collateral_usd + fee_usd(p.size_usd, params.open_fee_bps) > account.free_cash_usd:
        r.append("PERP_INSUFFICIENT_FREE_CASH")
    gross = account.gross_size_usd + p.size_usd
    if gross > account.equity_usd * params.max_total_size_pct_of_equity / HUNDRED:
        r.append("PERP_TOTAL_SIZE_ABOVE_CAP")
    distance = abs(p.entry_price - p.liquidation_price) / p.entry_price * HUNDRED
    if distance < params.min_liquidation_distance_pct:
        r.append("PERP_LIQUIDATION_TOO_CLOSE")
    return PerpRiskDecision(not r, p if not r else None, r)
