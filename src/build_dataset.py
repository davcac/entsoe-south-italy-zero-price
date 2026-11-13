"""Build the compact, analysis-ready dataset from the raw ENTSO-E / Terna files.

Input (a ``raw/`` folder, not versioned because of its size):

======================================  =========================================
``A44_<ZONE>.xml``                      day-ahead prices, one file per zone
``A65_<ZONE>.xml`` / ``A75_<ZONE>.xml`` load / generation per zone
``A11_<FROM>_<TO>.xml``                 net physical flow on a border
``A78_*.xml``                           grid unavailability (outages)
``transit_limits.csv``                  Terna transit limits (long format)
======================================  =========================================

Output (a ``data/`` folder, versioned):

* ``day_ahead_prices.csv``   -- zone, timestamp_utc, timestamp_local, price_eur_mwh
* ``load_generation.csv``    -- zone, source, timestamp_utc, timestamp_local, mw
* ``cross_border_flows.csv`` -- border, timestamp_utc, timestamp_local, flow_mw
* ``cross_border_flows_directional.csv``
                                -- gross flow, one row per published direction
* ``grid_unavailability.csv`` -- outage records declared on the transmission grid
* ``transit_limits.csv``     -- Terna final/forecast transit limits per hour

Flow sign convention: every border is stored in one canonical direction and
the value is the **net** flow in that direction (positive = along the label).
ENTSO-E publishes one file per direction and each file only carries the value
while the flow actually runs that way, so the net flow is
``f(forward) - f(backward)``.

``cross_border_flows_directional.csv`` keeps the two sides apart: one row for
every direction ENTSO-E publishes, with the **gross** flow that really went
in that direction (zeros included). The net of the two directions of a border
is exactly the value stored in ``cross_border_flows.csv``, so the directional
file is the one to use when the export and the import have to be told apart.
"""

from __future__ import annotations

import argparse
import csv
import glob
import os
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import entsoe  # noqa: E402

ROME = timezone(timedelta(hours=2))          # Italy: CET in October
MACRO_SOUTH = ["IT Sud", "IT Calabria", "IT Sicilia"]

#: canonical direction of every border used in the analysis.
BORDERS = {
    "SUD_CSUD": "IT Sud -> IT Centro-Sud",
    "CALA_SUD": "IT Calabria -> IT Sud",
    "SICI_CALA": "IT Sicilia -> IT Calabria",
    "SUD_GR": "IT Sud -> Greece",
    "SICI_MT": "IT Sicilia -> Malta",
}

EIC_TO_NAME = dict(entsoe.ZONE_NAMES)
EIC_TO_NAME.update({
    "10YGR-HTSO-----Y": "Greece",
    "10Y1001A1001A93C": "Malta",
})


def local(timestamp: datetime) -> str:
    return timestamp.astimezone(ROME).strftime("%Y-%m-%d %H:%M")


#: Terna publishes the three series under these names; the dataset uses
#: stable English labels (the margins keep their session suffix).
SERIES_LABELS = {
    "limite_definitivo": "final_transit_limit",
    "limite_provvisorio": "forecast_transit_limit",
}


def canonical_series(name: str) -> str:
    if name in SERIES_LABELS:
        return SERIES_LABELS[name]
    if name.startswith("margine"):
        return "margin_" + name.split("_", 1)[1] if "_" in name else "margin"
    return name


def utc(timestamp: datetime) -> str:
    return timestamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pick(raw_dir: str, patterns: list[str]) -> list[str]:
    """Return the files matching the first pattern that yields something."""
    for pattern in patterns:
        found = sorted(glob.glob(os.path.join(raw_dir, pattern)))
        if found:
            return found
    return []


def latest_batch(paths: list[str]) -> list[str]:
    """Keep only the files of the most recent download batch.

    The batch is identified by the ``YYYY-MM-DD_HH-MM-SS`` stamp that the
    downloader appends to every file name.
    """
    stamps = set()
    for path in paths:
        found = re.search(r"_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})", os.path.basename(path))
        if found:
            stamps.add(found.group(1))
    if not stamps:
        return paths
    last = sorted(stamps)[-1]
    return [path for path in paths if last in os.path.basename(path)]


