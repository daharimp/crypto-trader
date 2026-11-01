"""Run controls (§7.8): kill switch, circuit breaker, daily lockout, cooldowns.

Automated callers can only engage the kill switch; disengaging requires the owner (D-35).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from trader.common.clock import next_utc_midnight
from trader.common.opstore import OperationalStore
from trader.domain.enums import EventType
from trader.domain.killswitch import KillSwitchState


class KillSwitchError(PermissionError):
    """Raised on a disallowed kill-switch transition."""


@dataclass
class KillSwitch:
    """Run-scoped, in-memory kill switch (backtests)."""

    engaged: bool = False
    reason: str | None = None
    trigger: str | None = None

    def engage(self, reason: str, trigger: str | None = None) -> bool:
        """
        Engage the switch.

        Args:
            reason (str): Why.
            trigger (str | None): Auto-engage trigger name, if automated.

        Returns:
            bool: True if the state changed.
        """
        changed = not self.engaged
        self.engaged, self.reason, self.trigger = True, reason, trigger
        return changed

    def disengage(self, reason: str, by_owner: bool = False) -> None:
        """
        Disengage the switch. Only the owner may do this.

        Args:
            reason (str): Why.
            by_owner (bool): Must be True.

        Raises:
            KillSwitchError: If not called by the owner or without a reason.
        """
        if not by_owner or not reason.strip():
            raise KillSwitchError("only the owner may disengage, with a reason")
        self.engaged, self.reason, self.trigger = False, reason, None


@dataclass
class CircuitBreaker:
    """Latched drawdown circuit breaker (D-12 step 4). Only an owner reset reopens."""

    open: bool = False
    opened_at: datetime | None = None

    def trip(self, t: datetime) -> bool:
        """
        Open the breaker.

        Args:
            t (datetime): Time.

        Returns:
            bool: True if it was closed before.
        """
        if self.open:
            return False
        self.open, self.opened_at = True, t
        return True

    def reset(self, reason: str, by_owner: bool = False) -> None:
        """
        Reset the breaker (owner command with reason).

        Args:
            reason (str): Why.
            by_owner (bool): Must be True.

        Raises:
            KillSwitchError: If not called by the owner.
        """
        if not by_owner or not reason.strip():
            raise KillSwitchError("only the owner may reset the breaker, with a reason")
        self.open, self.opened_at = False, None


@dataclass
class DailyLockout:
    """Blocks new entries until the next 00:00 UTC after the daily loss limit is hit."""

    until: datetime | None = None

    def active(self, t: datetime) -> bool:
        """
        Whether the lockout is active at ``t``.

        Args:
            t (datetime): Time.

        Returns:
            bool: True if locked out.
        """
        return self.until is not None and t < self.until

    def start(self, t: datetime) -> datetime:
        """
        Start a lockout until the next UTC midnight.

        Args:
            t (datetime): Time the limit was reached.

        Returns:
            datetime: Lockout end.
        """
        self.until = next_utc_midnight(t)
        return self.until


@dataclass
class Cooldowns:
    """Consecutive-loss cooldowns per ``strategy_id|instrument_id``."""

    losses: dict[str, int] = field(default_factory=dict)
    until: dict[str, datetime] = field(default_factory=dict)

    @staticmethod
    def key(strategy_id: str, instrument_id: str) -> str:
        """
        Build the cooldown key.

        Args:
            strategy_id (str): Strategy.
            instrument_id (str): Instrument.

        Returns:
            str: ``strategy|instrument``.
        """
        return f"{strategy_id}|{instrument_id}"

    def active(self, key: str, t: datetime) -> bool:
        """
        Whether a cooldown is active.

        Args:
            key (str): Cooldown key.
            t (datetime): Time.

        Returns:
            bool: True if active.
        """
        u = self.until.get(key)
        return u is not None and t < u

    def record_exit(
        self, key: str, pnl: Decimal, t: datetime, count: int, hours: Decimal
    ) -> datetime | None:
        """
        Record a closed trade; start a cooldown after ``count`` consecutive losses.

        Args:
            key (str): Cooldown key.
            pnl (Decimal): Realized PnL after fees.
            t (datetime): Exit time.
            count (int): Threshold (UD-17).
            hours (Decimal): Duration (UD-17).

        Returns:
            datetime | None: Cooldown end if one started.
        """
        if pnl >= 0:
            self.losses[key] = 0
            return None
        self.losses[key] = self.losses.get(key, 0) + 1
        if self.losses[key] >= count:
            self.losses[key] = 0
            self.until[key] = t + timedelta(seconds=float(hours * 3600))
            return self.until[key]
        return None


@dataclass
class RunControls:
    """All run-scoped controls plus queued control events for the journal."""

    kill_switch: KillSwitch = field(default_factory=KillSwitch)
    breaker: CircuitBreaker = field(default_factory=CircuitBreaker)
    lockout: DailyLockout = field(default_factory=DailyLockout)
    cooldowns: Cooldowns = field(default_factory=Cooldowns)
    execution_enabled: bool = True
    consecutive_errors: int = 0
    events: list[tuple[EventType, dict[str, Any]]] = field(default_factory=list)

    def emit(self, event_type: EventType, payload: dict[str, Any]) -> None:
        """
        Queue a control event for journaling.

        Args:
            event_type (EventType): Event type.
            payload (dict[str, Any]): Payload.
        """
        self.events.append((event_type, payload))

    def drain(self) -> list[tuple[EventType, dict[str, Any]]]:
        """
        Return and clear queued events.

        Returns:
            list[tuple[EventType, dict[str, Any]]]: Events.
        """
        out, self.events = self.events, []
        return out


class PersistedKillSwitch:
    """Kill switch persisted in the operational store (governs paper sessions, V1)."""

    def __init__(self, store: OperationalStore | None = None) -> None:
        """
        Open the persisted kill switch.

        Args:
            store (OperationalStore | None): Store; defaults to ``data/state``.
        """
        self.store = store or OperationalStore()

    def state(self) -> KillSwitchState | None:
        """
        Return the latest state (None means never changed: disengaged).

        Returns:
            KillSwitchState | None: State.
        """
        return self.store.killswitch_state()

    def is_engaged(self) -> bool:
        """
        Whether the persisted switch is engaged.

        Returns:
            bool: True if engaged.
        """
        s = self.state()
        return s is not None and s.state == "engaged"

    def engage(self, reason: str, now: datetime, trigger: str | None = None) -> KillSwitchState:
        """
        Engage (always available; owner or system).

        Args:
            reason (str): Why.
            now (datetime): Time.
            trigger (str | None): Auto trigger; None means the owner.

        Returns:
            KillSwitchState: Appended state.

        Raises:
            KillSwitchError: If the reason is empty.
        """
        if not reason.strip():
            raise KillSwitchError("a reason is required")
        st = KillSwitchState(
            schema_version="1.0.0",
            state="engaged",
            changed_at_utc=now,
            changed_by="system" if trigger else "owner",
            reason=reason,
            trigger=trigger,
        )
        self.store.append_killswitch(st)
        return st

    def disengage(self, reason: str, now: datetime) -> KillSwitchState:
        """
        Disengage (owner command with reason; automation has no access to this path).

        Args:
            reason (str): Why.
            now (datetime): Time.

        Returns:
            KillSwitchState: Appended state.

        Raises:
            KillSwitchError: If the reason is empty.
        """
        if not reason.strip():
            raise KillSwitchError("a reason is required")
        st = KillSwitchState(
            schema_version="1.0.0",
            state="disengaged",
            changed_at_utc=now,
            changed_by="owner",
            reason=reason,
            trigger=None,
        )
        self.store.append_killswitch(st)
        return st
