# Data Architecture

**Document status:** Draft for owner review
**Version:** 0.2
**Date:** 2026-10-08
**Owner:** Dahari Morgan-Parker
**Depends on:** `product-requirements.md` §3, `architecture.md` §6.3, §6.4, §6.13, §17
**Used by:** `strategy-spec.md`, `experiment-plan.md`, `execution-plan.md`, `code-session-handoff.md`

Status labels: **APPROVED** (D-nn), **HYPOTHESIS** (H-nn), **RECOMMENDATION** (R-nn), **UNRESOLVED** (UD-nn).

---

## 1. Purpose and scope

This document specifies how market and later alternative data enter the system: provider interfaces, the staged source roadmap, canonical identifiers, the UTC timestamp policy, data-quality checks, immutable backtest datasets, feature lineage, look-ahead prevention, retention, and degraded behavior. It implements the progressive provider architecture (D-37), in which interfaces anticipate later sources but V1 does not depend on them (D-38).

## 2. Source roadmap

| Tier | Sources (D-37) | Typical data | Uses | Stage | Required by V1? |
|---|---|---|---|---|---|
| **V1** | Price/candles, volume, volatility, technical features | OHLCV for 1h and 4h (1m later); features derived from them | Signals, regime, sizing (ATR), eligibility (liquidity, history), evaluation | M1 | Yes, the only required tier |
| **V1.5** | Order book, cross-asset relationships, derivatives data where available | Top-of-book spread and depth; correlations and relative strength; funding rates, open interest, basis (read-only) | Spread eligibility, minute-level refinement, slippage estimates, features | V1.5 | No |
| **V2** | News, on-chain information, macroeconomic inputs | Headlines and events; network activity; rates, indices | Features; AI interpretation of unstructured sources (D-31) | V2 | No |
| **Experimental** | Social sentiment and other alternative signals | Sentiment scores; alternative indicators | Research environment only | Research | No |

Derivatives *data* is an input only. Derivatives are never traded (SAFE-02).

## 3. Provider interfaces

### 3.1 Design rules

- Each source type has a framework-neutral protocol in `trader.data.providers` that returns domain types (`Candle`, `DatasetManifest`) or plain typed records, never vendor objects.
- Providers report health (`ok`, `degraded`, `unavailable`) and never invent values for missing data.
- Every provider response records `provider_id`, `venue_id` (where relevant), `retrieved_at_utc`, and the symbol mapping used (v0.1 §6.3).
- The V1 decision pipeline requires only a `CandleProvider`. Other providers are optional registrations and can be listed in a profile only with `required_for_trading: false` while the system is at V1 (PV-07).

### 3.2 Protocols

```python
class ProviderHealth(StrEnum):
    OK = "ok"; DEGRADED = "degraded"; UNAVAILABLE = "unavailable"

class CandleProvider(Protocol):                       # V1
    provider_id: str
    def fetch_candles(self, instrument_id: str, timeframe: str,
                      start_utc: datetime, end_utc: datetime) -> list[Candle]: ...
    def health(self) -> ProviderHealth: ...

class OrderBookProvider(Protocol):                    # V1.5
    def top_of_book(self, instrument_id: str, as_of_utc: datetime) -> "BookTop | None": ...

class CrossAssetProvider(Protocol):                   # V1.5
    def series(self, series_id: str, start_utc: datetime, end_utc: datetime) -> "list[SeriesPoint]": ...

class DerivativesDataProvider(Protocol):              # V1.5, read-only data
    def funding_rates(self, instrument_id: str, start_utc: datetime, end_utc: datetime) -> "list[SeriesPoint]": ...
    def open_interest(self, instrument_id: str, start_utc: datetime, end_utc: datetime) -> "list[SeriesPoint]": ...

class NewsProvider(Protocol):                         # V2
    def items(self, start_utc: datetime, end_utc: datetime, assets: list[str]) -> "list[NewsItem]": ...

class OnChainProvider(Protocol):                      # V2
    def metric(self, asset_id: str, metric_id: str, start_utc: datetime, end_utc: datetime) -> "list[SeriesPoint]": ...

class MacroProvider(Protocol):                        # V2
    def series(self, series_id: str, start_utc: datetime, end_utc: datetime) -> "list[SeriesPoint]": ...

class AlternativeSignalProvider(Protocol):            # Experimental
    def signal(self, signal_id: str, start_utc: datetime, end_utc: datetime) -> "list[SeriesPoint]": ...
```

