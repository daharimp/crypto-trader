"""In-memory stand-in for ``ccxt.kraken`` (public data, orders, balances). Test-only."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any

from trader.domain.candles import Candle


class FakeAuthError(Exception):
    """Mimics ccxt.AuthenticationError (matched by class name)."""


FakeAuthError.__name__ = "AuthenticationError"


class FakeKraken:
    """Serves candles up to ``now()``, fills market orders at the current bar's open."""

    def __init__(
        self,
        candles: dict[str, list[Candle]],
        daily: dict[str, list[Candle]],
        now: Callable[[], datetime],
        usd: Decimal = Decimal(1000),
        fee_rate: Decimal = Decimal("0.004"),
    ) -> None:
        self.candles, self.daily, self.now = candles, daily, now
        self.balances: dict[str, Decimal] = {"USD": usd}
        self.fee_rate = fee_rate
        self.orders: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.fail_next_create = False
        self.clock_offset_s = 0.0

    # --- public ----------------------------------------------------------------------
    def fetch_time(self) -> int:
        return int((self.now().timestamp() + self.clock_offset_s) * 1000)

    def load_markets(self) -> dict[str, Any]:
        return {
            s: {"limits": {"amount": {"min": 0.0001}}, "precision": {"amount": 1e-08}}
            for s in self.candles
        }

    def _bars(self, symbol: str, timeframe: str) -> list[Candle]:
        src = self.daily if timeframe == "1d" else self.candles
        return [c for c in src[symbol] if c.open_time_utc <= self.now()]

    def fetch_ohlcv(
        self, symbol: str, timeframe: str, since: Any = None, limit: int | None = None
    ) -> list[list[Any]]:
        bars = self._bars(symbol, timeframe)[-(limit or 720) :]
        return [
            [
                int(c.open_time_utc.timestamp() * 1000),
                float(c.open),
                float(c.high),
                float(c.low),
                float(c.close),
                float(c.volume),
            ]
            for c in bars
        ]

    def _price(self, symbol: str) -> Decimal:
        return self._bars(symbol, "4h")[-1].open  # the forming bar's open

    # --- private ---------------------------------------------------------------------
    def create_order(
        self,
        symbol: str,
        type_: str,
        side: str,
        amount: float,
        price: Any = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params = dict(params or {})
        self.calls.append(("create_order", (symbol, type_, side, amount, price), params))
        if self.fail_next_create:
            self.fail_next_create = False
            oid = f"O{len(self.orders) + 1}"
            self._fill_market(oid, symbol, side, Decimal(str(amount)), params)
            raise TimeoutError("network timeout after the exchange accepted the order")
        if params.get("validate"):
            return {"id": None, "info": {"descr": "validated"}}
        oid = f"O{len(self.orders) + 1}"
        if "stopLossPrice" in params:
            self.orders[oid] = {
                "id": oid,
                "symbol": symbol,
                "side": side,
                "amount": Decimal(str(amount)),
                "status": "open",
                "stop": Decimal(str(params["stopLossPrice"])),
                "filled": 0,
                "userref": params.get("userref"),
                "placed": self.now(),
            }
        else:
            self._fill_market(oid, symbol, side, Decimal(str(amount)), params)
        return {"id": oid}

    def _fill_market(
        self,
        oid: str,
        symbol: str,
        side: str,
        amount: Decimal,
        params: dict[str, Any],
        price: Decimal | None = None,
    ) -> None:
        px = price or self._price(symbol)
        base = symbol.split("/")[0]
        cost = amount * px
        fee = cost * self.fee_rate
        if side == "buy":
            self.balances["USD"] -= cost + fee
            self.balances[base] = self.balances.get(base, Decimal(0)) + amount
        else:
            self.balances["USD"] += cost - fee
            self.balances[base] = self.balances.get(base, Decimal(0)) - amount
        self.orders[oid] = {
            "id": oid,
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "status": "closed",
            "filled": amount,
            "average": px,
            "fee": {"cost": float(fee), "currency": "USD"},
            "userref": params.get("userref"),
            "timestamp": int(self.now().timestamp() * 1000),
        }

    def _check_stops(self) -> None:
        for oid, o in list(self.orders.items()):
            if o["status"] != "open" or "stop" not in o:
                continue
            for c in self._bars(o["symbol"], "4h"):
                if (
                    c.open_time_utc >= o["placed"]
                    and c.close_time_utc <= self.now()
                    and c.low <= o["stop"]
                ):
                    self._fill_market(
                        oid,
                        o["symbol"],
                        "sell",
                        o["amount"],
                        {"userref": o["userref"]},
                        min(o["stop"], c.open),
                    )
                    break

    def fetch_order(self, oid: str, symbol: str | None = None) -> dict[str, Any]:
        self._check_stops()
        o = self.orders[oid]
        return {k: (float(v) if isinstance(v, Decimal) else v) for k, v in o.items()}

    def cancel_order(self, oid: str, symbol: str | None = None) -> dict[str, Any]:
        self.calls.append(("cancel_order", (oid, symbol), {}))
        self.orders[oid]["status"] = "canceled"
        return {"id": oid}

    def fetch_balance(self) -> dict[str, Any]:
        self._check_stops()
        return {"total": {k: float(v) for k, v in self.balances.items()}}

    def fetch_open_orders(
        self,
        symbol: str,
        since: Any = None,
        limit: Any = None,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        ref = (params or {}).get("userref")
        return [
            o
            for o in self.orders.values()
            if o["status"] == "open" and (ref is None or o.get("userref") == ref)
        ]

    def fetch_closed_orders(
        self,
        symbol: str,
        since: Any = None,
        limit: Any = None,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        ref = (params or {}).get("userref")
        return [
            o
            for o in self.orders.values()
            if o["status"] == "closed" and (ref is None or o.get("userref") == ref)
        ]
