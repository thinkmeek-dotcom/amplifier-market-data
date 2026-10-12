"""
Amplifier market data — Step 1: prove the data.

Downloads Redfin's public county market tracker, keeps only our 9 North Georgia
counties, and saves the latest numbers to data/market-snapshot.json plus a
human-readable data/summary.md. Nothing on the website uses this yet.
"""
import csv
import gzip
import io
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SOURCE_URL = (
    "https://redfin-public-data.s3.us-west-2.amazonaws.com/"
    "redfin_market_tracker/county_market_tracker.tsv000.gz"
)
COUNTIES = ["Barrow", "Jackson", "Gwinnett", "Hall", "Oconee",
            "Clarke", "Walton", "Morgan", "Forsyth"]
FIELDS = ["median_list_price", "median_sale_price", "avg_sale_to_list",
          "median_dom", "homes_sold"]
OUT_DIR = Path(__file__).resolve().parent.parent / "data"

csv.field_size_limit(10**7)

DEBUG = {"latest_period_in_file": "", "ga_regions_named_like_missing": set()}


def clean(value):
    return (value or "").strip().strip('"').strip()


def to_number(value):
    value = clean(value)
    if value in ("", "NA", "nan", "None"):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def county_from_region(region):
    # Redfin writes regions like "Barrow County, GA". Some consolidated
    # governments use longer names (e.g. "Athens-Clarke County, GA").
    region = clean(region).lower()
    if not region.endswith(", ga"):
        return None
    for name in COUNTIES:
        n = name.lower()
        if region == f"{n} county, ga" or region.endswith(f"-{n} county, ga"):
            return name
    return None


def read_rows(stream):
    text = io.TextIOWrapper(gzip.GzipFile(fileobj=stream), encoding="utf-8")
    reader = csv.reader(text, delimiter="\t")
    header = [clean(h).lower() for h in next(reader)]
    for raw in reader:
        if len(raw) != len(header):
            continue
        yield {k: v for k, v in zip(header, raw)}


def latest_by_county(rows):
    """Keep the most recent All Residential, non-seasonally-adjusted row per
    county (and per period length, in case Redfin publishes more than one)."""
    best = {}
    durations_seen = set()
    DEBUG["latest_period_in_file"] = ""
    for row in rows:
        period_end_any = clean(row.get("period_end"))
        if period_end_any > DEBUG["latest_period_in_file"]:
            DEBUG["latest_period_in_file"] = period_end_any
        region_raw = clean(row.get("region"))
        if region_raw.lower().endswith(", ga") and any(
            w in region_raw.lower() for w in ("oconee", "clarke")
        ):
            DEBUG["ga_regions_named_like_missing"].add(region_raw)
        county = county_from_region(row.get("region"))
        if not county:
            continue
        if clean(row.get("property_type")).lower() != "all residential":
            continue
        if clean(row.get("is_seasonally_adjusted")).lower() in ("true", "t", "1"):
            continue
        duration = clean(row.get("period_duration")) or "unknown"
        durations_seen.add(duration)
        key = (county, duration)
        period_end = clean(row.get("period_end"))
        if key not in best or period_end > best[key]["period_end"]:
            best[key] = {
                "county": county,
                "period_duration": duration,
                "period_begin": clean(row.get("period_begin")),
                "period_end": period_end,
                **{f: to_number(row.get(f)) for f in FIELDS},
            }
    return best, durations_seen


def fmt_money(v):
    return "—" if v is None else f"${v:,.0f}"


def fmt_ratio(v):
    return "—" if v is None else f"{v * 100:.1f}%"


def fmt_int(v):
    return "—" if v is None else f"{v:,.0f}"


def write_outputs(best, durations_seen):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    records = sorted(best.values(), key=lambda r: (r["period_duration"], COUNTIES.index(r["county"])))
    snapshot = {
        "source": "Redfin Data Center (county market tracker)",
        "source_url": SOURCE_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "period_durations_found": sorted(durations_seen),
        "counties": records,
    }
    (OUT_DIR / "market-snapshot.json").write_text(json.dumps(snapshot, indent=2))

    lines = ["# Amplifier market snapshot", "",
             f"Generated {snapshot['generated_at']} from Redfin.", ""]
    missing = [c for c in COUNTIES if not any(r["county"] == c for r in records)]
    for duration in sorted(durations_seen):
        lines += [f"## Period length: {duration}", "",
                  "| County | Period | List price | Sold price | Sale-to-list | Days on market | Homes sold |",
                  "|---|---|---|---|---|---|---|"]
        for r in records:
            if r["period_duration"] != duration:
                continue
            lines.append(
                f"| {r['county']} | {r['period_begin']} to {r['period_end']} | "
                f"{fmt_money(r['median_list_price'])} | {fmt_money(r['median_sale_price'])} | "
                f"{fmt_ratio(r['avg_sale_to_list'])} | {fmt_int(r['median_dom'])} | "
                f"{fmt_int(r['homes_sold'])} |")
        lines.append("")
    if missing:
        lines += [f"**Not found in Redfin data:** {', '.join(missing)}", ""]
    lines += ["## Diagnostics", "",
              f"- Newest period anywhere in Redfin's file: {DEBUG['latest_period_in_file'] or 'unknown'}",
              "- GA regions with 'Oconee' or 'Clarke' in the name: "
              + (", ".join(sorted(DEBUG["ga_regions_named_like_missing"])) or "none"),
              ""]
    summary = "\n".join(lines)
    (OUT_DIR / "summary.md").write_text(summary)
    print(summary)
    return missing


def main():
    print(f"Downloading {SOURCE_URL}")
    req = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "amplifier-market-data"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        best, durations = latest_by_county(read_rows(resp))
    if not best:
        sys.exit("No matching rows found. Redfin may have changed the file format.")
    missing = write_outputs(best, durations)
    if missing:
        print(f"WARNING: missing counties: {missing}")


if __name__ == "__main__":
    main()
