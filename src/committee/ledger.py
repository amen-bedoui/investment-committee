"""Tamper-evident paper-trading ledger (hash-chained JSON lines).

Each session records the committee's target weights for a date. Entries are
chained with SHA-256: editing or deleting any past entry breaks every hash
after it, which `verify` detects. This proves integrity of the record, not
profitability, and it is not a legal audit trail.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

import pandas as pd

from .portfolio import Config, Decision

GENESIS = "0" * 64


def _digest(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def append(path: str, decisions: list[Decision], date: pd.Timestamp, cfg: Config) -> dict:
    entries = read(path)
    day = pd.Timestamp(date).strftime("%Y-%m-%d")
    if entries and day <= entries[-1]["date"]:
        raise ValueError(f"ledger already has a session on or after {day}")
    entry = {
        "seq": len(entries) + 1, "date": day,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config_hash": cfg.fingerprint(),
        "weights": {d.ticker: round(d.weight, 6) for d in decisions if d.weight > 0},
        "scores": {d.ticker: round(d.composite, 4) for d in decisions},
        "prev_hash": entries[-1]["hash"] if entries else GENESIS,
    }
    entry["hash"] = _digest(entry)
    with open(path, "a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


def verify(path: str) -> tuple[bool, str]:
    prev = GENESIS
    for i, e in enumerate(read(path), 1):
        if e.get("seq") != i:
            return False, f"entry {i}: sequence number {e.get('seq')} (entry removed or reordered)"
        if e.get("prev_hash") != prev:
            return False, f"entry {i}: chain broken (previous entry altered or removed)"
        if _digest(e) != e.get("hash"):
            return False, f"entry {i}: content does not match its hash (entry edited)"
        prev = e["hash"]
    return True, f"ledger intact ({len(read(path))} sessions)"


def performance(path: str, prices: pd.DataFrame) -> pd.DataFrame:
    """Realised paper performance: each session's weights held until the next session (or last price)."""
    entries = read(path)
    rows, nav = [], 1.0
    for i, e in enumerate(entries):
        start = pd.Timestamp(e["date"])
        end = pd.Timestamp(entries[i + 1]["date"]) if i + 1 < len(entries) else prices.index[-1]
        if end <= start:
            continue
        seg = prices.loc[start:end]
        if len(seg) < 2:
            continue
        ret = sum(w * (seg[t].iloc[-1] / seg[t].iloc[0] - 1) for t, w in e["weights"].items() if t in seg)
        nav *= 1 + ret
        rows.append({"from": start.date(), "to": end.date(), "return": ret, "nav": nav})
    return pd.DataFrame(rows)