# --------------------------------------------------------------------------- #
# builders
# --------------------------------------------------------------------------- #

def build_prices(raw_dir: str, out_dir: str) -> int:
    rows = []
    italian = latest_batch(pick(raw_dir, ["A44_*.xml", "04_IT_*.xml", "04_IT*.xml"]))
    neighbours = latest_batch(pick(raw_dir, ["10_A44_*.xml"]))
    for path in italian + neighbours:
        zone = entsoe.price_zone(path)
        for instant, price in entsoe.parse_prices(path).items():
            rows.append([zone, utc(instant), local(instant), f"{price:.2f}"])
    if not rows:
        # fall back to the CSV produced by the first (exploratory) downloader
        legacy = pick(raw_dir, ["04_prezzi_*.csv"])
        if legacy:
            with open(legacy[-1], encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    rows.append([row["zona"], row["ora_utc"], row["ora_italiana"],
                                 f"{float(row['prezzo_eur_mwh']):.2f}"])
    rows.sort(key=lambda row: (row[0], row[1]))
    path = os.path.join(out_dir, "day_ahead_prices.csv")
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["zone", "timestamp_utc", "timestamp_local", "price_eur_mwh"])
        writer.writerows(rows)
    return len(rows)


def build_load_generation(raw_dir: str, out_dir: str) -> int:
    rows = []
    for pattern, kind in (("A75_*.xml", "generation"), ("10_A75_*.xml", "generation"),
                          ("A65_*.xml", "load"), ("10_A65_*.xml", "load")):
        for path in latest_batch(pick(raw_dir, [pattern])):
            for zone, source, instant, value in entsoe.parse_load_or_generation(path):
                if kind == "load":
                    source = "load"
                rows.append([zone, source, utc(instant), local(instant), f"{value:.1f}"])
    rows.sort(key=lambda row: (row[0], row[1], row[2]))
    path = os.path.join(out_dir, "load_generation.csv")
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["zone", "source", "timestamp_utc", "timestamp_local", "mw"])
        writer.writerows(rows)
    return len(rows)


def build_flows(raw_dir: str, out_dir: str) -> int:
    """Net flow per border, in the canonical direction of ``BORDERS``.

    ENTSO-E publishes one document per direction and each document only
    carries a value while the flow actually runs that way, so the net flow in
    the canonical direction is ``f(forward) - f(backward)``.
    """
    files = latest_batch(pick(raw_dir, ["A11_*.xml", "12_A11_*.xml"]))
    directions: dict[tuple[str, str], dict] = {}
    for path in files:
        root = entsoe.ET.parse(path).getroot()
        origin = destination = ""
        for node in entsoe.descendants(root, "TimeSeries"):
            origin = (entsoe.text_of(node, "out_Domain.mRID") or "").strip()
            destination = (entsoe.text_of(node, "in_Domain.mRID") or "").strip()
            break
        if not origin or not destination:
            continue
        key = (EIC_TO_NAME.get(origin, origin), EIC_TO_NAME.get(destination, destination))
        directions[key] = entsoe.parse_flow(path)

    rows = []
    for label in BORDERS.values():
        zone_from, zone_to = [part.strip() for part in label.split("->")]
        forward = directions.get((zone_from, zone_to), {})
        backward = directions.get((zone_to, zone_from), {})
        for instant in sorted(set(forward) | set(backward)):
            net = forward.get(instant, 0.0) - backward.get(instant, 0.0)
            rows.append([label, utc(instant), local(instant), f"{net:.1f}"])
    rows.sort(key=lambda row: (row[0], row[1]))
    path = os.path.join(out_dir, "cross_border_flows.csv")
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["border", "timestamp_utc", "timestamp_local", "flow_mw"])
        writer.writerows(rows)
    return len(rows)


