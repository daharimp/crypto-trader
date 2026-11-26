"""crypto-trader's live trend rule as a freqtrade strategy (research cross-check only).

Port of ``trader.regimes.trend`` + the ``main`` paper account (configs/perps/jupiter.yaml v11):

* Side: long while SMA50 > SMA200, short while below; while the market is ranging (Kaufman
  efficiency ratio over 180 bars < 0.05) the SMA10/SMA30 pair decides. Needs 200 bars.
* Leverage: keeps liquidation 4 typical daily moves away (std of the last 180 4h returns
  x sqrt 6), 1/(distance + 27 bps), rounded down to 0.1, between 1x and 25x.
* Collateral: 10% of equity per position, at most 3 positions, total size <= 400% of equity.
* Stop: 30% of collateral lost, fees (7 bps a side) included.
* Ladder (LADDER = True): TP1 4R closes 25% and moves the stop to breakeven + fees,
  TP2 8R closes 25% and moves it to TP1, TP3 12R closes the rest. R = entry-to-stop.
* After a stop or TP3 the coin waits for the next UTC day before it may open again.

Known freqtrade-vs-engine differences (by design of each tool, reported in the results):
partial exits fill at the next candle open after the level was touched (our engine fills at
the level); after a flip freqtrade waits one candle before opening the other side; equity
for sizing is freqtrade's wallet (closed P&L), ours marks open positions; no daily loss
limit; no borrow or funding on either side in the like-for-like run.
"""

import numpy as np
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, stoploss_from_absolute
from pandas import DataFrame

FEE = 0.0007
STOP_SHARE = 0.30
BUFFER = 4.0
CEILING = 25.0
COLLATERAL = 0.10
MAX_GROSS = 4.0
RUNGS = ((4.0, 0.25), (8.0, 0.25), (12.0, 0.50))


class TrendMain(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "4h"
    can_short = True
    startup_candle_count = 420
    stoploss = -STOP_SHARE
    use_custom_stoploss = True
    minimal_roi = {"0": 100.0}
    trailing_stop = False
    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    position_adjustment_enable = True
    max_entry_position_adjustment = 0
    LADDER = True

    # --- indicators -------------------------------------------------------------------
    def populate_indicators(self, df: DataFrame, metadata: dict) -> DataFrame:
        c = df["close"]
        path = c.diff().abs().rolling(180).sum()
        er = (c - c.shift(180)).abs() / path
        ranging = er < 0.05
        fast = np.where(ranging, c.rolling(10).mean(), c.rolling(50).mean())
        slow = np.where(ranging, c.rolling(30).mean(), c.rolling(200).mean())
        trend = np.sign(fast - slow)
        trend = np.where(c.rolling(200).count() >= 200, trend, 0)
        df["trend"] = np.nan_to_num(trend)
        move = c.pct_change().rolling(180).std() * np.sqrt(6)
        raw = 1 / (BUFFER * move + 0.0027)
        df["lev"] = np.clip(np.floor(raw * 10) / 10, 1, CEILING)
        return df

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df["enter_long"] = (df["trend"] > 0).astype(int)
        df["enter_short"] = (df["trend"] < 0).astype(int)
        return df

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df["exit_long"] = (df["trend"] <= 0).astype(int)
        df["exit_short"] = (df["trend"] >= 0).astype(int)
        return df

    # --- sizing -----------------------------------------------------------------------
    def _last(self, pair: str, col: str) -> float:
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        return float(df[col].iloc[-1]) if len(df) else float("nan")

    def leverage(
        self,
        pair,
        current_time,
        current_rate,
        proposed_leverage,
        max_leverage,
        entry_tag,
        side,
        **kwargs,
    ) -> float:
        lev = self._last(pair, "lev")
        return float(lev) if np.isfinite(lev) else 1.0

    def _equity(self) -> float:
        """Wallet plus open positions marked at the last close, like our engine's equity."""
        eq = self.wallets.get_total_stake_amount()
        for t in Trade.get_trades_proxy(is_open=True):
            px = self._last(t.pair, "close")
            if np.isfinite(px):
                eq += t.calc_profit(px)
        return eq

    def custom_stake_amount(
        self,
        pair,
        current_time,
        current_rate,
        proposed_stake,
        min_stake,
        max_stake,
        leverage,
        entry_tag,
        side,
        **kwargs,
    ) -> float:
        return min(self._equity() * COLLATERAL, max_stake)

    def confirm_trade_entry(
        self, pair, order_type, amount, rate, time_in_force, current_time, entry_tag, side, **kwargs
    ) -> bool:
        if not np.isfinite(self._last(pair, "lev")):
            return False
        last = Trade.get_trades_proxy(pair=pair, is_open=False)
        if last:
            t = max(last, key=lambda x: x.close_date_utc)
            if (
                t.exit_reason in ("stop_loss", "tp3", "liquidation")
                and t.close_date_utc.date() == current_time.date()
            ):
                return False
        equity = self._equity()
        gross = sum(t.stake_amount * t.leverage for t in Trade.get_trades_proxy(is_open=True))
        return gross + amount * rate <= equity * MAX_GROSS

    # --- stop and ladder --------------------------------------------------------------
    @staticmethod
    def _levels(trade: Trade) -> tuple[float, float]:
        """(initial stop price, R in price)."""
        sign = -1 if trade.is_short else 1
        room = STOP_SHARE / trade.leverage - 2 * FEE
        stop = trade.open_rate * (1 - sign * room)
        return stop, abs(trade.open_rate - stop)

    def custom_stoploss(
        self, pair, trade, current_time, current_rate, current_profit, after_fill, **kwargs
    ) -> float | None:
        sign = -1 if trade.is_short else 1
        stop, r = self._levels(trade)
        hit = int(trade.get_custom_data("tps", 0) or 0)
        if hit == 1:
            stop = trade.open_rate * (1 + sign * 2 * FEE)
        elif hit >= 2:
            stop = trade.open_rate + sign * RUNGS[0][0] * r
        return stoploss_from_absolute(
            stop, current_rate, is_short=trade.is_short, leverage=trade.leverage
        )

    def _touched(self, trade: Trade, k: int) -> bool:
        sign = -1 if trade.is_short else 1
        _, r = self._levels(trade)
        level = trade.open_rate + sign * RUNGS[k][0] * r
        best = trade.min_rate if trade.is_short else trade.max_rate
        return best is not None and (best - level) * sign >= 0

    def adjust_trade_position(
        self,
        trade: Trade,
        current_time,
        current_rate,
        current_profit,
        min_stake,
        max_stake,
        current_entry_rate,
        current_exit_rate,
        current_entry_profit,
        current_exit_profit,
        **kwargs,
    ):
        if not self.LADDER:
            return None
        hit = int(trade.get_custom_data("tps", 0) or 0)
        if hit < 2 and self._touched(trade, hit):
            first = trade.orders[0]
            opening_stake = first.safe_amount_after_fee * first.safe_price / trade.leverage
            trade.set_custom_data("tps", hit + 1)
            return -opening_stake * RUNGS[hit][1], f"tp{hit + 1}"
        return None

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        hit = int(trade.get_custom_data("tps", 0) or 0)
        if self.LADDER and hit >= 2 and self._touched(trade, 2):
            return "tp3"
        return None


class TrendMainNoLadder(TrendMain):
    LADDER = False


class TrendMainPeek(TrendMain):
    """Positive control for lookahead-analysis: reads the NEXT candle's close (cheating)."""

    def populate_indicators(self, df: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_indicators(df, metadata)
        df["trend"] = np.sign(df["close"].shift(-1) - df["close"]).fillna(0)
        return df
