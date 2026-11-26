"""Run freqtrade with no exchange connection: hand-built Binance USDT-M markets and tiers.

The cloud container cannot reach any exchange, and freqtrade's backtester only needs the
market metadata (precision, limits) and the leverage tiers (for liquidation prices).
Maintenance margin is set to 0.2% to match our paper engine's maintenance_bps of 20.
"""

import sys

from freqtrade.exchange import exchange as ex_mod

COINS = ["BTC", "ETH", "SOL"]


def _market(base: str) -> dict:
    sym = f"{base}/USDT:USDT"
    return {
        "id": f"{base}USDT",
        "symbol": sym,
        "base": base,
        "quote": "USDT",
        "settle": "USDT",
        "baseId": base,
        "quoteId": "USDT",
        "settleId": "USDT",
        "type": "swap",
        "spot": False,
        "margin": False,
        "swap": True,
        "future": False,
        "option": False,
        "contract": True,
        "linear": True,
        "inverse": False,
        "contractSize": 1.0,
        "active": True,
        "taker": 0.0007,
        "maker": 0.0007,
        "precision": {"amount": 1e-6, "price": 1e-6},
        "limits": {
            "amount": {"min": 1e-6, "max": 1e12},
            "cost": {"min": 0.01, "max": 1e12},
            "price": {"min": 1e-6, "max": 1e12},
            "leverage": {"min": 1, "max": 250},
        },
        "info": {},
    }


MARKETS = {f"{c}/USDT:USDT": _market(c) for c in COINS}


def _reload(self, force: bool = False, *, load_leverage_tiers: bool = True) -> None:
    if self._last_markets_refresh > 0:
        return
    for api in (self._api, self._api_async):
        api.set_markets(list(MARKETS.values()))
    self._markets = self._api.markets
    self._last_markets_refresh = ex_mod.dt_ts()
    for pair in MARKETS:
        self._leverage_tiers[pair] = [
            {
                "minNotional": 0.0,
                "maxNotional": 1e15,
                "maintenanceMarginRate": 0.002,
                "maxLeverage": 250.0,
                "maintAmt": 0.0,
            }
        ]


ex_mod.Exchange.reload_markets = _reload
ex_mod.Exchange.validate_timeframes = lambda self, tf: None
ex_mod.Exchange.fetch_trading_fees = lambda self: {}

if __name__ == "__main__":
    from freqtrade.main import main

    sys.exit(main(sys.argv[1:]))
