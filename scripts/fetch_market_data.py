"""
Amplifier market data.

Pulls Realtor.com's monthly county inventory data, keeps our 9 North Georgia
counties (matched by FIPS code, the permanent government ID for each county),
and saves:
  data/market-snapshot.json  -> what the website will read
  data/summary.md            -> a readable table for checking the numbers

Attribution required by Realtor.com: "Realtor.com® Economic Research" with a
link to https://www.realtor.com/research/data/
"""
import csv
import io
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SOURCE_URL = (
    "https://econdata.s3-us-west-2.amazonaws.com/Reports/Core/"
    "RDC_Inventory_Core_Metrics_County.csv"
)
ZIP_SOURCE_URL = (
    "https://econdata.s3-us-west-2.amazonaws.com/Reports/Core/"
    "RDC_Inventory_Core_Metrics_Zip.csv"
)
ATTRIBUTION = "Realtor.com® Economic Research"
ATTRIBUTION_LINK = "https://www.realtor.com/research/data/"

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data"
# If the download ever fails, upload the CSV here by hand and re-run.
MANUAL_FILE = ROOT / "data" / "source" / "RDC_Inventory_Core_Metrics_County.csv"
MANUAL_ZIP_FILE = ROOT / "data" / "source" / "RDC_Inventory_Core_Metrics_Zip.csv"

# City page -> the ZIP codes that represent it (in display order)
CITY_ZIPS = {
    "Winder": ["30680"],
    "Bethlehem": ["30620"],
    "Statham": ["30666"],
    "Auburn": ["30011"],
    "Braselton": ["30517"],
    "Jefferson": ["30549"],
    "Hoschton": ["30548"],
    "Monroe": ["30655", "30656"],
    "Watkinsville": ["30677"],
    "Athens": ["30601", "30605", "30606", "30607"],
}

# FIPS code -> county name
COUNTIES = {
    "13013": "Barrow",
    "13157": "Jackson",
    "13135": "Gwinnett",
    "13139": "Hall",
    "13219": "Oconee",
    "13059": "Clarke",
    "13297": "Walton",
    "13211": "Morgan",
    "13117": "Forsyth",
}


def num(value):
    value = (value or "").strip()
    if value in ("", "NA", "nan", "None"):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def load_csv_text(url=SOURCE_URL, manual=MANUAL_FILE, required=True):
    try:
        print(f"Downloading {url}")
        req = urllib.request.Request(url, headers={"User-Agent": "amplifier-market-data"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            return resp.read().decode("utf-8-sig"), "download"
    except Exception as err:  # noqa: BLE001
        print(f"Download failed: {err}")
        if manual.exists():
            print(f"Using manually uploaded file: {manual}")
            return manual.read_text(encoding="utf-8-sig"), "manual upload"
        if not required:
            return None, "unavailable"
        sys.exit(
            "Could not download Realtor.com data and no manual file was found. "
            f"Upload the CSV to {manual.relative_to(ROOT)} and run again."
        )


def latest_by_county(text):
    best = {}
    for row in csv.DictReader(io.StringIO(text)):
        fips = (row.get("county_fips") or "").strip().split(".")[0].zfill(5)
        if fips not in COUNTIES:
            continue
        month = (row.get("month_date_yyyymm") or "").strip()
        if fips in best and month <= best[fips]["month_raw"]:
            continue
        best[fips] = {
            "month_raw": month,
            "county": COUNTIES[fips],
            "fips": fips,
            "median_list_price": num(row.get("median_listing_price")),
            "median_list_price_yoy": num(row.get("median_listing_price_yy")),
            "median_days_on_market": num(row.get("median_days_on_market")),
            "median_days_on_market_yoy": num(row.get("median_days_on_market_yy")),
            "active_listings": num(row.get("active_listing_count")),
            "active_listings_yoy": num(row.get("active_listing_count_yy")),
            "price_reduced_share": num(row.get("price_reduced_share")),
            "price_reduced_share_yoy": num(row.get("price_reduced_share_yy")),
            "quality_flag": (row.get("quality_flag") or "").strip(),
        }
    return best


def month_label(raw):
    try:
        return datetime.strptime(raw, "%Y%m").strftime("%B %Y")
    except ValueError:
        return raw


def money(v):
    return "—" if v is None else f"${v:,.0f}"


def whole(v):
    return "—" if v is None else f"{v:,.0f}"


def pct(v):
    return "—" if v is None else f"{v * 100:.0f}%"


def stats_from_row(row):
    return {
        "median_list_price": num(row.get("median_listing_price")),
        "median_list_price_yoy": num(row.get("median_listing_price_yy")),
        "median_days_on_market": num(row.get("median_days_on_market")),
        "median_days_on_market_yoy": num(row.get("median_days_on_market_yy")),
        "active_listings": num(row.get("active_listing_count")),
        "active_listings_yoy": num(row.get("active_listing_count_yy")),
        "price_reduced_share": num(row.get("price_reduced_share")),
        "price_reduced_share_yoy": num(row.get("price_reduced_share_yy")),
        "quality_flag": (row.get("quality_flag") or "").strip(),
    }


def build_city_snapshot():
    """Per-ZIP stats for each city page. Never breaks the county update:
    if the ZIP file can't be loaded, the existing city file is left alone."""
    text, how = load_csv_text(ZIP_SOURCE_URL, MANUAL_ZIP_FILE, required=False)
    if text is None:
        print("WARNING: ZIP data unavailable; keeping the previous city snapshot.")
        return None
    wanted = {z for zips in CITY_ZIPS.values() for z in zips}
    best = {}
    for row in csv.DictReader(io.StringIO(text)):
        z = (row.get("postal_code") or "").strip().split(".")[0].zfill(5)
        if z not in wanted:
            continue
        month = (row.get("month_date_yyyymm") or "").strip()
        if z in best and month <= best[z]["month"]:
            continue
        best[z] = {"zip": z, "month": month, **stats_from_row(row)}
    if not best:
        print("WARNING: none of our ZIPs were found; keeping the previous city snapshot.")
        return None
    newest = max(r["month"] for r in best.values())
    snapshot = {
        "attribution": ATTRIBUTION,
        "attribution_link": ATTRIBUTION_LINK,
        "month": newest,
        "month_label": month_label(newest),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fetched_via": how,
        "cities": {
            city: [best[z] for z in zips if z in best]
            for city, zips in CITY_ZIPS.items()
        },
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "city-snapshot.json").write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))

    lines = [
        "## Cities by ZIP",
        "",
        f"**{month_label(newest)}** · fetched via {how}",
        "",
        "| City | ZIP | Median list price | Days on market | Active listings | % with a price cut |",
        "|---|---|---|---|---|---|",
    ]
    for city, zips in CITY_ZIPS.items():
        for z in zips:
            r = best.get(z)
            if not r:
                lines.append(f"| {city} | {z} | missing | | | |")
                continue
            flag = " ⚠️" if r["quality_flag"] not in ("", "0", "0.0") else ""
            lines.append(
                f"| {city} | {z}{flag} | {money(r['median_list_price'])} | {whole(r['median_days_on_market'])} | "
                f"{whole(r['active_listings'])} | {pct(r['price_reduced_share'])} |"
            )
    lines.append("")
    return "\n".join(lines)