Every `SeriesPoint` carries both `observed_at_utc` (when the value refers to) and `available_at_utc` (when the system could first have known it). Point-in-time joins use `available_at_utc` (§9).

### 3.3 V1 implementations

| Provider | Purpose | Network | Notes |
|---|---|---|---|
| `CsvCandleProvider` | Import owner-supplied CSV files | None | Columns `open_time_utc,open,high,low,close,volume`; ISO-8601 `Z` or epoch milliseconds |
| `SyntheticCandleProvider` | Deterministic test and demo data | None | Seeded regime-switching random walk; parameters are test fixtures with no market meaning |
| `CcxtPublicCandleProvider` | Download public OHLCV | Public endpoints only | Optional install extra; venue must be given explicitly (no default, UD-20); no API keys; rate-limited; mocked in tests |

### 3.4 Registry

`ProviderRegistry` maps `source_id` (from the profile's `data_sources`) to provider instances. Compiling a profile fails with `DATA_SOURCE_NOT_PERMITTED` if a source required for trading has no registered V1 provider.

---

## 4. Canonical asset and market identifiers

### 4.1 Identifiers

| Identifier | Format | Example | Notes |
|---|---|---|---|
| `asset_id` | Uppercase ticker, 2 to 15 characters | `BTC`, `ETH` | Venue aliases (for example `XBT`) map to the canonical ID in the registry |
| `instrument_id` | `BASE-QUOTE` (spot only) | `BTC-USD` | v0.1's `BTC/USD` notation becomes `BTC-USD` |
| `venue_id` | Lowercase | `sim`, `csv`, `ccxt-<exchange>` | `sim` is the internal simulator |
| `market_id` | `venue_id:venue_symbol` | `ccxt-<exchange>:BTC/USD` | Venue-specific symbol |
| `timeframe` | `1m`, `5m`, `15m`, `1h`, `4h`, `1d` | `4h` | Decision timeframes in V1: `1h`, `4h` (D-16) |

The canonical quote currency is USD. Mapping a stablecoin quote (for example USDT) to USD requires an explicit registry flag and a recorded depeg-risk note (UD-20).

### 4.2 Asset registry (`configs/universe/assets.yaml`)

```yaml
schema_version: "1.0.0"
kind: AssetRegistry
version: 1
assets:
  - asset_id: BTC
    name: Bitcoin
    tier: core                # D-26: BTC is a Core asset
    tier_status: approved
    aliases: [XBT]
    blocked: false
  - asset_id: ETH
    name: Ether
    tier: core                # D-26
    tier_status: approved
    aliases: []
    blocked: false
instruments:
  - {instrument_id: BTC-USD, base: BTC, quote: USD, type: spot, quantity_step: "0.00000001"}
  - {instrument_id: ETH-USD, base: ETH, quote: USD, type: spot, quantity_step: "0.00000001"}
market_symbol_map:
  - {market_id: "sim:BTC-USD", venue_id: sim, venue_symbol: BTC-USD, instrument_id: BTC-USD}
  - {market_id: "sim:ETH-USD", venue_id: sim, venue_symbol: ETH-USD, instrument_id: ETH-USD}
  - {market_id: "csv:BTC-USD", venue_id: csv, venue_symbol: BTC-USD, instrument_id: BTC-USD}
  - {market_id: "csv:ETH-USD", venue_id: csv, venue_symbol: ETH-USD, instrument_id: ETH-USD}
```

`quantity_step` is a simulator setting, not a risk value. It is replaced by the venue's lot rules once UD-20 is resolved. Major and Speculative assets are added only after UD-06 and UD-18 are resolved.

### 4.3 Tier rules (D-26)

| Tier | Admission | Limits |
|---|---|---|
| Core | BTC, ETH, or other assets explicitly approved by the owner as Core | Core per-asset cap (H-01 for Balanced) |
| Major | Established, liquid altcoins passing Major thresholds (UD-18) and listed under UD-06 | Major per-asset cap (H-02) |
| Speculative | Smaller or higher-volatility assets passing Speculative thresholds (UD-18), strict limits | Per-asset cap (H-03) and total cap (H-04) |
| Blocked | Fails liquidity, data-history, spread, support, or explicit exclusion rules | Not tradable |

### 4.4 Eligibility rules (`configs/universe/eligibility.yaml`)

Every asset, including Core assets and manual allowlist entries, is evaluated at each decision time with point-in-time data (D-25). Thresholds are UNRESOLVED (UD-18). A criterion with a `TBD` threshold fails closed, so the asset is treated as Blocked with reason `ELIGIBILITY_THRESHOLD_UNRESOLVED`.

```yaml
schema_version: "1.0.0"
kind: EligibilityRules
version: 1
criteria:
  liquidity:
    metric: median_daily_quote_volume_usd_30d     # from candles: sum(volume x close) per UTC day
    min_by_tier:
      core:        {value: TBD, status: unresolved, ref: UD-18}
      major:       {value: TBD, status: unresolved, ref: UD-18}
      speculative: {value: TBD, status: unresolved, ref: UD-18}
  data_history:
    metric: days_of_continuous_history            # point-in-time, ending at the decision time
    min_by_tier:
      core:        {value: TBD, status: unresolved, ref: UD-18}
      major:       {value: TBD, status: unresolved, ref: UD-18}
      speculative: {value: TBD, status: unresolved, ref: UD-18}
  spread:
    metric: median_relative_spread_bps
    max_by_tier:
      core:        {value: TBD, status: unresolved, ref: UD-18}
      major:       {value: TBD, status: unresolved, ref: UD-18}
      speculative: {value: TBD, status: unresolved, ref: UD-18}
    when_no_spread_data: {value: TBD, status: unresolved, ref: UD-18}   # R-21 recommends not_applicable
  support:
    rule: instrument_has_market_mapping_for_active_venue
  explicit_exclusion:
    rule: not_in_profile_disallowed_assets_and_not_registry_blocked
tier_assignment:
  core: owner_approved_only                                         # D-26
  major:       {value: TBD, status: unresolved, ref: UD-06}
  speculative: {value: TBD, status: unresolved, ref: UD-06}
```

### 4.5 Spread criterion on candle-only V1 data (RECOMMENDATION R-21)

D-26 lists spread among the Blocked criteria, but V1 data (candles) contains no spread. Recommendation: in V1 the spread criterion evaluates to `not_applicable` and its absence is offset by conservative slippage in the cost scenarios (`experiment-plan.md` §6). It becomes mandatory as soon as V1.5 order-book data exists. Until the owner confirms this in UD-18, `when_no_spread_data` stays `TBD` and fails closed; the M1 demo supplies `not_applicable` only as a labelled experiment input.

### 4.6 `UniverseSnapshot`

Produced at each decision time and journaled (`UNIVERSE_EVALUATED`): for each asset, its tier, eligibility status, the outcome of each criterion (`pass`, `fail`, `not_applicable`, `unresolved`), the measured values, and the threshold references. AI ranking of eligible assets (D-31; V2) is a separate field that never changes eligibility.

---

## 5. UTC timestamp policy and candle time convention (RECOMMENDATION R-07; ADR-017)

1. All timestamps are timezone-aware UTC. Naive timestamps are rejected at every boundary (provider, loader, contract) with `NAIVE_TIMESTAMP`.
2. Serialization is ISO-8601 with `Z`. Market and decision times use second precision; wall-clock `recorded_at_utc` may use microseconds.
3. Candles are labelled by `open_time_utc`. `close_time_utc = open_time_utc + timeframe`. A candle becomes available at its `close_time_utc` and never earlier.
4. Bars are aligned to UTC boundaries: `1h` on the hour, `4h` at 00:00, 04:00, 08:00, 12:00, 16:00, 20:00, and `1d` at 00:00.
5. A decision at time `t` (a bar close) may use only candles with `close_time_utc <= t`. Orders decided at `t` fill no earlier than the open of the bar starting at `t` (next-bar-open fill).
6. **Freshness.** At decision time `t`, the expected latest closed candle has `close_time_utc = t` (`t` aligned down to the timeframe). If that candle is missing, the snapshot is stale. In backtests this is parameter-free. In forward paper sessions the check runs `paper_grace_seconds` (UD-17) after `t` to allow for publication delay.
7. The trading day for daily loss limits is the UTC calendar day; day-start equity is the equity marked at 00:00:00 UTC.
8. Forward paper sessions compare the system clock with a reference time source; skew beyond tolerance (UD-17) engages the kill switch.

---

## 6. Data-quality checks

Every dataset is checked when created and re-verified when loaded. A failed `error` check makes the dataset unusable (`DATA_QUALITY_FAILED`). Warnings are recorded in the manifest's quality report and the journal.

| Check | What it verifies | Severity | Action |
|---|---|---|---|
| DQ-01 Schema | Required columns present; numeric types; no nulls in OHLCV | error | Reject dataset |
| DQ-02 UTC | All timestamps timezone-aware UTC | error | Reject (`NAIVE_TIMESTAMP`) |
| DQ-03 Alignment | `open_time_utc` aligned to the timeframe boundary | error | Reject |
| DQ-04 Ordering | Strictly increasing after a stable sort; source misordering recorded | warning (if fixable by sort) | Sort and record |
| DQ-05 Duplicates | Exact duplicates dropped; conflicting duplicates (same time, different values) | warning / error | Drop exact; reject conflicting |
| DQ-06 Gaps | Missing bars listed with ranges | warning | Never filled; a missing bar makes that decision time stale |
| DQ-07 OHLC consistency | `low <= min(open, close)`, `high >= max(open, close)`, `low <= high`, all prices > 0 | error | Reject |
| DQ-08 Volume | Volume ≥ 0; zero-volume bars flagged | error / warning | Reject negative; flag zero |
| DQ-09 Outlier returns | Absolute log return above a robust threshold (RECOMMENDATION: 8 rolling median absolute deviations over 30 days) | warning | Flag for review; never auto-corrected |
| DQ-10 Coverage | Requested range covered; enough history for warm-up | error | Reject for the run (`INSUFFICIENT_HISTORY`) |
| DQ-11 Incomplete candles | No candle with `close_time_utc` after the retrieval time | warning | Drop the incomplete candle |
| DQ-12 Cross-timeframe consistency | 4h candles agree with aggregated 1h candles within tolerance | warning | Flag (V1 should-have) |

---

## 7. Immutable backtest datasets

### 7.1 Storage layout

```text
data/
  raw/<provider>/<venue>/<instrument_id>/<timeframe>/<retrieval-timestamp>.(csv|json)
  datasets/<dataset_id>/candles.parquet
  datasets/<dataset_id>/manifest.json
```

### 7.2 `DatasetManifest`

| Field | Description |
|---|---|
| `dataset_id` | `ds-` plus the first 16 hex characters of `content_sha256` |
| `schema_version` | Manifest schema version |
| `instrument_id`, `timeframe` | Canonical identifiers |
| `source` | `provider_id`, `venue_id`, `venue_symbol`, `retrieved_at_utc`, source label |
| `range` | First and last `open_time_utc` |
| `row_count` | Number of candles |
| `content_sha256` | SHA-256 over a canonical serialization: the identity fields above, then one line per candle `open_time_utc,open,high,low,close,volume` with normalized decimal strings |
| `quality_report` | Results of DQ-01 to DQ-12, gap list, overall `pass`, `pass_with_warnings`, or `fail` |
| `parent_dataset_ids` | For derived datasets (for example resampled) |
| `created_at_utc` | Wall-clock creation time (not part of the hash) |

### 7.3 Immutability rules

- Datasets are write-once. Files are made read-only after creation. Creating a dataset whose ID already exists is a no-op that returns the existing ID; the store never overwrites.
- Identical inputs always produce the same `dataset_id` (T-17).
- Every backtest, experiment, and report references dataset IDs, never file paths.
- Re-validation on load recomputes the hash; a mismatch fails the run with `DATASET_INTEGRITY_FAILED` (exit code 4).

---

## 8. Feature lineage

- Feature definitions are registered in code with a name, parameters, input columns, warm-up length, and a version. `definitions_hash` is the hash of the canonical definition list.
- A `FeatureSet` records `feature_set_version`, `definitions_hash`, `input_dataset_ids`, `as_of_utc`, and `max_input_close_time_utc`.
- Lineage chain: `run_id` → `dataset_ids` → `feature_set_version` and `definitions_hash` → `FeatureSet` → `SignalCandidate` → `EnsembleDecision` → `RiskDecision` → `OrderIntent`.
- Feature set `features-v1` (V1): `sma_20`, `sma_50`, `sma_200`, `atr_14`, `rsi_14`, `bb_mid_20`, `bb_lower_20_2`, `bb_upper_20_2`, `donchian_high_20`, `donchian_low_10`, `realized_vol_30`, `log_return_1`, `volume_zscore_30`, `drawdown_from_peak`. M1 needs only `sma_20`, `sma_50`, and `atr_14` (`features-m1`).
- Fitted transformations (scalers, ML models) are fitted on training folds only, and their fitted state is versioned with the fold ID (P8).

## 9. Look-ahead and leakage prevention

Design mechanisms (the corresponding checks LA-01 to LA-08 are in `experiment-plan.md` §5):

| Mechanism | How |
|---|---|
| Availability-based access | The snapshot builder exposes only rows with `close_time_utc <= t` (candles) or `available_at_utc <= t` (other series). Strategies cannot reach the underlying dataset. |
| Causal feature computation | Features are computed with trailing windows only; `max_input_close_time_utc <= as_of_utc` is validated on every `FeatureSet`. |
| Next-bar execution | Orders decided at `t` fill at the next bar's open or later, never at the decision bar's close. |
| Point-in-time universe | Eligibility uses only data up to `t`; assets are not selected using future liquidity or survival. |
| Fold-scoped fitting | Fitted transformations and models use training folds only, with an embargo before validation. |
| Sealed holdout | The final test period is sealed; access is logged and counted (`experiment-plan.md` §3). |
| Incomplete-candle rejection | Candles not yet closed at retrieval time are dropped (DQ-11). |
| Timestamp discipline | UTC only; naive timestamps rejected (§5). |

## 10. Retention considerations (UNRESOLVED UD-11)

V1 performs no automatic deletion. The table shows the recommended policy (UD-11 option B), which is not yet approved.

| Data category | Recommended retention | Rule |
|---|---|---|
| Journals (`TradeEvent`) | Indefinite | Audit trail |
| Experiment records and promotion records | Indefinite | Evidence for decisions |
| Datasets referenced by any experiment or promotion record | Indefinite | Never deleted while referenced |
| Unreferenced raw downloads (minute data) | 12 months | Re-downloadable |
| Reports | Indefinite (small) | Reproducible from journal and datasets |
| Operational state history (kill switch, breaker) | Indefinite | Audit trail |
| Structured logs | 90 days | Operational debugging |
| Model artifacts | Indefinite for champions and approved versions; 12 months for rejected | Reproducibility |

Local data stays out of source control (`data/` is git-ignored). Backups are manual in V1 and become part of the hosted design (P10).

## 11. Degraded behavior when a provider is unavailable

General rules: a missing value never becomes a default number (null means abstain); a provider outage never relaxes a risk limit; every degraded state is journaled (`DATA_STALE` for candles, `PROVIDER_DEGRADED` for other sources) and shown in reports.

| Source | Tier | Behavior when unavailable or stale | Recovery |
|---|---|---|---|
| Candles | V1 | Backtest: a missing dataset blocks the run (exit 2); a missing bar makes that decision time stale. Paper: no new orders for the instrument (RR-06); after N consecutive stale cycles (UD-17) the kill switch engages; open positions and attached stops unchanged (UD-19 interim) | Automatic when fresh data returns; owner disengages the kill switch if it engaged |
| Fee schedule | V1 | Use the run's configured cost scenario; never assume zero fees | Not applicable |
| Order book or spread | V1.5 | Spread eligibility follows the UD-18 rule; minute-level refinement falls back to the parent's unrefined order (M-04); slippage uses the cost scenario | Automatic |
| Cross-asset series | V1.5 | Dependent features are null; strategies that need them abstain; the others continue | Automatic |
| Derivatives data | V1.5 | As cross-asset | Automatic |
| News, on-chain, macro | V2 | As cross-asset; AI interpretation components report `unavailable` and contribute nothing | Automatic |
| Social sentiment, alternative signals | Experimental | Research only; no effect on the active trader | Not applicable |

## 12. Change log

| Version | Date | Change |
|---|---|---|
| 0.2 | 2026-10-08 | First issue: provider protocols, source roadmap, identifiers, registry and eligibility files, UTC policy, DQ-01 to DQ-12, immutable datasets, lineage, leakage prevention, retention, degraded behavior. |
