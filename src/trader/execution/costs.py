"""Cost scenario parameters (RECOMMENDATION R-10)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CostParams:
    """Fee, slippage, and minimum notional applied to every simulated fill."""

    scenario_id: str
    fee_rate_pct: Decimal
    slippage_bps: Decimal
    min_notional_usd: Decimal
    # Order style for entries and strategy exits: "market" (taker) or "limit" (post-only
    # maker, one bar, offset below/above the last close). Protective stops stay stop-market.
    order_style: str = "market"
    maker_fee_rate_pct: Decimal | None = None
    limit_offset_bps: Decimal = Decimal(0)

    @property
    def maker_fee_rate(self) -> Decimal:
        """
        Maker fee as a fraction (falls back to the taker fee).

        Returns:
            Decimal: e.g. 0.0025 for 0.25%.
        """
        pct = self.maker_fee_rate_pct if self.maker_fee_rate_pct is not None else self.fee_rate_pct
        return pct / Decimal(100)

    @property
    def fee_rate(self) -> Decimal:
        """
        Fee as a fraction.

        Returns:
            Decimal: e.g. 0.004 for 0.40%.
        """
        return self.fee_rate_pct / Decimal(100)

    @property
    def slippage(self) -> Decimal:
        """
        Slippage as a fraction.

        Returns:
            Decimal: e.g. 0.001 for 10 bps.
        """
        return self.slippage_bps / Decimal(10000)

    @classmethod
    def from_scenario(cls, scenario: dict[str, str]) -> CostParams:
        """
        Build from a compiled cost scenario mapping.

        Args:
            scenario (dict[str, str]): ``CompiledProfile.cost_scenario``.

        Returns:
            CostParams: Parameters.
        """
        return cls(
            scenario_id=scenario["scenario_id"],
            fee_rate_pct=Decimal(scenario["fee_rate_pct"]),
            slippage_bps=Decimal(scenario["slippage_bps"]),
            min_notional_usd=Decimal(scenario["min_notional_usd"]),
            order_style=scenario.get("order_style", "market"),
            maker_fee_rate_pct=(
                Decimal(scenario["maker_fee_rate_pct"])
                if "maker_fee_rate_pct" in scenario
                else None
            ),
            limit_offset_bps=Decimal(scenario.get("limit_offset_bps", "0")),
        )
