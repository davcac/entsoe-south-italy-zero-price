"""Download the raw data needed by the analysis.

    python src/download.py --out raw --start 2026-10-16 --end 2026-10-19

The ENTSO-E token is read from the ``ENTSOE_TOKEN`` environment variable (or from
a ``.env`` file next to ``src/``); the Terna limits need no credentials.

Everything is stored as raw XML/CSV in the ``raw/`` folder; ``build_dataset.py``
turns that folder into the versioned dataset in ``data/``.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import entsoe      # noqa: E402
import terna_limits  # noqa: E402

ROME = timezone(timedelta(hours=2))

#: (label, from-zone, to-zone) for every border the analysis needs, in both
#: directions.
BORDERS = [
    ("SUD_CSUD", "10Y1001A1001A788", "10Y1001A1001A71M"),
    ("CALA_SUD", "10Y1001C--00096J", "10Y1001A1001A788"),
    ("SICI_CALA", "10Y1001A1001A75E", "10Y1001C--00096J"),
    ("SUD_GR", "10Y1001A1001A788", "10YGR-HTSO-----Y"),
    ("SICI_MT", "10Y1001A1001A75E", "10Y1001A1001A93C"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="download the raw ENTSO-E and Terna data")
    parser.add_argument("--out", default="raw", help="folder for the raw downloads")
    parser.add_argument("--start", default="2026-10-16", help="first delivery day (local)")
    parser.add_argument("--end", default="2026-10-19", help="day after the last one (local)")
    args = parser.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=ROME)
    end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=ROME)
    os.makedirs(args.out, exist_ok=True)

    token = entsoe.read_token()
    print(f"token: {len(token)} characters (not shown)")
    print(f"window: {start:%Y-%m-%d %H:%M} -> {end:%Y-%m-%d %H:%M} (Italian local time)")

    print("\n1) day-ahead prices (A44)")
    for name, eic in list(entsoe.ZONES.items()) + list(entsoe.OTHER_MARKETS.items()):
        path = os.path.join(args.out, f"A44_{name.replace(' ', '_')}.xml")
        entsoe.download(token, {
            "documentType": "A44",
            "in_Domain": eic,
            "out_Domain": eic,
            "periodStart": start.astimezone(timezone.utc).strftime("%Y%m%d%H%M"),
            "periodEnd": end.astimezone(timezone.utc).strftime("%Y%m%d%H%M"),
        }, path)
        print(f"   {name:14s} -> {os.path.basename(path)}")

    print("\n2) load (A65) and generation (A75)")
    for document, tag in (("A65", "A65"), ("A75", "A75")):
        for name, eic in entsoe.ZONES.items():
            path = os.path.join(args.out, f"{tag}_{name.replace(' ', '_')}.xml")
            entsoe.download(token, {
                "documentType": document,
                "in_Domain": eic,
                "out_Domain": eic,
                "processType": "A16",
                "periodStart": start.astimezone(timezone.utc).strftime("%Y%m%d%H%M"),
                "periodEnd": end.astimezone(timezone.utc).strftime("%Y%m%d%H%M"),
            }, path)
            print(f"   {tag} {name:14s} -> {os.path.basename(path)}")

    print("\n3) cross-border physical flows (A11)")
    for label, source, target in BORDERS:
        for from_eic, to_eic, tag in ((source, target, label),
                                      (target, source, f"{label}_rev")):
            path = os.path.join(args.out, f"A11_{tag}.xml")
            try:
                entsoe.download(token, {
                    "documentType": "A11",
                    "out_Domain": from_eic,
                    "in_Domain": to_eic,
                    "periodStart": start.astimezone(timezone.utc).strftime("%Y%m%d%H%M"),
                    "periodEnd": end.astimezone(timezone.utc).strftime("%Y%m%d%H%M"),
                }, path)
                print(f"   {tag:16s} -> {os.path.basename(path)}")
            except Exception as error:                       # noqa: BLE001
                print(f"   {tag:16s} not available ({error})")

    print("\n4) grid unavailability (A78)")
    for name in ("IT Sud", "IT Calabria"):
        path = os.path.join(args.out, f"A78_{name.replace(' ', '_')}.xml")
        try:
            entsoe.download(token, {
                "documentType": "A78",
                "in_Domain": entsoe.ZONES[name],
                "periodStart": start.astimezone(timezone.utc).strftime("%Y%m%d%H%M"),
                "periodEnd": end.astimezone(timezone.utc).strftime("%Y%m%d%H%M"),
            }, path)
            print(f"   {name:14s} -> {os.path.basename(path)}")
        except Exception as error:                           # noqa: BLE001
            print(f"   {name:14s} not available ({error})")

    print("\n5) transit limits (Terna, public)")
    csv_path = os.path.join(args.out, "transit_limits.csv")
    rows = terna_limits.build_csv(
        csv_path,
        [
            # The corridor the analysis focuses on: every series, margins included.
            ("Sud -> Centro-Sud", "South", "Centre-South"),
            # The other interfaces of the macro-zone: the final limit is enough.
            # "Greece 2" is the physical interconnection (500 MW); "Greece" is the
            # commercial coupling point, whose limit is never binding.
            ("Sud -> Greece", "South", "Greece 2", ["final"]),
            ("Sicily -> Malta", "Sicily", "Malta", ["final"]),
            ("South -> Calabria", "South", "Calabria", ["final"]),
            ("Sicily -> Calabria", "Sicily", "Calabria", ["final"]),
        ],
        year=start.year,
        month=start.month,
    )
    print(f"   {rows} values -> {os.path.basename(csv_path)}")

    print(f"\nDone. Now run: python src/build_dataset.py --raw {args.out} --out data")


if __name__ == "__main__":
    main()
