<!-- Independent audit of research/exp023_lib.py, 2026-11-26. Written by a separate reviewer that was
     given the code and the live engine, not the conclusions. Since the audit: the cache fix of 1.1
     is applied to exp023_lib.py (a fresh rebuild reproduces the same numbers); exp024_lib.py has
     the fixes for 1.2 and 1.5 and stamps its caches per coin. The EXP-2026-023 tables were
     produced before those fixes, from the cache this audit verified. -->

# Audit of the EXP-2026-023 replay harness (`research/exp023_lib.py`, `research/run_exp023.py`)

**Verdict: safe to use, with the caveats listed below.**

With the default switches the harness reproduces the real live session (`PerpsSession.cycle`) event for event, apart from one ordering difference worth at most 0.03% of end equity. I found no look-ahead, and every summary statistic recomputes correctly. The only thing that can produce badly wrong numbers is the disk cache: it is correct today, but nothing protects it against a reused label or changed candle files.

The tables already produced (the main, spot-perps and degen tables in `EXP-2026-023-results.txt`) came from a correct cache, so they can be read as "what the live paper engine would have done on Binance candles".

Version audited: `exp023_lib.py` sha256 `cf66bc607aedf8aa…` (390 lines), `run_exp023.py` sha256 `e3fd102ff1009be6…`. The library was rewritten once during the audit (01:24 UTC, a reformat of `moves()` only). Every result below is from that version, and it was still unchanged at 01:49 UTC. Line numbers refer to it.

Everything in sections 1 to 3 was confirmed by running code unless it is marked "read only".

## 1. Confirmed defects and mismatches, ranked by impact

| # | What | Effect on the numbers already produced |
|---|---|---|
| 1.1 | Disk cache keyed by timeframe and label only | None today (cache verified). Unbounded and silent if a label or the data changes |
| 1.2 | Coins opened in a different order from live | At most ±0.03% of end equity, ±0.03 pp CAGR |
| 1.3 | `stop%` also counts stops after a take-profit | Column overstated by 1.5 to 2.5 points on main and degen |
| 1.4 | `breakout_reentry` looks back 20 execution bars | Degen row tests a 20-hour rule, main an 80-hour rule |
| 1.5 | Last bar of a window still takes a decision | Zero in the six standard runs; up to −0.15% of end equity otherwise |
| 1.6 | A `gate` is asked before any of the bar's opens | None for the built-in variants |
| 1.7 | `summarize()` crashes on a one-day replay | None |
| 1.8 | 4h path: BTC and ETH history starts at SOL's first candle | None for the defined windows |

### 1.1 Disk cache is keyed by timeframe and label only

`exp023_lib.py:131-147` (`_cached`, key on line 134), `:171` (`signals`), `:179` (`moves`).

- **What happens.** The file is `<tf>-<name>.pkl`. Nothing ties it to the candles, the time axis, `KEEP`, the coin list or the signal function. A file written for other data or another signal is loaded with no check, and `run()` indexes it by bar number.
- **Reproduction** (`cache_hazard.py`, private cache folder):
  - Same label, different signal: after a live cache exists, `feed.signals("live", lib.plain_50_200)` returns the live signal (equal to live: True; equal to what was asked for: False).
  - Cache built from a file that starts 31 days later, then used with the full file: it loads without error (2,742 cached entries for 2,928 bars), `run()` raises nothing, and every decision reads the signal of 31 days ahead. Main over 2023-11-15 to 2024-11-15 reports CAGR −19.0% and Sharpe 0.28 instead of the correct 296.8% and 1.82.
- **State today.** All six shared files (`4h` and `1h` × `sig-live`, `sig-plain-50-200`, `moves`) equal a fresh rebuild from the candle files, element for element (`check_cache.py 4h`, `check_cache_1h_full.py`).
- **Why it still matters.** The shared folder already holds labels written by other scripts (`signal-churn1-*`, `followup-ema-vote-v1`). A changed factory under an unchanged label, or refreshed candle files, would be served stale.
- **Bias.** None now. If triggered: any size, either direction, no error.
- **Related, read only.** The temp file is `<name>.<id(self)>.tmp` (line 142), so two processes building the same entry could share a name. Eight fresh processes gave eight different names, so the chance is small.
- **Fix**, verified on a patched copy (`verify_cache_fix.py`: other data and another factory both get the right series, and a second load hits the cache). File names change, so each entry is rebuilt once (about two minutes for the 1h feed).

