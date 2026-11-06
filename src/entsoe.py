"""Thin client for the ENTSO-E Transparency Platform (web-api.tp.entsoe.eu).

Everything the project needs from ENTSO-E goes through this module:

* ``A44`` day-ahead prices, one bidding zone per call
* ``A65`` load, ``A75`` generation (both are ``GL_MarketDocument``)
* ``A11`` net cross-border physical flows
* ``A78`` unavailability (outages) of the transmission grid

Two details drive the design:

1. **The API answers XML, not JSON.** The documents are namespaced, so every
   element is looked up by its local name (the part after ``}``).
2. **ENTSO-E omits repeated values.** With ``curveType A03`` a position is
   written only when its value differs from the previous one; the missing
   positions repeat the last written value. Ignoring this shifts every
   timestamp and biases every average. :func:`expand_series` implements the
   forward-fill.

The API token is read from the ``ENTSOE_TOKEN`` environment variable (or from a
``.env`` file). It is never written to disk, never logged and never printed.
"""

from __future__ import annotations

import csv
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

API_URL = "https://web-api.tp.entsoe.eu/api"

#: Italian bidding zones and sub-zones -> EIC code used by ENTSO-E.
ZONES: dict[str, str] = {
    "IT Nord": "10Y1001A1001A73I",
    "IT Centro-Nord": "10Y1001A1001A70O",
    "IT Centro-Sud": "10Y1001A1001A71M",
    "IT Sud": "10Y1001A1001A788",
    "IT Sicilia": "10Y1001A1001A75E",
    "IT Sardegna": "10Y1001A1001A74G",
    "IT Calabria": "10Y1001C--00096J",
}

#: Reverse lookup, EIC -> readable name.
ZONE_NAMES: dict[str, str] = {eic: name for name, eic in ZONES.items()}

#: Neighbouring bidding zones used as a control group in the analysis.
OTHER_MARKETS: dict[str, str] = {
    "10YGR-HTSO-----Y": "Greece",
    "10YFR-RTE------C": "France",
    "10YAT-APG------L": "Austria",
    "10YSI-ELES-----O": "Slovenia",
    "10YCH-SWISSGRIDZ": "Switzerland",
    "10YCS-CG-TSO---S": "Montenegro",
}

ZONE_NAMES.update(OTHER_MARKETS)

#: Generation technologies grouped into the five buckets used in the analysis.
PSR_TO_SOURCE: dict[str, str] = {
    "B16": "solar",
    "B18": "wind",
    "B19": "wind",
    "B10": "hydro",
    "B11": "hydro",
    "B12": "hydro",
    "B04": "gas",
}

SOURCES = ["solar", "wind", "hydro", "gas", "other"]


# --------------------------------------------------------------------------- #
# token
# --------------------------------------------------------------------------- #

def read_token(env_file: str | None = None) -> str:
    """Return the ENTSO-E API token.

    Order of precedence: environment variable, then ``.env`` file, then the
    path given in ``env_file``. The value is never printed.
    """
    token = os.environ.get("ENTSOE_TOKEN", "").strip()
    if token:
        return token

    candidates = [env_file] if env_file else []
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))
    for path in candidates:
        if path and os.path.exists(path):
            with open(path, encoding="utf-8-sig") as handle:
                for line in handle:
                    line = line.strip()
                    if line.startswith("export "):
                        line = line[len("export "):].strip()
                    if line.startswith("#") or "=" not in line:
                        continue
                    name, value = line.split("=", 1)
                    if name.strip() == "ENTSOE_TOKEN":
                        return value.strip().strip('"').strip("'")
    raise SystemExit(
        "ENTSO-E token not found. Set the ENTSO_E_TOKEN environment variable "
        "or put ENTSOE_TOKEN=<uuid> in a .env file next to src/."
    )


# --------------------------------------------------------------------------- #
# XML helpers
# --------------------------------------------------------------------------- #

def local_name(tag: str) -> str:
    """Strip the XML namespace: ``{urn:...}Point`` -> ``Point``."""
    return tag.split("}")[-1]


def children(element, name: str) -> list:
    return [child for child in list(element) if local_name(child.tag) == name]


