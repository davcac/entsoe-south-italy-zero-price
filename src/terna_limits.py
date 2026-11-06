"""Transit limits between Italian bidding zones, published by Terna.

Terna (the Italian transmission system operator) computes, for every hour of
the delivery day, the maximum power that may flow between two bidding zones
while keeping the grid secure under the n-1 criterion. GME takes those numbers
as an input of the day-ahead auction: they are the reason why one zone can be
short while another one is long.

Three series are published on the public download centre
(https://dati.terna.it/download-center, section "Mercato e adeguatezza" ->
"Limiti di transito tra zone di mercato"):

``MGPTransitLimit``
    **final** limits, the ones in force when the day-ahead auction ran.
    This is the series the analysis compares against the physical flow.
``ForecastTransitLimit``
    forecasts published the day before (flat and usually higher).
``TransitMargins``
    residual margin (limit minus schedule) recomputed after each intraday
    session.

The endpoint is public: no registration, no API key.
"""

from __future__ import annotations

import csv
import io
import urllib.parse
import urllib.request
from datetime import datetime

import openpyxl

ENDPOINT = "https://dati.terna.it/api/sitecore/dati/downloadcenter/records"

#: dataset on the portal -> label used in the exported CSV.
SERIES = [
    ("final", "MGPTransitLimit", "final_transit_limit"),
    ("forecast", "ForecastTransitLimit", "forecast_transit_limit"),
    ("margin", "TransitMargins", "transit_margin"),
]

PAGE_SIZE = 10000


def download(dataset: str, zone_from: str, zone_to: str, year: int, month: int) -> bytes:
    """Download one table of the Terna download centre as ``.xlsx`` bytes.

    The zone names must be written in English and separated by " -> ", the way
    the portal expects them (e.g. ``"South"`` -> ``"Centre-South"``).
    """
    params = {
        "f": "xlsx",
        "filterDataset": dataset,
        "filterZoneFrom": zone_from,
        "filterZoneTo": zone_to,
        "filterYear": str(year),
        "filterMonth": str(month),
        "orderByColumn": "Date",
        "orderByDir": "desc",
        "pageSize": str(PAGE_SIZE),
        "db": "dati",
    }
    url = ENDPOINT + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


def _column_index(headers: list, prefix: str) -> int | None:
    for index, name in enumerate(headers):
        if name and str(name).strip().lower().startswith(prefix):
            return index
    return None


def parse_xlsx(content: bytes, label: str, zone_from: str, zone_to: str) -> list[tuple]:
    """Turn a Terna ``.xlsx`` table into ``(series, timestamp, from, to, MW)`` rows.

    The last row of every table is a service row that repeats the filters
    applied ("Applied filters: ..."); it is recognised by the fact that its
    first column is not a date.
    """
    workbook = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    rows = list(workbook.active.iter_rows(values_only=True))
    if not rows:
        return []
    headers = list(rows[0])
    data = [row for row in rows[1:] if hasattr(row[0], "hour")]

    col_date = _column_index(headers, "date")
    col_from = _column_index(headers, "zone from")
    col_to = _column_index(headers, "zone to")
    col_session = _column_index(headers, "session")
    col_value = None
    for prefix in ("forecast", "transit limit", "margin"):
        col_value = _column_index(headers, prefix)
        if col_value is not None:
            break
    if col_value is None:
        raise ValueError(f"unexpected columns in the Terna table: {headers}")

    parsed = []
    for row in data:
        value = row[col_value]
        if value is None:
            continue
        name = label
        if col_session is not None:
            name = f"{label}_{row[col_session]}"
        parsed.append((
            name,
            row[col_date],
            row[col_from] if col_from is not None else zone_from,
            row[col_to] if col_to is not None else zone_to,
            float(value),
        ))
    return parsed


def build_csv(path: str, borders: list[tuple[str, str, str]], year: int, month: int) -> int:
    """Download every border/series combination and store one long-format CSV.

    Returns the number of rows written.
    """
    rows: list[tuple] = []
    for title, zone_from, zone_to in borders:
        for key, dataset, label in SERIES:
            try:
                content = download(dataset, zone_from, zone_to, year, month)
            except Exception as error:                      # noqa: BLE001
                print(f"  {title} / {key}: not downloaded ({error})")
                continue
            parsed = parse_xlsx(content, label, zone_from, zone_to)
            rows.extend(parsed)
            print(f"  {title} / {key}: {len(parsed)} values")
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["series", "timestamp_local", "zone_from", "zone_to", "value_mw"])
        for series, when, zone_from, zone_to, value in sorted(rows, key=lambda r: (r[0], r[1])):
            writer.writerow([series, when.strftime("%Y-%m-%d %H:%M"), zone_from, zone_to, f"{value:.2f}"])
    return len(rows)
