"""``trader data synth|import|fetch|validate|list``."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import typer

from trader.data.providers.csv_provider import CsvCandleProvider, CsvFormatError
from trader.data.providers.synthetic import SyntheticCandleProvider
from trader.data.quality import run_quality_checks
from trader.data.store import (
    DataQualityError,
    DatasetIntegrityError,
    DatasetNotFoundError,
    DatasetStore,
)
from trader.domain.market import SourceRef

from .common import EXIT_INTEGRITY, EXIT_INVALID, utc_option

app = typer.Typer(help="Create, validate, and list immutable datasets.", no_args_is_help=True)


def _quality_fail(exc: DataQualityError) -> None:
    """
    Print quality errors and exit 2.

    Args:
        exc (DataQualityError): Error.

    Raises:
        typer.Exit: Always (code 2).
    """
    for i in exc.report.errors:
        typer.echo(f"{i.check_id} {i.message} {i.detail}", err=True)
    typer.echo("DATA_QUALITY_FAILED", err=True)
    raise typer.Exit(EXIT_INVALID)


@app.command("synth")
def synth(
    instrument: str = typer.Option(..., "--instrument"),
    timeframe: str = typer.Option(..., "--timeframe"),
    start: str = typer.Option(..., "--start"),
    end: str = typer.Option(..., "--end"),
    seed: int = typer.Option(..., "--seed"),
    start_price: str = typer.Option(..., "--start-price"),
    daily_quote_volume_usd: str = typer.Option("1e9", "--daily-quote-volume-usd"),
) -> None:
    """Create a deterministic synthetic dataset and print its ID."""
    s, e = utc_option(start), utc_option(end)
    assert s and e
    prov = SyntheticCandleProvider(seed, Decimal(start_price), Decimal(daily_quote_volume_usd))
    try:
        candles = prov.fetch_candles(instrument, timeframe, s, e)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_INVALID) from None
    src = SourceRef(provider_id=prov.provider_id, venue_id=prov.venue_id, retrieved_at_utc=None)
    label = f"synthetic:seed={seed}:start_price={start_price}"
    try:
        m = DatasetStore().create(candles, instrument, timeframe, src, label)
    except DataQualityError as exc:
        _quality_fail(exc)
        return
    typer.echo(m.dataset_id)


@app.command("import")
def import_csv(
    csv: Path = typer.Option(..., "--csv", exists=True, dir_okay=False),
    instrument: str = typer.Option(..., "--instrument"),
    timeframe: str = typer.Option(..., "--timeframe"),
    source_label: str = typer.Option(..., "--source-label"),
) -> None:
    """Create a dataset from a CSV file and print its ID."""
    prov = CsvCandleProvider(csv)
    try:
        frame = prov.read_frame()
    except CsvFormatError as exc:
        typer.echo(f"DATA_QUALITY_FAILED: {exc}", err=True)
        raise typer.Exit(EXIT_INVALID) from None
    src = SourceRef(provider_id="csv", venue_id="csv", retrieved_at_utc=None)
    try:
        m = DatasetStore().create_from_frame(frame, instrument, timeframe, src, source_label)
    except DataQualityError as exc:
        _quality_fail(exc)
        return
    typer.echo(m.dataset_id)


@app.command("import-kraken")
def import_kraken(
    file: Path = typer.Option(
        ..., "--file", exists=True, dir_okay=False, help="Kraken OHLCVT file, e.g. XBTUSD_240.csv"
    ),
    instrument: str = typer.Option(..., "--instrument", help="e.g. BTC-USD"),
) -> None:
    """Create a dataset from Kraken's downloadable history; the interval comes from the name."""
    from trader.data.providers.kraken_csv import (
        KrakenCsvError,
        read_kraken_ohlcvt,
        timeframe_from_name,
    )

    try:
        timeframe = timeframe_from_name(file)
        frame = read_kraken_ohlcvt(file)
    except KrakenCsvError as exc:
        typer.echo(f"DATA_QUALITY_FAILED: {exc}", err=True)
        raise typer.Exit(EXIT_INVALID) from None
    src = SourceRef(provider_id="kraken_ohlcvt", venue_id="kraken", retrieved_at_utc=None)
    try:
        m = DatasetStore().create_from_frame(
            frame, instrument, timeframe, src, f"kraken-ohlcvt:{file.name}"
        )
    except DataQualityError as exc:
        _quality_fail(exc)
        return
    typer.echo(m.dataset_id)


@app.command("fetch")
def fetch(
    exchange: str = typer.Option(..., "--exchange", help="ccxt exchange ID (explicit, UD-20)."),
    symbol: str = typer.Option(..., "--symbol"),
    instrument: str = typer.Option(..., "--instrument"),
    timeframe: str = typer.Option(..., "--timeframe"),
    start: str = typer.Option(..., "--start"),
    end: str = typer.Option(..., "--end"),
) -> None:
    """Download public OHLCV (``ccxt`` extra; no API keys) and print the dataset ID."""
    from trader.data.providers.ccxt_public import CcxtPublicCandleProvider

    s, e = utc_option(start), utc_option(end)
    assert s and e
    prov = CcxtPublicCandleProvider(exchange, symbol)
    try:
        candles = prov.fetch_candles(instrument, timeframe, s, e)
    except ModuleNotFoundError:
        typer.echo("ccxt is not installed: run `uv sync --extra ccxt`", err=True)
        raise typer.Exit(EXIT_INVALID) from None
    retrieved = datetime.now(UTC)
    src = SourceRef(provider_id=prov.provider_id, venue_id=exchange, retrieved_at_utc=retrieved)
    try:
        m = DatasetStore().create(
            candles,
            instrument,
            timeframe,
            src,
            f"ccxt:{exchange}:{symbol}:{retrieved:%Y%m%dT%H%M%SZ}",
        )
    except DataQualityError as exc:
        _quality_fail(exc)
        return
    typer.echo(m.dataset_id)


@app.command("validate")
def validate(dataset_id: str = typer.Argument(...)) -> None:
    """Re-verify integrity (exit 4 on mismatch) and re-run quality checks (exit 2)."""
    try:
        m, df = DatasetStore().load(dataset_id)
    except DatasetIntegrityError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_INTEGRITY) from None
    except DatasetNotFoundError:
        typer.echo(f"dataset not found: {dataset_id}", err=True)
        raise typer.Exit(EXIT_INVALID) from None
    rep = run_quality_checks(df, m.timeframe, m.source.retrieved_at_utc)
    for i in rep.issues:
        typer.echo(f"{i.severity.upper()} {i.check_id} {i.message}")
    if not rep.ok:
        typer.echo("DATA_QUALITY_FAILED", err=True)
        raise typer.Exit(EXIT_INVALID)
    typer.echo(f"OK {m.dataset_id} {m.instrument_id} {m.timeframe} rows={m.row_count}")


@app.command("list")
def list_cmd() -> None:
    """List datasets."""
    for m in DatasetStore().list():
        typer.echo(
            f"{m.dataset_id}  {m.instrument_id:8} {m.timeframe:3} rows={m.row_count:6}  "
            f"{m.first_open_time_utc:%Y-%m-%d}..{m.last_open_time_utc:%Y-%m-%d}  {m.source_label}"
        )