def main():
    text, how = load_csv_text()
    best = latest_by_county(text)
    if not best:
        sys.exit("None of our counties were found. The file format may have changed.")

    ordered = [best[f] for f in COUNTIES if f in best]
    missing = [name for f, name in COUNTIES.items() if f not in best]
    months = sorted({r["month_raw"] for r in ordered})
    newest = months[-1]

    snapshot = {
        "attribution": ATTRIBUTION,
        "attribution_link": ATTRIBUTION_LINK,
        "month": newest,
        "month_label": month_label(newest),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fetched_via": how,
        "counties": {
            r["county"]: {k: v for k, v in r.items() if k not in ("county", "month_raw")}
            | {"month": r["month_raw"]}
            for r in ordered
        },
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "market-snapshot.json").write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))

    lines = [
        "# Amplifier market snapshot",
        "",
        f"**{month_label(newest)}** · Source: [{ATTRIBUTION}]({ATTRIBUTION_LINK}) · fetched via {how} · generated {snapshot['generated_at']}",
        "",
        "| County | Median list price | Days on market | Active listings | % with a price cut | Data month |",
        "|---|---|---|---|---|---|",
    ]
    for r in ordered:
        flag = " ⚠️" if r["quality_flag"] not in ("", "0", "0.0") else ""
        lines.append(
            f"| {r['county']}{flag} | {money(r['median_list_price'])} | {whole(r['median_days_on_market'])} | "
            f"{whole(r['active_listings'])} | {pct(r['price_reduced_share'])} | {month_label(r['month_raw'])} |"
        )
    lines.append("")
    if missing:
        lines += [f"**Missing counties:** {', '.join(missing)}", ""]
    if len(months) > 1:
        lines += [f"**Heads up:** counties came from different months: {', '.join(month_label(m) for m in months)}", ""]
    lines += ["⚠️ = Realtor.com flagged this county's data for a quality issue that month.", ""]
    city_summary = build_city_snapshot()
    if city_summary:
        lines += ["", city_summary]
    summary = "\n".join(lines)
    (OUT_DIR / "summary.md").write_text(summary)
    print(summary)


if __name__ == "__main__":
    main()
