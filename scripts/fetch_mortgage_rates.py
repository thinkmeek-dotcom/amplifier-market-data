"""
Weekly Freddie Mac 30-year fixed mortgage rates for the Amplifier site.

Source: Freddie Mac Primary Mortgage Market Survey (PMMS), official history CSV.
Output: data/mortgage-rates.json (trailing ~3 years of real weekly observations).

Safety rules:
  - Only actual published observations are written. No interpolation, no estimates.
  - The new data must pass every check below, or nothing is written and the
    last known good file stays in place.
  - Runs independently of the Realtor.com script, so a problem here can't
    affect the county and city market data.
"""

import csv
import io
import json
import os
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SOURCE_URL = "https://www.freddiemac.com/pmms/docs/PMMS_history.csv"
SOURCE_PAGE = "https://www.freddiemac.com/pmms"
OUT_FILE = Path(__file__).resolve().parent.parent / "data" / "mortgage-rates.json"

WINDOW_DAYS = 3 * 365 + 1      # trailing three years (~156 weekly observations)
MIN_POINTS = 140               # fewer than this in the window means something's wrong
MIN_RATE, MAX_RATE = 1.0, 20.0 # sanity bounds for a 30-year fixed rate
MIN_GAP, MAX_GAP = 4, 14       # days between weekly releases (holidays shift a day or two)
MAX_AGE_DAYS = 45              # newest observation older than this = stale feed


class ValidationError(Exception):
    pass


def download(url):
    local = os.environ.get("PMMS_LOCAL_FILE")  # for offline testing only
    if local:
        return Path(local).read_text(encoding="utf-8-sig")
    last_err = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "amplifier-market-data"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read().decode("utf-8-sig")
        except Exception as err:  # network hiccup: wait and retry
            last_err = err
            time.sleep(10 * (attempt + 1))
    raise ValidationError(f"Could not download Freddie Mac data: {last_err}")


def parse(text):
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "date" not in reader.fieldnames or "pmms30" not in reader.fieldnames:
        raise ValidationError(f"Unexpected columns: {reader.fieldnames}")
    rows = []
    for line in reader:
        raw_date = (line.get("date") or "").strip()
        raw_rate = (line.get("pmms30") or "").strip()
        if not raw_date or not raw_rate:
            continue  # blank rows are skipped, never filled in
        try:
            d = datetime.strptime(raw_date, "%m/%d/%Y").date()
        except ValueError:
            raise ValidationError(f"Unreadable date: {raw_date!r}")
        try:
            r = float(raw_rate)
        except ValueError:
            raise ValidationError(f"Unreadable rate on {raw_date}: {raw_rate!r}")
        rows.append((d, r))
    if not rows:
        raise ValidationError("No observations found in the file.")
    return rows


def validate(rows, today):
    dates = [d for d, _ in rows]
    if len(set(dates)) != len(dates):
        dupes = sorted({d for d in dates if dates.count(d) > 1})
        raise ValidationError(f"Duplicate dates: {dupes[:5]}")
    if dates != sorted(dates):
        raise ValidationError("Observations are not in date order.")

    latest = dates[-1]
    if latest > today + timedelta(days=1):
        raise ValidationError(f"Newest observation is in the future: {latest}")
    if (today - latest).days > MAX_AGE_DAYS:
        raise ValidationError(f"Newest observation is stale: {latest}")

    start = latest - timedelta(days=WINDOW_DAYS)
    window = [(d, r) for d, r in rows if d > start]
    if len(window) < MIN_POINTS:
        raise ValidationError(f"Only {len(window)} observations in the 3-year window.")

    for d, r in window:
        if not (MIN_RATE <= r <= MAX_RATE):
            raise ValidationError(f"Rate out of range on {d}: {r}")
    for (d1, _), (d2, _) in zip(window, window[1:]):
        gap = (d2 - d1).days
        if not (MIN_GAP <= gap <= MAX_GAP):
            raise ValidationError(f"Unexpected {gap}-day gap between {d1} and {d2}.")
    return window


def previous_latest():
    try:
        old = json.loads(OUT_FILE.read_text())
        return date.fromisoformat(old["latest"]["date"])
    except Exception:
        return None


def summarize(window):
    latest_d, latest_r = window[-1]
    high = max(window, key=lambda x: (x[1], x[0]))
    low = min(window, key=lambda x: (x[1], -x[0].toordinal()))
    # Year-ago: the actual observation closest to 52 weeks earlier (never invented).
    target = latest_d - timedelta(days=364)
    year_ago = min(window, key=lambda x: abs((x[0] - target).days))
    if abs((year_ago[0] - target).days) > 7:
        year_ago = None
    obs = lambda p: {"date": p[0].isoformat(), "rate": p[1]}
    return {
        "latest": obs(window[-1]),
        "high": obs(high),
        "low": obs(low),
        "year_ago": obs(year_ago) if year_ago else None,
        "change_vs_year_ago": round(latest_r - year_ago[1], 2) if year_ago else None,
    }


def main():
    today = datetime.now(timezone.utc).date()
    try:
        rows = parse(download(SOURCE_URL))
        window = validate(rows, today)
        prev = previous_latest()
        if prev and date.fromisoformat(window[-1][0].isoformat()) < prev:
            raise ValidationError(f"New data ({window[-1][0]}) is older than what we already have ({prev}).")
    except ValidationError as err:
        print(f"Mortgage rates NOT updated (kept last good file): {err}")
        sys.exit(1)

    out = {
        "series": "Freddie Mac 30-Year Fixed-Rate Mortgage Average in the United States",
        "note": "National weekly benchmark from Freddie Mac's Primary Mortgage Market Survey. Not a personalized mortgage quote.",
        "attribution": "Freddie Mac Primary Mortgage Market Survey®",
        "attribution_link": SOURCE_PAGE,
        "source_file": SOURCE_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **summarize(window),
        "observations": [{"date": d.isoformat(), "rate": r} for d, r in window],
    }
    new_text = json.dumps(out, indent=1)

    if prev and window[-1][0] == prev:
        # Same week as before: only rewrite if the numbers actually changed (e.g. a correction).
        old = json.loads(OUT_FILE.read_text())
        if old.get("observations") == out["observations"]:
            print(f"No new Freddie Mac release yet (latest still {prev}). Nothing to save.")
            return

    OUT_FILE.write_text(new_text + "\n")
    print(f"Saved {len(window)} weekly observations through {window[-1][0]} (latest {window[-1][1]}%).")


if __name__ == "__main__":
    main()