def descendants(root, name: str) -> list:
    return [element for element in root.iter() if local_name(element.tag) == name]


def text_of(element, name: str) -> str | None:
    found = children(element, name)
    return found[0].text if found else None


def parse_instant(text: str) -> datetime:
    """``2026-10-16T08:00Z`` -> timezone-aware UTC datetime."""
    text = text.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def resolution_minutes(resolution: str | None) -> int | None:
    """``PT15M`` -> 15, ``PT60M`` -> 60, ``PT1H`` -> 60, ``P1D`` -> 1440."""
    if not resolution:
        return None
    if resolution.startswith("PT"):
        rest = resolution[2:]
        if rest.endswith("M"):
            return int(rest[:-1])
        if rest.endswith("H"):
            return int(rest[:-1]) * 60
    if resolution.startswith("P") and resolution.endswith("D"):
        return int(resolution[1:-1]) * 1440
    return None


def expand_series(periods: list[dict]) -> dict[datetime, float]:
    """Turn the sparse ``(position, value)`` points of a period into a dense series.

    ``curveType A03`` means "write the value only when it changes"; every
    omitted position repeats the previous one.
    """
    result: dict[datetime, float] = {}
    for period in periods:
        step = timedelta(minutes=period["minutes"])
        instant = period["start"]
        index = 1
        last: float | None = None
        while instant < period["end"]:
            if index in period["values"]:
                last = period["values"][index]
                result[instant] = last
            elif period["sparse"] and last is not None:
                result[instant] = last
            instant += step
            index += 1
    return result


def read_periods(root, value_tag: str) -> list[dict]:
    """Collect every ``<Period>`` of a document into a normalised structure."""
    periods: list[dict] = []
    for series in descendants(root, "TimeSeries"):
        sparse = (text_of(series, "curveType") or "").strip().upper() == "A03"
        for period in children(series, "Period"):
            interval = children(period, "timeInterval")
            if not interval:
                continue
            minutes = resolution_minutes(text_of(period, "resolution") or "PT60M")
            if minutes is None:
                continue
            values: dict[int, float] = {}
            for point in children(period, "Point"):
                position = text_of(point, "position")
                value = text_of(point, value_tag)
                if position is None or value is None:
                    continue
                try:
                    values[int(position)] = float(value)
                except ValueError:
                    continue
            periods.append({
                "start": parse_instant(text_of(interval[0], "start")),
                "end": parse_instant(text_of(interval[0], "end")),
                "minutes": minutes,
                "values": values,
                "sparse": sparse,
            })
    return periods


# --------------------------------------------------------------------------- #
# download
# --------------------------------------------------------------------------- #

def download(token: str, params: dict, out_path: str) -> str:
    """Call the Transparency Platform and store the raw XML response."""
    query = dict(params)
    query["securityToken"] = token
    response = requests.get(API_URL, params=query, timeout=90)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(response.text)
    if response.status_code != 200 or "Acknowledgement_MarketDocument" in response.text[:2000]:
        reasons = descendants(ET.fromstring(response.text), "Reason")
        detail = "; ".join(
            (text_of(reason, "code") or "?") + " - " + (text_of(reason, "text") or "")
            for reason in reasons
        )
        raise RuntimeError(f"ENTSO-E rejected the request: {detail or response.text[:300]}")
    return out_path


def download_prices(token: str, raw_dir: str, start: datetime, end: datetime) -> list[str]:
    """Download the day-ahead price series (A44) of every Italian zone."""
    paths = []
    for name, eic in ZONES.items():
        path = os.path.join(raw_dir, f"A44_{name.replace(' ', '_')}.xml")
        download(token, {
            "documentType": "A44",
            "in_Domain": eic,
            "out_Domain": eic,
            "periodStart": start.strftime("%Y%m%d%H%M"),
            "periodEnd": end.strftime("%Y%m%d%H%M"),
        }, path)
        paths.append(path)
    return paths


# --------------------------------------------------------------------------- #
# parsers
# --------------------------------------------------------------------------- #

def parse_prices(path: str) -> dict[datetime, float]:
    """Day-ahead price series of one zone, keyed by UTC instant."""
    root = ET.parse(path).getroot()
    series = expand_series(read_periods(root, "price.amount"))
    return {instant.astimezone(timezone.utc): value for instant, value in series.items()}