```diff
@@ imports
+import hashlib
+import os
+import uuid
@@ class Feed
+    def _fingerprint(self) -> str:
+        """Hash of everything a cached series depends on: candles, time axis, KEEP, coins."""
+        if "fp" not in self._mem:
+            h = hashlib.sha256(f"{self.tf}|{KEEP}|{COINS}|{len(self.times)}".encode())
+            for m in COINS:
+                for t in self.times:
+                    h.update(f"{t.isoformat()}{self.rows[m][t][4]}".encode())
+                for r in (self.trend or {}).get(m, []):
+                    h.update(f"{r[0].isoformat()}{r[4]}".encode())
+            self._mem["fp"] = h.hexdigest()[:16]
+        return self._mem["fp"]
+
     def _cached(self, name: str, build: Callable[[], Any]) -> Any:
         if name in self._mem:
             return self._mem[name]
-        path = self.cache_dir / f"{self.tf}-{name}.pkl" if self.cache_dir else None
+        path = (
+            self.cache_dir / f"{self.tf}-{name}-{self._fingerprint()}.pkl" if self.cache_dir else None
+        )
         if path is not None and path.exists():
             with open(path, "rb") as f:
                 value = pickle.load(f)  # noqa: S301 - our own cache file
+            if any(len(v) != len(self.times) for v in value.values()):
+                raise ValueError(f"{path}: cached series do not match this feed's bars")
@@
-                tmp = path.with_suffix(f".{id(self)}.tmp")
+                tmp = path.with_suffix(f".{os.getpid()}.{uuid.uuid4().hex}.tmp")
@@ Feed.signals
-        return self._cached(f"sig-{label}", build)
+        # Reason: the factory's name is part of the key, so one label cannot hide two signals.
+        return self._cached(f"sig-{label}-{factory.__module__}.{factory.__qualname__}", build)
```

Two limits of that fix: two lambdas in one module share the name `<lambda>`, so parameters still belong in the label; and a `functools.partial` has no `__qualname__`, so pass named functions.

### 1.2 Coins are opened in a different order from live

`exp023_lib.py:280-322` against `session.py:397-406` (`apply_signal` per market).

- **What happens.** Live handles one market at a time in the order SOL, ETH, BTC: close if the side changed, then open. The harness closes every changed position first, then opens all longs, then all shorts. Each open lowers equity by its fees, so collateral amounts differ slightly, and when a cap binds a different coin can be the one refused.
- **Evidence** (`ref_session.py`, the real session driven bar by bar). The first divergence in main dev is 2020-11-27 00:00, when SOL short and ETH, BTC long open together. Session collateral: SOL 322.59, ETH 322.47, BTC 322.21. Harness: ETH 322.59, BTC 322.32, SOL 322.00.
- **Size** (`effects.py`, harness against the same loop in the live order):

| Account, window | End equity | CAGR |
|---|---|---|
| main dev | +0.028% | +0.026 pp |
| main hold | +0.003% | +0.001 pp |
| degen dev | +0.021% | +0.012 pp |
| degen hold | +0.008% | +0.003 pp |
| spot-perps dev | +0.003% | +0.001 pp |
| spot-perps hold | −0.002% | −0.001 pp |

  The number of refused opens is the same in both orders (main: 23 and 66 `PERP_TOTAL_SIZE_ABOVE_CAP`).
