"""Our Binance csv candles -> freqtrade futures feather files (+ flat mark and zero funding)."""

import sys
from pathlib import Path

import pandas as pd

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
out = dst / "binance" / "futures"
out.mkdir(parents=True, exist_ok=True)
for coin in ("btc", "eth", "sol"):
    for tf in ("4h", "1h"):
        df = pd.read_csv(src / f"{coin}_{tf}.csv")
        df["date"] = pd.to_datetime(df["ts_utc"], utc=True)
        df = df[["date", "open", "high", "low", "close", "volume"]].astype(
            {c: float for c in ("open", "high", "low", "close", "volume")}
        )
        name = f"{coin.upper()}_USDT_USDT"
        df.reset_index(drop=True).to_feather(out / f"{name}-{tf}-futures.feather")
        if tf == "1h":
            df.reset_index(drop=True).to_feather(out / f"{name}-1h-mark.feather")
            for ftf in ("1h", "8h"):
                f = df.set_index("date").resample(ftf).first().dropna().reset_index()
                f[["open", "high", "low", "close"]] = 0.0
                f["volume"] = 0.0
                f.to_feather(out / f"{name}-{ftf}-funding_rate.feather")
                if ftf == "8h":
                    m = (
                        df.set_index("date")
                        .resample("8h")
                        .agg(
                            {
                                "open": "first",
                                "high": "max",
                                "low": "min",
                                "close": "last",
                                "volume": "sum",
                            }
                        )
                        .dropna()
                        .reset_index()
                    )
                    m.to_feather(out / f"{name}-8h-mark.feather")
print(sorted(p.name for p in out.iterdir()))
