#!/usr/bin/env python3
"""
update_data.py
---------------
Pulls one (or more) days of call data from the Metabase "Calls" table (Analytics DB,
table id 12288 — a Five9 call log export) and upserts the aggregated daily metrics
into data.json, which index.html reads to render the rolling dashboard.

Designed to be run once a day, after the day is fully over, via cron or the bundled
GitHub Actions workflow (.github/workflows/update-dashboard.yml). It is idempotent:
re-running it for a date that's already in data.json simply recomputes and replaces
that day's entry.

Required environment variables (set as GitHub Actions secrets, or export locally):
  METABASE_URL       e.g. https://metabase.ops.tutenlabs.com
  METABASE_USER      Metabase login email
  METABASE_PASSWORD  Metabase login password

Optional environment variables:
  METABASE_DB_ID      default 136   (the "Analytics" database id)
  METABASE_TABLE_ID   default 12288 (the "Calls" table id)
  TARGET_DATE         default: yesterday (UTC), format YYYY-MM-DD
  DATA_JSON_PATH      default: data.json (relative to this script, or absolute path)

Usage:
  python update_data.py                  # updates yesterday's entry
  TARGET_DATE=2026-01-15 python update_data.py   # backfill a specific day
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

METABASE_URL = os.environ.get("METABASE_URL", "").rstrip("/")
METABASE_USER = os.environ.get("METABASE_USER", "")
METABASE_PASSWORD = os.environ.get("METABASE_PASSWORD", "")
DB_ID = int(os.environ.get("METABASE_DB_ID", "136"))
TABLE_ID = int(os.environ.get("METABASE_TABLE_ID", "12288"))
DATA_JSON_PATH = Path(os.environ.get("DATA_JSON_PATH", str(Path(__file__).parent / "data.json")))

FIELD_NAMES = ["timestamp", "disposition", "total_queue_time", "time_to_abandon", "talk_time"]
PAGE_SIZE = 2000


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def parse_dur(s):
    """Mirrors the browser-side parser used to build the historical backfill:
    the source table stores durations as day-fraction floats (e.g. 0.00123 = 106.5s),
    but a large share of rows are corrupted into comma-decimal scientific notation
    (e.g. '7,15E+09'). Treat anything that doesn't look like a clean 0..1 float as
    unparseable and exclude it from timing-based metrics."""
    if s is None or s == "":
        return None
    s = str(s)
    if "," in s or "e+" in s.lower():
        return None
    try:
        n = float(s)
    except ValueError:
        return None
    if n < 0 or n > 1:
        return None
    return n * 86400  # seconds


def get_session_token():
    if not (METABASE_URL and METABASE_USER and METABASE_PASSWORD):
        fail("METABASE_URL, METABASE_USER and METABASE_PASSWORD must all be set.")
    r = requests.post(
        f"{METABASE_URL}/api/session",
        json={"username": METABASE_USER, "password": METABASE_PASSWORD},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["id"]


def get_field_ids(session_token):
    r = requests.get(
        f"{METABASE_URL}/api/table/{TABLE_ID}/query_metadata",
        headers={"X-Metabase-Session": session_token},
        timeout=30,
    )
    r.raise_for_status()
    meta = r.json()
    ids = {}
    for name in FIELD_NAMES:
        f = next((f for f in meta["fields"] if f["name"] == name), None)
        if f is None:
            fail(f"Field '{name}' not found on table {TABLE_ID}. Has the schema changed?")
        ids[name] = f["id"]
    return ids


def fetch_day_rows(session_token, field_ids, date_str):
    start = date_str
    end = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    rows = []
    offset = 0
    while True:
        body = {
            "database": DB_ID,
            "type": "query",
            "query": {
                "source-table": TABLE_ID,
                "fields": [["field", field_ids[n], None] for n in FIELD_NAMES],
                "filter": [
                    "and",
                    [">=", ["field", field_ids["timestamp"], None], start],
                    ["<", ["field", field_ids["timestamp"], None], end],
                ],
                "limit": PAGE_SIZE,
                "offset": offset,
            },
        }
        r = requests.post(
            f"{METABASE_URL}/api/dataset",
            json=body,
            headers={"X-Metabase-Session": session_token},
            timeout=60,
        )
        r.raise_for_status()
        page = r.json().get("data", {}).get("rows", [])
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def aggregate_day(rows):
    day = {
        "total": 0, "answered": 0, "answered30s": 0, "answered2min": 0,
        "abandoned": 0, "transferredCbsi": 0, "slaHit5min": 0,
    }
    for ts, disp, tqt, tta, talk in rows:
        day["total"] += 1
        talk_sec = parse_dur(talk)
        is_answered = talk_sec is not None and talk_sec > 0
        is_abandoned = disp in ("Abandon", "Abandon - United Pacific")
        is_cbsi = disp == "Transferred To CBSI"
        queue_sec = parse_dur(tqt)
        abandon_sec = parse_dur(tta)

        if is_answered:
            day["answered"] += 1
            if queue_sec is not None:
                if queue_sec <= 30:
                    day["answered30s"] += 1
                if queue_sec <= 120:
                    day["answered2min"] += 1
                if queue_sec <= 300:
                    day["slaHit5min"] += 1
        if is_abandoned:
            day["abandoned"] += 1
            if abandon_sec is not None:
                if abandon_sec <= 300:
                    day["slaHit5min"] += 1
            elif queue_sec is not None and queue_sec <= 300:
                day["slaHit5min"] += 1
        if is_cbsi:
            day["transferredCbsi"] += 1
            if queue_sec is not None and queue_sec <= 300:
                day["slaHit5min"] += 1
    return day


def main():
    target_date = os.environ.get("TARGET_DATE")
    if not target_date:
        target_date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    if not DATA_JSON_PATH.exists():
        fail(f"{DATA_JSON_PATH} not found. Run this from the repo that contains data.json, "
             f"or set DATA_JSON_PATH.")

    with open(DATA_JSON_PATH) as f:
        store = json.load(f)

    print(f"Fetching {target_date} from Metabase table {TABLE_ID}...")
    token = get_session_token()
    field_ids = get_field_ids(token)
    rows = fetch_day_rows(token, field_ids, target_date)
    print(f"  {len(rows)} call records found.")

    day_metrics = aggregate_day(rows)
    day_metrics["date"] = target_date

    days = [d for d in store["days"] if d["date"] != target_date]
    days.append(day_metrics)
    days.sort(key=lambda d: d["date"])
    store["days"] = days
    store["generatedAt"] = datetime.now(timezone.utc).isoformat()

    with open(DATA_JSON_PATH, "w") as f:
        json.dump(store, f, indent=2)

    print(f"Upserted {target_date}: {day_metrics}")


if __name__ == "__main__":
    main()
