"""Trade-by-trade comparison of freqtrade's backtest with our engine's replay."""

import json
import statistics as st
import sys
import zipfile
from collections import Counter


def ours(path):
    ev = json.load(open(path))["events"]
    open_, out = {}, []
    for e in ev:
        m = e.get("market")
        if e["event"] == "OPENED":
            open_[m] = {
                "pair": m,
                "side": e["side"],
                "open": e["at_utc"][:16],
                "entry": float(e["entry"]),
                "lev": float(e["leverage"]),
                "coll": float(e["collateral_usd"]),
                "pnl": 0.0,
            }
        elif e["event"] == "TAKE_PROFIT" and m in open_:
            open_[m]["pnl"] += float(e["pnl_usd"]) - float(e["fees_usd"])
        elif e["event"] in ("CLOSED", "LIQUIDATED") and m in open_:
            t = open_.pop(m)
            if e["event"] == "CLOSED":
                t["pnl"] += float(e["pnl_usd"]) - float(e["fees_usd"])
                t["reason"] = e["reason"]
            else:
                t["pnl"] = -t["coll"]
                t["reason"] = "LIQUIDATED"
            t["close"] = e["at_utc"][:16]
            # Reason: the opening fee leaves cash at the open, so it is not in the closing pnl.
            t["roc"] = (t["pnl"] - t["coll"] * t["lev"] * 0.0007) / t["coll"] * 100
            out.append(t)
    return out


def ft(path):
    z = zipfile.ZipFile(path)
    j = json.loads(
        z.read(
            [
                n
                for n in z.namelist()
                if n.endswith(".json") and "config" not in n and "meta" not in n
            ][0]
        )
    )
    trades = next(iter(j["strategy"].values()))["trades"]
    out = []
    for t in trades:
        out.append(
            {
                "pair": t["pair"].split("/")[0],
                "side": "short" if t["is_short"] else "long",
                "open": t["open_date"][:16].replace(" ", "T"),
                "entry": t["open_rate"],
                "lev": t["leverage"],
                "reason": t["exit_reason"],
                "roc": t["profit_ratio"] * 100,
            }
        )
    return out


def report(name, o, f):
    ko = {(t["pair"], t["side"], t["open"]): t for t in o}
    kf = {(t["pair"], t["side"], t["open"]): t for t in f}
    both = sorted(set(ko) & set(kf))
    d_roc = [kf[k]["roc"] - ko[k]["roc"] for k in both]
    same_lev = sum(abs(kf[k]["lev"] - ko[k]["lev"]) < 1e-9 for k in both)
    close = sum(abs(x) < 1.0 for x in d_roc)
    print(f"## {name}")
    print(
        f"trades: ours {len(o)}, freqtrade {len(f)}; same coin+side+entry bar: {len(both)} "
        f"({len(both) / len(o) * 100:.0f}% of ours, {len(both) / len(f) * 100:.0f}% of freqtrade's)"
    )
    print(
        f"matched trades: same leverage {same_lev / len(both) * 100:.0f}%; result within 1 point of collateral "
        f"{close / len(both) * 100:.0f}%; median gap {st.median(d_roc):+.2f} pts, mean gap {st.mean(d_roc):+.2f} pts"
    )
    print(
        f"mean result per trade (% of collateral): ours {st.mean(t['roc'] for t in o):+.2f}, freqtrade {st.mean(t['roc'] for t in f):+.2f}"
    )
    print("exits ours:", dict(Counter(t["reason"] for t in o).most_common()))
    print("exits freqtrade:", dict(Counter(t["reason"] for t in f).most_common()))
    big = sorted(both, key=lambda k: -abs(kf[k]["roc"] - ko[k]["roc"]))[:3]
    for k in big:
        print(
            "  biggest gap",
            k,
            f"ours {ko[k]['roc']:+.1f} ({ko[k]['reason']}) ft {kf[k]['roc']:+.1f} ({kf[k]['reason']})",
        )
    only_o = Counter(ko[k]["reason"] for k in set(ko) - set(kf))
    print("  unmatched ours by exit of the trade:", dict(only_o))
    print()


if __name__ == "__main__":
    for name, a, b in [x.split(",") for x in sys.argv[1:]]:
        report(name, ours(a), ft(b))