- **Fix**, verified (`make_patched.py`: with this and the fix in 1.5, the patched copy's events equal the live-order reference in all six runs):

```diff
@@ run(), lines 303-305
                 if gate is not None and not gate(acct, m, target, j):
                     continue
-                wanted[target].append(m)
+                if group_cap is None:
+                    # Reason: session.cycle -> apply_signal closes then opens market by market.
+                    acct.open(m, target, fills, closes_at)
+                else:
+                    wanted[target].append(m)
```

### 1.3 `stop%` also counts stops after a take-profit

`exp023_lib.py:356, 364`. The table legend calls the column "share of entries that ended at the stop".

- **What happens.** Every `CLOSED` with reason `STOP_LOSS` counts. After a take-profit the stop sits at breakeven or better, and the engine uses the same reason for it (synthetic case B4: a breakeven exit gives `stop_share` 100%).
- **Size** (`effects.py`):

| Account, window | `stop%` reported | Stops before any take-profit only |
|---|---|---|
| main dev | 29.4% (275 + 19) | 27.5% |
| main hold | 25.9% (226 + 14) | 24.4% |
| degen dev | 31.2% (447 + 39) | 28.7% |
| degen hold | 27.5% (373 + 37) | 25.0% |
| spot-perps | no ladder, no difference | |

- **Fix** (not run as a patch; the same counting ran in `effects.py`):

```diff
@@ summarize()
-    stops = sum(1 for e in closed if e["reason"] == "STOP_LOSS")
+    # Reason: a stop after a take-profit is at breakeven or better, not a full loss.
+    had_tp: dict[str, bool] = {}
+    stops = stops_after_tp = 0
+    for e in ev:
+        if e["event"] == "OPENED":
+            had_tp[e["market"]] = False
+        elif e["event"] == "TAKE_PROFIT":
+            had_tp[e["market"]] = True
+        elif e["event"] == "CLOSED" and e["reason"] == "STOP_LOSS":
+            if had_tp.get(e["market"]):
+                stops_after_tp += 1
+            else:
+                stops += 1
@@
         "stop_share": stops / max(opens, 1) * 100,
+        "stop_after_tp_share": stops_after_tp / max(opens, 1) * 100,
```

### 1.4 `breakout_reentry` looks back 20 execution bars

`exp023_lib.py:63, 292`.

- **What happens.** The look-back is 20 bars of the account's own timeframe: 80 hours on main and spot-perps, 20 hours on degen. The "reentry=breakout" row therefore tests a different rule on degen.
- **Size** (`breakout_bars.py`, degen):

| Look-back | Dev CAGR | Hold CAGR |
|---|---|---|
| 20 one-hour bars (as coded) | 53.1% | −11.0% |
| 80 one-hour bars (the 80 hours main uses) | 50.3% | −20.8% |

  The conclusion for degen (worse than live) holds either way.
- **The promise itself holds.** Of 226 same-side re-entries after a stop (main and spot-perps, both windows), none happened without an earlier close beyond the previous 20 closes or a signal change (`switches.py`, synthetic case F).
- **Fix**, if the same 80 hours is what is meant (equivalent to the 80-bar run above):

```diff
-BREAKOUT_BARS = 20
+BREAKOUT_BARS = 20  # 4h candles; an hourly account looks back the same 80 hours
@@ run(), line 292
-                    look = [feed.rows[m][x][4] for x in times[max(j0, j - BREAKOUT_BARS) : j]]
+                    n = BREAKOUT_BARS * int(TREND_STEP / step)
+                    look = [feed.rows[m][x][4] for x in times[max(j0, j - n) : j]]
```

### 1.5 The last bar of a window still takes a decision

`exp023_lib.py:275, 330-333`. The docstring (line 228) says bars opening at or after `end` are not used.

- **What happens.** On the last bar the fill price is the open of the bar that opens at `end`. Anything opened there is closed at once at the previous bar's close, paying both fees.
- **Reproduction** (synthetic case J). The signal turns long on the last bar; the harness opens at 101 (the next bar's open), closes at 100, and ends with 988.10 instead of 1,000.00.
- **Size.** Zero in all six standard runs, because no position changed on the last decision. Over 150 random 60-day windows on main it was non-zero in 18, worst −0.15% of end equity (`engine_notes.py`). Slightly pessimistic.
- **Fix**, verified together with 1.2:

```diff
-        has_next = j + 1 < len(times) and times[j + 1] == closes_at
+        # Reason: a decision on the last bar would fill at the open of the bar at `end`.
+        has_next = j + 1 < j1 and times[j + 1] == closes_at
```

### 1.6 A `gate` is asked about every coin before any of that bar's opens

`exp023_lib.py:303-305` against `:306-322`.

- **Reproduction** (synthetic case H). A gate "fewer than 2 positions" lets all three coins open in one bar, because the account is still empty when each is asked.
- **Size.** None for the built-in variants, which use no gate. The one gate I saw elsewhere (`exp023_degen.py:457`, a time-of-day test) is unaffected.
- **Read only.** A gate also receives the bar index `j`. A gate that reads `feed.rows` at `j + 1` would look ahead, and the harness cannot stop that.
- **Fix.** With the change in 1.2 the gate is called right before each open when there is no group cap. Say so in the docstring.

### 1.7 `summarize()` crashes on a replay inside one UTC day

`exp023_lib.py:352`: `ZeroDivisionError` (synthetic case I). Fix, verified:

```diff
-    sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / (len(rets) - 1))
+    sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)) if len(rets) > 1 else 0.0
```

### 1.8 On the 4h path BTC and ETH only see history from SOL's first candle

`exp023_lib.py:113-117` builds each coin's history from the shared timestamps.

- **Evidence** (`misc.py`, `check_cache_1h_full.py`). On the 4h feed the first live signal for all three coins is at bar 199 (2020-09-13 08:00). On the 1h feed BTC and ETH have a signal from bar 0, because that path uses each coin's own 4h candles from January 2020.
- **Size.** None for the defined windows (dev starts at bar 305). It matters only for a window that starts before 2020-09-13.
- **Fix** (not run):

```diff
@@ Feed.views, 4h path
-            hist: list[Decimal] = []
-            for t in self.times:
-                hist.append(self.rows[m][t][4])
-                view = hist[-KEEP:]
-                out.append((view, view))
+            own = sorted(self.rows[m])  # this coin's own candles, like session.cycle
+            own_closes = [self.rows[m][t][4] for t in own]
+            for t in self.times:
+                i = bisect.bisect_right(own, t)
+                view = own_closes[max(0, i - KEEP) : i]
+                out.append((view, view))
```

### Two notes on `run_exp023.py`

- Lines 58 and 61: on degen a position risks 5% × 30% = 1.5% of equity, so three positions risk 4.5%. `group_cap=6%` and `buffer=8 + group_cap=6%` cannot bind and repeat the live and `buffer=8` rows exactly, as `out/exp023-degen.txt` shows. On spot-perps no cap from 3% up binds either (largest same-side risk 2.8%).
- Line 77 (read only): `feeds.setdefault(tf, lib.build_feed(...))` reloads the CSV files for every account. Speed only.

## 2. Engine assumptions shared with live paper

These live in `src/trader/perps/simulator.py`. The harness and the live engine behave the same, so they are not harness defects, but they shape every number.

- **Take-profit bar: only the close is tested against the moved stop** (`simulator.py:298`, synthetic case B4). The rest of the position survived although the bar's adverse extreme had reached the moved stop in 4 of 140 take-profit bars (main dev), 0 of 115 (main hold), 2 of 212 and 2 of 194 (degen). Assuming the worse order of high and low instead (`engine_notes.py`): main dev CAGR 207.2% becomes 188.5%, main hold is unchanged, degen goes from 79.8% to 77.3% and from 9.9% to 9.8%. Four trades moving the dev CAGR by 19 points also shows how much that number hangs on a few trades.
- **Stops fill exactly at the stop price.** In this data no stop ever gapped: all 599 stops before a take-profit in the main and degen hold runs cost 29.99% to 30.01% of collateral (`live_check.py`), and handing the bar's open to `mark` changes nothing (0.00% in `vs_backtest.py`).
- **Cent rounding** (borrow booked per bar in whole cents, `simulator.py:181`). Booked borrow is within −1.6% to +0.2% of the exact amount. The same replay with 100 times the balance moves CAGR by −0.56 to +0.10 points; the largest is degen hold, 9.89% against 10.44% (`effects.py`).
- **Reading aid.** `fee/y` is trading fees plus borrow. Borrow alone is 25% to 28% of average equity a year on main, 15% to 18% on degen and 6% on spot-perps.
- **Read only.** At the day roll the day's starting equity is taken at the bar's adverse extremes (`simulator.py:229`), which lowers the base of the daily loss limit. A live account that starts mid-bar is first marked against the whole bar, including prices from before it opened (`session.py:361-385`). The harness starts on a bar boundary.

## 3. Checked and found correct

- **Order of steps per bar, first bar, UTC day roll, `stopped_today`.** The real `PerpsSession.cycle`, driven one bar per cycle by a fake candle fetcher (719 completed candles plus a forming candle whose only known price is its open), matches the audit reference (the harness loop with `apply_signal`) event for event: main dev 3,327 events, main hold 3,073, spot-perps dev 3,006, spot-perps hold 2,692, degen 2024-01-01 to 2024-10-01 (6,576 hourly bars) 1,062. The harness differs from that reference only by 1.2 (`ref_session.py`, `liveorder.py`).
- **Day-end equity and drawdown.** The session's own equity journal equals the reference day-end equity within half a cent on every day (1,186 and 1,055 days, main and spot-perps); maximum drawdown agrees to 0.01 (`summ_check.py`).
- **No look-ahead.** Every candle value not yet known at the decision of bar T was changed, keeping the open of T+1, and all events stamped up to that decision had to stay identical. 4h path: 4 pivots × main and spot-perps × 6 variants (live, plain, group cap, breakout, gate, a custom signal) = 48 identical. 1h path: 4 pivots × 6 variants = 24 identical, one pivot on a 4h boundary and three inside a 4h candle. A deliberately leaky signal was caught in 12 of 12 control runs (`lookahead.py`).
- **`Feed.views` on the 1h path equals `session._trend_view`.** 1,652 bars per coin, including 409 on a 4h boundary and the bars around every data gap: closes, daily move and signal all equal. Also checked by hand (synthetic case G).
- **420 closes are enough.** Signals and daily moves from the truncated view equal those from the full history (4,500 samples) and from the 719 closes Kraken gives the live session (`check_cache.py`).
- **Stops, gap fills, ladder, liquidation, borrow, group cap split, breakout re-entry.** 32 checks against numbers worked out by hand, all equal (`synthetic.py`). Same-bar rules confirmed: stop and take-profit in one bar means the stop wins; a stop the open gapped through fills at the open; a gap through the liquidation price liquidates.
- **`group_cap`.** A cap of 1,000% gives events identical to no cap, so the temporary `acct.params` swap changes nothing else, and `acct.params` is the original object after every run. Same-side risk right after an open never exceeded the cap by more than 0.015 points (`switches.py`).
- **`gate`.** A gate that always allows gives identical events.
- **`summarize`.** All 12 statistics recomputed from the journal alone match; the day keys are exactly every UTC day of the window; the last day equals end cash (`summ_check.py`).
- **Against `run_perps_backtest`**, same signal (`audit-sma-20-50`), same parameters, same bars. An emulation of the old replay reproduces its trades, prices and amounts exactly, so the gap is fully explained (`vs_backtest.py`):

| Run | Old replay end equity | Stops that gap fill at the open | Mark stamped at the bar close (the live session) | Harness order | Harness ÷ old |
|---|---|---|---|---|---|
| main, whole data | 895.18 | 895.18 (0.00%) | 935.22 (+4.47%) | 936.61 (+0.15%) | 1.046 |
| main, bars from 2024 | 1,565.04 | 1,565.04 (0.00%) | 1,363.13 (−12.90%) | 1,364.08 (+0.07%) | 0.872 |
| spot-perps, whole data | 3,528.17 | 3,528.17 (0.00%) | 3,281.77 (−6.98%) | 3,281.85 (0.00%) | 0.930 |
| spot-perps, bars from 2024 | 2,569.29 | 2,569.29 (0.00%) | 2,474.95 (−3.67%) | 2,475.04 (0.00%) | 0.963 |

  The one cause that matters is in the old replay: it stamps `mark` with the bar's open time (`backtest.py:115-117`), so the UTC day rolls one bar late (a coin stopped yesterday re-enters at 04:00, not 00:00) and borrow accrues one bar late. The harness follows the live session here.
- **Live journal.** At the end of the data (2026-11-22 00:00) the harness has all three coins short and would open main at SOL 7.0x, ETH 7.2x, BTC 9.5x and degen at 9.3x, 9.5x, 12.6x. Live opened 23 hours later at 7.0x, 7.1x, 9.2x and 9.2x, 9.4x, 12.2x. Stop distance: harness 4.15%, 4.03%, 3.02% on main; live stops fired 4.12%, 4.06%, 3.09% from entry, each costing 30.0% of collateral (`live_check.py`).
- **Runs do not disturb each other.** The same run before and after other variants on one feed gives identical events and statistics (`misc.py`).
- **Data.** The 4h files have no gap on the shared axis and every 4h candle equals its four 1h candles. The 1h files have 10 exchange outages of 1 to 4 hours, all between 2020-11-30 and 2023-03-24 (`gaps.py`).

## 4. Not checked

- **Kraken against Binance.** Live reads Kraken USD candles; the replay uses Binance. No Kraken history was available offline, so differences in wicks, which decide stops, are unmeasured.
- **Fill delay.** Live fills at the latest price 90 seconds or more after the bar closes; the harness fills at the next bar's open. This needs finer data than I had.
- **The 1h path against the real session beyond nine months.** I drove the session over 2024-01 to 2024-10 only. The 10 outages in the 1h data are all in the dev window: there the harness skips the decision before the gap, and I did not replay what live would do in an outage.
- **The other scripts built on the harness**: `exp023_signal.py`, `exp023_sizing.py`, `exp023_degen.py`, `exp023_followup.py`, and `exp024_lib.py`, which is a separate copy of the harness. I only searched them for gates and cache labels.
- **Real venue costs.** Jupiter's borrow rate moves with pool use and its price impact with size. The harness uses the config values, as live paper does.

The audit's own scripts were scratch work and are not in the repository; each check above names the idea so it can be rebuilt.