def build_directional_flows(raw_dir: str, out_dir: str) -> int:
    """Gross flow for every direction ENTSO-E publishes, per border.

    ENTSO-E publishes one document per direction and writes a value only
    while the flow actually runs that way (zeros elsewhere), so each row
    here is the physical flow that really went in that direction.
    ``cross_border_flows.csv`` is the net of the two directions of a border.
    """
    files = latest_batch(pick(raw_dir, ["A11_*.xml", "12_A11_*.xml"]))
    rows = []
    for path in files:
        root = entsoe.ET.parse(path).getroot()
        origin = destination = ""
        for node in entsoe.descendants(root, "TimeSeries"):
            origin = (entsoe.text_of(node, "out_Domain.mRID") or "").strip()
            destination = (entsoe.text_of(node, "in_Domain.mRID") or "").strip()
            break
        if not origin or not destination:
            continue
        label = (f"{EIC_TO_NAME.get(origin, origin)}"
                 f" -> {EIC_TO_NAME.get(destination, destination)}")
        for instant, value in entsoe.parse_flow(path).items():
            rows.append([label, utc(instant), local(instant), f"{value:.1f}"])
    rows.sort(key=lambda row: (row[0], row[1]))
    path = os.path.join(out_dir, "cross_border_flows_directional.csv")
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["border", "timestamp_utc", "timestamp_local", "flow_mw"])
        writer.writerows(rows)
    return len(rows)


def build_unavailability(raw_dir: str, out_dir: str) -> int:
    rows = []
    for path in pick(raw_dir, ["A78_*.xml", "12_A78_*.xml"]):
        for record in entsoe.parse_unavailability(path):
            rows.append([
                record["in_domain"],
                record["out_domain"],
                record["business_type"],
                record["unit"],
                "" if record["available_capacity_mw"] is None else f"{record['available_capacity_mw']:.0f}",
                utc(record["start_utc"]) if record["start_utc"] else "",
                utc(record["end_utc"]) if record["end_utc"] else "",
                record["document_created_utc"] or "",
            ])
    path = os.path.join(out_dir, "grid_unavailability.csv")
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["domain_in", "domain_out", "business_type", "unit",
                         "available_capacity_mw", "start_utc", "end_utc",
                         "document_created_utc"])
        writer.writerows(rows)
    return len(rows)


def build_transit_limits(raw_dir: str, out_dir: str) -> int:
    source = pick(raw_dir, ["transit_limits.csv", "16_limiti_transito_*.csv"])
    if not source:
        return 0
    rows = []
    with open(source[-1], encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if "serie" in row:
                # legacy layout of the exploratory script 16
                when = datetime.strptime(row["data_ora"], "%Y-%m-%d %H:%M")
                rows.append([canonical_series(row["serie"]),
                             when.strftime("%Y-%m-%d %H:%M"),
                             row["zona_da"], row["zona_a"], row["valore_MW"]])
            else:
                # layout written by src/terna_limits.py
                rows.append([canonical_series(row["series"]), row["timestamp_local"],
                             row["zone_from"], row["zone_to"], row["value_mw"]])
    rows.sort(key=lambda row: (row[0], row[1]))
    path = os.path.join(out_dir, "transit_limits.csv")
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["series", "timestamp_local", "zone_from", "zone_to", "value_mw"])
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="build the analysis dataset")
    parser.add_argument("--raw", default="raw", help="folder with the raw downloads")
    parser.add_argument("--out", default="data", help="folder for the CSV dataset")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    print(f"raw folder : {args.raw}")
    print(f"out folder : {args.out}")
    for name, builder in (
        ("day_ahead_prices.csv", build_prices),
        ("load_generation.csv", build_load_generation),
        ("cross_border_flows.csv", build_flows),
        ("cross_border_flows_directional.csv", build_directional_flows),
        ("grid_unavailability.csv", build_unavailability),
        ("transit_limits.csv", build_transit_limits),
    ):
        count = builder(args.raw, args.out)
        print(f"  {name:28s} {count:6d} rows")


if __name__ == "__main__":
    main()
