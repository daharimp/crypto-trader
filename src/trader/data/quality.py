"""Data-quality checks DQ-01 to DQ-12 (data-architecture.md §6)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

import numpy as np
import pandas as pd

from trader.common.clock import ensure_utc, format_utc, is_aligned, timeframe_delta
from trader.domain.market import QualityIssue

from .frames import COLUMNS, PRICE_COLS, columns

OUTLIER_MADS = 8  # RECOMMENDATION (DQ-09), warning only


@dataclass
class QualityReport:
    """Result of running the checks; ``frame`` is the cleaned, sorted frame."""

    frame: pd.DataFrame
    issues: list[QualityIssue] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """
        Whether no error-severity check failed.

        Returns:
            bool: True if usable.
        """
        return not any(i.severity == "error" for i in self.issues)

    @property
    def errors(self) -> list[QualityIssue]:
        """
        Error-severity issues.

        Returns:
            list[QualityIssue]: Errors.
        """
        return [i for i in self.issues if i.severity == "error"]


def _issue(check: str, sev: str, msg: str, **detail: object) -> QualityIssue:
    """
    Build a quality issue.

    Args:
        check (str): Check ID.
        sev (str): ``error`` or ``warning``.
        msg (str): Message.
        **detail: Extra detail (stringified).

    Returns:
        QualityIssue: Issue.
    """
    return QualityIssue(
        check_id=check,
        severity="error" if sev == "error" else "warning",
        message=msg,
        detail={k: str(v) for k, v in detail.items()},
    )


def run_quality_checks(
    df: pd.DataFrame, timeframe: str, retrieved_at_utc: datetime | None
) -> QualityReport:
    """
    Run DQ-01 to DQ-11 (DQ-12 is optional in M1 and not evaluated).

    Args:
        df (pd.DataFrame): Raw candle frame.
        timeframe (str): Timeframe label.
        retrieved_at_utc (datetime | None): Retrieval time for DQ-11, if known.

    Returns:
        QualityReport: Issues and the cleaned frame.
    """
    rep = QualityReport(frame=df)
    # DQ-01 schema
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing or df[COLUMNS].isna().any().any():
        rep.issues.append(_issue("DQ-01", "error", "missing columns or nulls", missing=missing))
        return rep
    if df.empty:
        rep.issues.append(_issue("DQ-10", "error", "dataset is empty"))
        return rep
    try:
        df = df.copy()
        for c in PRICE_COLS:
            df[c] = pd.Series([Decimal(str(v)) for v in columns(df, c)], dtype=object)
    except (InvalidOperation, ValueError):
        rep.issues.append(_issue("DQ-01", "error", "non-numeric OHLCV values"))
        return rep
    # DQ-02 UTC
    times_raw = columns(df, "open_time_utc")
    naive = [t for t in times_raw if not isinstance(t, datetime) or t.tzinfo is None]
    if naive:
        rep.issues.append(_issue("DQ-02", "error", "NAIVE_TIMESTAMP", count=len(naive)))
        return rep
    df["open_time_utc"] = [ensure_utc(t) for t in times_raw]
    # DQ-03 alignment
    bad = [format_utc(t) for t in columns(df, "open_time_utc") if not is_aligned(t, timeframe)]
    if bad:
        rep.issues.append(_issue("DQ-03", "error", "misaligned open times", first=bad[0]))
    # DQ-04 ordering
    if not df["open_time_utc"].is_monotonic_increasing:
        rep.issues.append(_issue("DQ-04", "warning", "rows were out of order; sorted"))
    df = df.sort_values("open_time_utc", kind="stable").reset_index(drop=True)
    # DQ-05 duplicates
    dup_mask = df.duplicated("open_time_utc", keep=False)
    if dup_mask.any():
        distinct = df[dup_mask].drop_duplicates(subset=COLUMNS)
        conflict_times = sorted(set(columns(distinct[distinct.duplicated("open_time_utc")],
                                            "open_time_utc")))
        if conflict_times:
            rep.issues.append(
                _issue("DQ-05", "error", "conflicting duplicates", at=format_utc(conflict_times[0]))
            )
        else:
            rep.issues.append(_issue("DQ-05", "warning", "exact duplicates dropped"))
        df = df.drop_duplicates("open_time_utc", keep="first").reset_index(drop=True)
    # DQ-07 OHLC consistency
    bad_ohlc = [
        format_utc(t)
        for t, o, h, lo, c in zip(*(columns(df, k) for k in COLUMNS[:5]), strict=True)
        if min(o, h, lo, c) <= 0 or lo > min(o, c) or h < max(o, c)
    ]
    if bad_ohlc:
        rep.issues.append(_issue("DQ-07", "error", "OHLC inconsistent", first=bad_ohlc[0],
                                 count=len(bad_ohlc)))
    # DQ-08 volume
    vols = columns(df, "volume")
    if any(v < 0 for v in vols):
        rep.issues.append(_issue("DQ-08", "error", "negative volume"))
    zero = sum(1 for v in vols if v == 0)
    if zero:
        rep.issues.append(_issue("DQ-08", "warning", "zero-volume bars", count=zero))
    # DQ-11 incomplete candles
    delta = timeframe_delta(timeframe)
    if retrieved_at_utc is not None:
        keep = [t + delta <= retrieved_at_utc for t in columns(df, "open_time_utc")]
        if not all(keep):
            rep.issues.append(
                _issue("DQ-11", "warning", "incomplete candle dropped", count=keep.count(False))
            )
            df = df[keep].reset_index(drop=True)
    # DQ-06 gaps (never filled)
    times = columns(df, "open_time_utc")
    for a, b in zip(times, times[1:], strict=False):
        if b - a > delta:
            rep.gaps.append(f"{format_utc(a + delta)}/{format_utc(b)}")
    if rep.gaps:
        rep.issues.append(_issue("DQ-06", "warning", "gaps (not filled)", count=len(rep.gaps),
                                 first=rep.gaps[0]))
    # DQ-09 outlier returns (warning)
    n_out = _outliers(df, timeframe)
    if n_out:
        rep.issues.append(_issue("DQ-09", "warning", "outlier returns flagged", count=n_out))
    if df.empty:
        rep.issues.append(_issue("DQ-10", "error", "no complete candles"))
    rep.frame = df
    return rep


def _outliers(df: pd.DataFrame, timeframe: str) -> int:
    """
    Count returns beyond ``OUTLIER_MADS`` rolling MADs over 30 days (DQ-09).

    Args:
        df (pd.DataFrame): Clean frame.
        timeframe (str): Timeframe.

    Returns:
        int: Number of flagged bars.
    """
    if len(df) < 3:
        return 0
    closes = np.array([float(c) for c in columns(df, "close")])
    r = pd.Series(np.diff(np.log(closes)))
    window = max(3, int(30 * 86400 / timeframe_delta(timeframe).total_seconds()))
    med = r.rolling(window, min_periods=10).median()
    mad = (r - med).abs().rolling(window, min_periods=10).median()
    flagged = (r - med).abs() > OUTLIER_MADS * mad
    return int(flagged[mad.notna() & (mad > 0)].sum())
