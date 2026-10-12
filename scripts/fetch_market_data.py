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
COUNTY_HISTORY_URL = (
    "https://econdata.s3-us-west-2.amazonaws.com/Reports/Core/"
    "RDC_Inventory_Core_Metrics_County_History.csv"
)
ZIP_HISTORY_URL = (
    "https://econdata.s3-us-west-2.amazonaws.com/Reports/Core/"
    "RDC_Inventory_Core_Metrics_Zip_History.csv"
)
HISTORY_YEARS = 5  # yearly points: this year plus the previous 5
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
            "pending_ratio": num(row.get("pending_ratio")),
            "pending_ratio_yoy": num(row.get("pending_ratio_yy")),
            "pending_listings": num(row.get("pending_listing_count")),
            "new_listings": num(row.get("new_listing_count")),
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


def ratio(v):
    return "—" if v is None else f"{v:.2f}"


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
        "pending_ratio": num(row.get("pending_ratio")),
        "pending_ratio_yoy": num(row.get("pending_ratio_yy")),
        "pending_listings": num(row.get("pending_listing_count")),
        "new_listings": num(row.get("new_listing_count")),
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


def stream_rows(url):
    """Stream a big CSV line by line (history files are 100MB+)."""
    print(f"Streaming {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "amplifier-market-data"})
    resp = urllib.request.urlopen(req, timeout=600)
    text = io.TextIOWrapper(resp, encoding="utf-8-sig", newline="")
    yield from csv.DictReader(text)


def collect_history(url, key_field, wanted, local_file=None):
    """Return {key: {yyyymm: {price, pending_ratio, dom, price_cut_share, flagged}}}."""
    out = {}
    try:
        if local_file is not None and local_file.exists():
            rows = csv.DictReader(open(local_file, encoding="utf-8-sig", newline=""))
        else:
            rows = stream_rows(url)
        for row in rows:
            key = (row.get(key_field) or "").strip().split(".")[0].zfill(5)
            if key not in wanted:
                continue
            month = (row.get("month_date_yyyymm") or "").strip()
            if not month.isdigit():
                continue
            flag = (row.get("quality_flag") or "").strip()
            flagged = flag not in ("", "0", "0.0")
            out.setdefault(key, {})[month] = {
                "price": num(row.get("median_listing_price")),
                "pending_ratio": num(row.get("pending_ratio")),
                "dom": num(row.get("median_days_on_market")),
                "price_cut_share": num(row.get("price_reduced_share")),
                "active": num(row.get("active_listing_count")),
                "flagged": flagged,
            }
    except Exception as err:  # noqa: BLE001
        print(f"WARNING: history unavailable from {url}: {err}")
        return None
    return out


def yearly_points(series, anchor_month):
    """Same calendar month each year (removes seasonal swings), skipping flagged months."""
    year, mm = int(anchor_month[:4]), anchor_month[4:]
    points = []
    for y in range(year - HISTORY_YEARS, year + 1):
        point = series.get(f"{y}{mm}") or {"price": None, "flagged": True}
        value, flagged = point["price"], point["flagged"]
        if value is None or flagged:
            continue
        points.append({"year": y, "value": value})
    return points


def build_history(county_month):
    """Writes data/history.json. Never breaks the rest of the update."""
    counties = collect_history(
        COUNTY_HISTORY_URL, "county_fips", set(COUNTIES),
        ROOT / "data" / "source" / "RDC_Inventory_Core_Metrics_County_History.csv")
    if not counties:
        print("WARNING: no county history; keeping previous history file.")
        return
    zip_set = {z for zips in CITY_ZIPS.values() for z in zips}
    zips = collect_history(
        ZIP_HISTORY_URL, "postal_code", zip_set,
        ROOT / "data" / "source" / "RDC_Inventory_Core_Metrics_Zip_History.csv") or {}
    history = {
        "attribution": ATTRIBUTION,
        "attribution_link": ATTRIBUTION_LINK,
        "metric": "median_list_price",
        "anchor_month": county_month,
        "anchor_month_name": datetime.strptime(county_month, "%Y%m").strftime("%B"),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "counties": {COUNTIES[f]: yearly_points(s, county_month) for f, s in counties.items()},
        "zips": {z: yearly_points(s, county_month) for z, s in zips.items()},
    }
    (OUT_DIR / "history.json").write_text(json.dumps(history, indent=2, ensure_ascii=False))
    print(f"History saved: {len(history['counties'])} counties, {len(history['zips'])} ZIPs")
    build_signal_history(counties, zips)


def build_signal_history(counties, zips=None):
    """Monthly market-gauge signals per county (unflagged months only)."""
    signals = {}
    for fips, series in counties.items():
        rows = []
        for month in sorted(series):
            p = series[month]
            if p["flagged"]:
                continue
            rows.append({"month": month, "pending_ratio": p["pending_ratio"],
                         "dom": p["dom"], "price_cut_share": p["price_cut_share"]})
        signals[COUNTIES[fips]] = rows
    out = {
        "attribution": ATTRIBUTION,
        "attribution_link": ATTRIBUTION_LINK,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "counties": signals,
    }
    (OUT_DIR / "signal-history.json").write_text(json.dumps(out, ensure_ascii=False))
    print(f"Signal history saved: {sum(len(v) for v in signals.values())} county-months")
    build_gauge(signals, city_signal_rows(zips or {}))


def city_signal_rows(zips):
    """Blend each city's ZIPs month by month, weighted by active listings.
    Flagged or incomplete ZIP-months are left out of that month's blend."""
    cities = {}
    for city, zip_list in CITY_ZIPS.items():
        months = sorted({m for z in zip_list for m in zips.get(z, {})})
        rows = []
        for month in months:
            parts = []
            for z in zip_list:
                pt = zips.get(z, {}).get(month)
                if (not pt or pt["flagged"] or not pt.get("active")
                        or None in (pt["pending_ratio"], pt["dom"], pt["price_cut_share"])):
                    continue
                parts.append(pt)
            total = sum(pt["active"] for pt in parts)
            if not parts or total <= 0:
                continue
            w = lambda k: sum(pt[k] * pt["active"] for pt in parts) / total
            rows.append({"month": month, "pending_ratio": w("pending_ratio"), "dom": w("dom"),
                         "price_cut_share": w("price_cut_share"), "active": total,
                         "zips": [z for z in zip_list if zips.get(z, {}).get(month) in parts]})
        cities[city] = rows
    return cities


# ---- Buyer/seller market gauge -------------------------------------------
# Score 0-100 (0 = strong buyer's market, 100 = strong seller's market).
#   50% estimated months of supply (pending listings stand in for monthly
#       sales; 3 months or less = 100, 7.5 months or more = 0, ~5.25 = 50)
#   25% days on market vs. the same calendar month in past years
#   25% share of listings with a price cut vs. the same month in past years
MOS_FACTOR = 1.2
GAUGE_ZONES = [
    (20, "strong_buyer", "Strong Buyer's Market"),
    (40, "slight_buyer", "Slight Buyer's Market"),
    (60, "balanced", "Balanced Market"),
    (80, "slight_seller", "Slight Seller's Market"),
    (100, "strong_seller", "Strong Seller's Market"),
]


def _percentile(value, past, higher_is_seller):
    if not past:
        return 50.0
    below = sum(v < value for v in past) + 0.5 * sum(v == value for v in past)
    pct = 100.0 * below / len(past)
    return pct if higher_is_seller else 100.0 - pct


MIN_ACTIVE_LISTINGS = 40  # below this, a single month is too noisy to show


def score_rows(rows):
    good = [r for r in rows
            if None not in (r["pending_ratio"], r["dom"], r["price_cut_share"])
            and r["pending_ratio"] > 0]
    if len(good) < 13:
        return None
    cur = good[-1]
    if cur.get("active") is not None and cur["active"] < MIN_ACTIVE_LISTINGS:
        return None
    same_month = [r for r in good[:-1] if r["month"][4:] == cur["month"][4:]]
    mos = MOS_FACTOR / cur["pending_ratio"]
    supply_score = max(0.0, min(100.0, (7.5 - mos) / (7.5 - 3.0) * 100))
    dom_score = _percentile(cur["dom"], [r["dom"] for r in same_month], False)
    cut_score = _percentile(cur["price_cut_share"],
                            [r["price_cut_share"] for r in same_month], False)
    score = round(0.5 * supply_score + 0.25 * dom_score + 0.25 * cut_score)
    zone_key, zone_label = next((k, l) for top, k, l in GAUGE_ZONES if score <= top)
    out = {
        "score": score,
        "zone": zone_key,
        "zone_label": zone_label,
        "month_raw": cur["month"],
        "est_months_supply": round(mos, 1),
        "pending_ratio": round(cur["pending_ratio"], 4),
        "days_on_market": round(cur["dom"], 1),
        "price_cut_share": round(cur["price_cut_share"], 4),
        "parts": {"supply": round(supply_score), "days_on_market": round(dom_score),
                  "price_cuts": round(cut_score)},
    }
    if "zips" in cur:
        out["zips"] = cur["zips"]
        out["active_listings"] = round(cur["active"])
    return out


def build_gauge(signals, city_signals=None):
    out_counties = {c: g for c, rows in signals.items() if (g := score_rows(rows))}
    out_cities = {c: g for c, rows in (city_signals or {}).items() if (g := score_rows(rows))}
    out = {
        "attribution": ATTRIBUTION,
        "attribution_link": ATTRIBUTION_LINK,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": "Estimated from Realtor.com pending listings, days on market and price cuts.",
        "counties": out_counties,
        "cities": out_cities,
    }
    (OUT_DIR / "gauge.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print("Gauge saved: " + ", ".join(f"{c} {v['score']}" for c, v in {**out_counties, **out_cities}.items()))


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
        "| County | Median list price | Days on market | Active listings | % with a price cut | Pending ratio | Data month |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in ordered:
        flag = " ⚠️" if r["quality_flag"] not in ("", "0", "0.0") else ""
        lines.append(
            f"| {r['county']}{flag} | {money(r['median_list_price'])} | {whole(r['median_days_on_market'])} | "
            f"{whole(r['active_listings'])} | {pct(r['price_reduced_share'])} | {ratio(r['pending_ratio'])} | "
            f"{month_label(r['month_raw'])} |"
        )
    lines.append("")
    if missing:
        lines += [f"**Missing counties:** {', '.join(missing)}", ""]
    if len(months) > 1:
        lines += [f"**Heads up:** counties came from different months: {', '.join(month_label(m) for m in months)}", ""]
    lines += ["⚠️ = Realtor.com flagged this county's data for a quality issue that month.", ""]
    build_history(newest)
    city_summary = build_city_snapshot()
    if city_summary:
        lines += ["", city_summary]
    summary = "\n".join(lines)
    (OUT_DIR / "summary.md").write_text(summary)
    print(summary)


if __name__ == "__main__":
    main()
