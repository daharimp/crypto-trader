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
        )
