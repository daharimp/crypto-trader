# QuantConnect (LEAN) version of the lab's "squeeze 42 q0.25 stop3.0 L" idea, for checking
# results on QuantConnect's own data. Paste into a new Python project at quantconnect.com.
# Research only: written to match trader.research.lab.squeeze_breakout, but NOT yet run on
# QuantConnect; numbers may differ (their data, fees and fills). Not investment advice.
from AlgorithmImports import *


class SqueezeBreakout(QCAlgorithm):
    """Long-only: after a quiet stretch (range in the bottom 25% of the last 300 bars),
    buy a break above the 42-bar high; exit on a 3x ATR(14) trailing stop. 4h bars."""

    N, Q, STOP, LOOK = 42, 0.25, 3.0, 300

    def initialize(self):
        self.set_start_date(2024, 9, 1)
        self.set_cash(2500)
        self.set_brokerage_model(BrokerageName.KRAKEN, AccountType.CASH)
        self.state = {}
        for t in ("SOLUSD", "BTCUSD", "ETHUSD"):
            sym = self.add_crypto(t, Resolution.HOUR, Market.KRAKEN).symbol
            cons = TradeBarConsolidator(timedelta(hours=4))
            cons.data_consolidated += self.on_bar
            self.subscription_manager.add_consolidator(sym, cons)
            self.state[sym] = {
                "bars": RollingWindow[TradeBar](self.LOOK + self.N),
                "atr": AverageTrueRange(14, MovingAverageType.SIMPLE),
                "widths": RollingWindow[float](self.LOOK),
                "stop": None,
            }
            self.register_indicator(sym, self.state[sym]["atr"], cons)
        self.set_warm_up(timedelta(days=60))

    def on_bar(self, _, bar):
        s = self.state[bar.symbol]
        bars = s["bars"]
        if bars.count >= self.N:
            prev = [bars[i] for i in range(self.N)]  # the N bars before this one
            hi, lo = max(b.high for b in prev), min(b.low for b in prev)
            quiet = (
                s["widths"].count >= 100
                and (hi - lo) / bar.close
                <= sorted(s["widths"])[int(self.Q * (s["widths"].count - 1))]
            )
            s["widths"].add((hi - lo) / bar.close)
        else:
            hi = quiet = None
        bars.add(bar)
        if self.is_warming_up or not s["atr"].is_ready or hi is None:
            return
        a = s["atr"].current.value
        held = self.portfolio[bar.symbol].invested
        if held:
            s["stop"] = max(s["stop"], bar.close - self.STOP * a)
            if bar.close < s["stop"]:
                self.liquidate(bar.symbol)
        elif quiet and bar.close > hi:
            # Reason: equal thirds of the account; the bot's own risk engine sizes real trades.
            self.set_holdings(bar.symbol, 0.33)
            s["stop"] = bar.close - self.STOP * a
