"""Provenance-carrying risk parameter types (§7.3).

Each value may be the literal ``"TBD"`` (unresolved owner decision). Validators enforce:
``unresolved`` iff ``TBD``; ``approved`` needs approver and date; ``hypothesis`` refs are
``H-nn``; ``unresolved`` refs are ``UD-nn``.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Annotated, Any, Literal, Self

from pydantic import Field, model_validator

from .common import TBD, DomainModel

ParamStatus = Literal["approved", "hypothesis", "unresolved"]
DecisionRef = Annotated[str, Field(pattern=r"^(D|H|UD)-[0-9]{2}$")]
DateText = Annotated[str, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")]

_HYP = re.compile(r"^H-[0-9]{2}$")
_UD = re.compile(r"^UD-[0-9]{2}$")


class ParamBase(DomainModel):
    """Common provenance fields."""

    status: ParamStatus
    ref: DecisionRef
    approved_by: Annotated[str, Field(min_length=1)] | None = None
    approved_on: DateText | None = None
    note: str | None = None

    def is_tbd(self) -> bool:
        """
        Report whether this parameter's value is unresolved.

        Returns:
            bool: True when the value is ``TBD``.
        """
        raise NotImplementedError

    def resolved_value(self) -> Any:
        """
        Return the parameter's resolved value in plain form.

        Returns:
            Any: The value (scalar or dict).
        """
        raise NotImplementedError

    @model_validator(mode="after")
    def _provenance(self) -> Self:
        """
        Apply the provenance rules shared by every parameter type.

        Returns:
            ParamBase: The validated parameter.

        Raises:
            ValueError: If status, value, and ref are inconsistent.
        """
        tbd = self.is_tbd()
        if (self.status == "unresolved") != tbd:
            raise ValueError("status must be 'unresolved' if and only if the value is TBD")
        if self.status == "unresolved" and not _UD.match(self.ref):
            raise ValueError("unresolved values must reference UD-nn")
        if self.status == "hypothesis" and not _HYP.match(self.ref):
            raise ValueError("hypothesis values must reference H-nn")
        if self.status == "approved" and (self.approved_by is None or self.approved_on is None):
            raise ValueError("approved values need approved_by and approved_on")
        return self


class PctParam(ParamBase):
    """Percentage 0 < value <= 100."""

    value: TBD | Annotated[Decimal, Field(gt=0, le=100)]
    candidates_under_test: list[Annotated[Decimal, Field(gt=0, le=100)]] | None = None

    def is_tbd(self) -> bool:
        """Return True when unresolved."""
        return self.value == "TBD"

    def resolved_value(self) -> Any:
        """Return the value."""
        return self.value


class PctRangeParam(ParamBase):
    """Percentage range with low and high."""

    low: TBD | Annotated[Decimal, Field(ge=0, le=100)]
    high: TBD | Annotated[Decimal, Field(ge=0, le=100)]

    def is_tbd(self) -> bool:
        """Return True when either bound is unresolved."""
        return self.low == "TBD" or self.high == "TBD"

    def resolved_value(self) -> Any:
        """Return ``{"low": .., "high": ..}``."""
        return {"low": self.low, "high": self.high}


class CountParam(ParamBase):
    """Integer count >= 1."""

    value: TBD | Annotated[int, Field(ge=1, strict=True)]

    def is_tbd(self) -> bool:
        """Return True when unresolved."""
        return self.value == "TBD"

    def resolved_value(self) -> Any:
        """Return the value."""
        return self.value


class HoursParam(ParamBase):
    """Duration in hours > 0."""

    value: TBD | Annotated[Decimal, Field(gt=0)]

    def is_tbd(self) -> bool:
        """Return True when unresolved."""
        return self.value == "TBD"

    def resolved_value(self) -> Any:
        """Return the value."""
        return self.value


class SecondsParam(HoursParam):
    """Duration in seconds > 0."""


class MultiplierParam(ParamBase):
    """Multiplier >= 1."""

    value: TBD | Annotated[Decimal, Field(ge=1)]

    def is_tbd(self) -> bool:
        """Return True when unresolved."""
        return self.value == "TBD"

    def resolved_value(self) -> Any:
        """Return the value."""
        return self.value


class GenericParam(ParamBase):
    """Number >= 0 or a lower-case token (e.g. ``not_applicable``)."""

    value: TBD | Annotated[Decimal, Field(ge=0)] | Annotated[str, Field(pattern=r"^[a-z_]+$")]

    def is_tbd(self) -> bool:
        """Return True when unresolved."""
        return self.value == "TBD"

    def resolved_value(self) -> Any:
        """Return the value."""
        return self.value


class ChoiceParam(ParamBase):
    """Halt and liquidation policy choice (UD-19)."""

    value: Literal[
        "hold_unchanged",
        "flatten_all_at_market",
        "staged_derisking",
        "hold_with_owner_flatten_command",
        "TBD",
    ]

    def is_tbd(self) -> bool:
        """Return True when unresolved."""
        return self.value == "TBD"

    def resolved_value(self) -> Any:
        """Return the value."""
        return self.value


class StopPolicy(ParamBase):
    """Hard stop policy (UD-16)."""

    method: Literal["atr_multiple", "fixed_pct", "TBD"]
    timeframe: Literal["decision_timeframe"] | None = None
    atr_period_bars: TBD | Annotated[int, Field(ge=2)] | None = None
    atr_multiple: TBD | Annotated[Decimal, Field(gt=0)] | None = None
    fixed_pct: TBD | Annotated[Decimal, Field(gt=0, le=100)] | None = None

    def is_tbd(self) -> bool:
        """Return True when the method is unresolved."""
        return self.method == "TBD"

    def resolved_value(self) -> Any:
        """Return the stop policy fields."""
        out: dict[str, Any] = {"method": self.method}
        for k in ("timeframe", "atr_period_bars", "atr_multiple", "fixed_pct"):
            v = getattr(self, k)
            if v is not None:
                out[k] = v
        return out

    @model_validator(mode="after")
    def _method_fields(self) -> Self:
        """
        Require the inputs of the chosen method.

        Returns:
            StopPolicy: The validated policy.

        Raises:
            ValueError: If the chosen method's inputs are missing or TBD.
        """
        if self.method == "atr_multiple" and (
            not isinstance(self.atr_period_bars, int) or not isinstance(self.atr_multiple, Decimal)
        ):
            raise ValueError("atr_multiple needs atr_period_bars and atr_multiple")
        if self.method == "fixed_pct" and not isinstance(self.fixed_pct, Decimal):
            raise ValueError("fixed_pct needs fixed_pct")
        return self


class LossStep(DomainModel):
    """One loss-scaling step."""

    drawdown_fraction_of_breaker_below: Annotated[Decimal, Field(gt=0, le=1)]
    multiplier: Annotated[Decimal, Field(ge=0, le=1)]


class LossScalingSchedule(ParamBase):
    """Size-reduction schedule as drawdown grows (D-12 step 2, UD-15)."""

    method: Literal["stepwise_fraction_of_breaker", "linear_to_breaker", "TBD"]
    steps: Literal["TBD", "not_applicable"] | Annotated[list[LossStep], Field(min_length=1)]

    def is_tbd(self) -> bool:
        """Return True when the method or steps are unresolved."""
        return self.method == "TBD" or self.steps == "TBD"

    def resolved_value(self) -> Any:
        """Return ``{"method": .., "steps": ..}``."""
        steps: Any = self.steps
        if isinstance(steps, list):
            steps = [s.model_dump() for s in steps]
        return {"method": self.method, "steps": steps}