def price_zone(path: str) -> str:
    """Readable name of the zone a price document refers to."""
    root = ET.parse(path).getroot()
    for series in descendants(root, "TimeSeries"):
        eic = (text_of(series, "out_Domain.mRID")
               or text_of(series, "in_Domain.mRID") or "").strip()
        if eic:
            return ZONE_NAMES.get(eic, eic)
    return os.path.basename(path)


def parse_prices_csv(path: str) -> dict[str, dict[datetime, float]]:
    """Day-ahead prices for every zone from the CSV produced by ``build_dataset``."""
    out: dict[str, dict[datetime, float]] = {}
    with open(path, encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            zone = row["zone"]
            instant = datetime.fromisoformat(row["timestamp_utc"].replace("Z", "+00:00"))
            out.setdefault(zone, {})[instant] = float(row["price_eur_mwh"])
    return out


def parse_load_or_generation(path: str) -> list[tuple[str, str, datetime, float]]:
    """``A65`` / ``A75`` -> list of ``(zone, source, instant, MW)``.

    Load files carry no technology, so their source is ``"load"``.
    """
    root = ET.parse(path).getroot()
    rows: list[tuple[str, str, datetime, float]] = []
    for series in descendants(root, "TimeSeries"):
        psr = descendants(series, "psrType")
        psr_code = (psr[0].text or "").strip() if psr else ""
        source = PSR_TO_SOURCE.get(psr_code, "other")
        eic = (text_of(series, "outBiddingZone_Domain.mRID")
               or text_of(series, "inBiddingZone_Domain.mRID") or "").strip()
        zone = ZONE_NAMES.get(eic, eic or "?")
        sparse = (text_of(series, "curveType") or "").strip().upper() == "A03"
        for period in children(series, "Period"):
            interval = children(period, "timeInterval")
            if not interval:
                continue
            minutes = resolution_minutes(text_of(period, "resolution") or "PT60M")
            if minutes is None:
                continue
            values: dict[int, float] = {}
            for point in children(period, "Point"):
                position = text_of(point, "position")
                value = text_of(point, "quantity")
                if position is None or value is None:
                    continue
                try:
                    values[int(position)] = float(value)
                except ValueError:
                    continue
            for instant, value in expand_series([{
                "start": parse_instant(text_of(interval[0], "start")),
                "end": parse_instant(text_of(interval[0], "end")),
                "minutes": minutes,
                "values": values,
                "sparse": sparse,
            }]).items():
                rows.append((zone, source, instant, value))
    return rows


def parse_flow(path: str) -> dict[datetime, float]:
    """``A11`` net physical flow of one border -> ``{instant: MW}``."""
    root = ET.parse(path).getroot()
    series = expand_series(read_periods(root, "quantity"))
    return {instant.astimezone(timezone.utc): value for instant, value in series.items()}


def parse_unavailability(path: str) -> list[dict]:
    """``A78`` outage records -> one dict per declared outage."""
    root = ET.parse(path).getroot()
    created = text_of(root, "createdDateTime")
    records = []
    for series in descendants(root, "TimeSeries"):
        in_domain = (text_of(series, "in_Domain.mRID") or "").strip()
        out_domain = (text_of(series, "out_Domain.mRID") or "").strip()
        unit = text_of(series, "quantity_Measure_Unit.name") or ""
        for period in children(series, "Available_Period"):
            interval = children(period, "timeInterval")
            start = parse_instant(text_of(interval[0], "start")) if interval else None
            end = parse_instant(text_of(interval[0], "end")) if interval else None
            capacity = None
            for point in children(period, "Point"):
                raw = text_of(point, "quantity")
                if raw is not None:
                    capacity = float(raw)
            records.append({
                "in_domain": ZONE_NAMES.get(in_domain, in_domain),
                "out_domain": ZONE_NAMES.get(out_domain, out_domain),
                "business_type": (text_of(series, "businessType") or "").strip(),
                "unit": unit,
                "available_capacity_mw": capacity,
                "start_utc": start,
                "end_utc": end,
                "document_created_utc": created,
            })
    return records
