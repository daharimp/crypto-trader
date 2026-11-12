# ADR-035: Paper perps trades only when two trend rules agree

- **Status:** Accepted (2026-11-12; owner decision UD-29)
- **Owner decision UD-29 (2026-11-12):** asked whether to switch the paper session from the
  moving-average signal to the 1-month trend rule, the owner chose to "combine both to
  synthesize a result with the most evidence".
- **Context:** EXP-2026-015 reported that `sma_stance` 20/50 is not shown to make money on
  BTC or ETH, and that the 1-month trend rule did better. Each rule alone is always in the
  market, long or short.
- **Decision:**
  1. `trader.perps.signals` names three signals: `sma_stance_20_50`, `tsmom_30d` (the
     direction of the 30-day return), and `consensus_sma_tsmom`, which takes a side only
     when both agree and is flat when they disagree or either is warming up.
  2. `trader perps paper run --signal <name>` selects one; the default is the consensus.
     Signals still only say long, short, or flat; sizing and limits stay in the risk code.
  3. A saved session still refuses to continue under a different signal (ADR-031), so
     switching means moving the old state file aside and starting a new paper account.
- **Evidence, and its limits:** an exploratory check on 5 to 10 years of 4h candles at 1x
  (7 bps fees, 0.0016%/h borrow; not pre-registered, no uncertainty ranges) gave, per year on
  $2,500: BTC $479 / $1,097 / $912, ETH $1,306 / $2,759 / $2,155, SOL $1,815 / $1,995 /
  $2,035 for moving-average / 1-month / consensus, with the consensus in the market about
  65% of the time and the smallest worst drop on every coin (69% to 72% against 75% to 98%).
  So the consensus earned somewhat less than the 1-month rule on BTC and ETH with smaller
  drops. This is one look at history, not proof; a pre-registered test with ranges and the
  forward paper record are what count.
- **Consequences:** The historical replay on the dashboard still shows the moving-average
  signal. The consensus trades about twice as often as either rule, because it steps out
  and back in when they disagree.
