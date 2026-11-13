"""Diagnostics behind the "why did the price go to zero in Southern Italy?" question.

Everything is computed from the CSV dataset in ``data/`` (see
``build_dataset.py``), so the numbers printed here can be reproduced without
any API key.

Run it with::

    python src/analysis.py
"""

from __future__ import annotations

import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")

ROME = "Europe/Rome"
MACRO_SOUTH = ["IT Sud", "IT Calabria", "IT Sicilia"]
ITALY = ["IT Nord", "IT Centro-Nord", "IT Centro-Sud", "IT Sud", "IT Sicilia",
         "IT Sardegna", "IT Calabria"]
NEIGHBOURS = ["Greece", "France", "Austria", "Slovenia", "Switzerland", "Montenegro"]
EVENT_DAY = "2026-10-16"
CONTROL_DAYS = ["2026-10-16", "2026-10-17", "2026-10-18"]
CORRIDOR = "IT Sud -> IT Centro-Sud"
#: The three interfaces through which the southern macro-zone can export, and
#: the pair of zones Terna uses to name them in its limit tables. "Greece 2" is
#: the physical interconnection with Greece (500 MW); "Greece" is the
#: commercial coupling point, whose limit (10 000 MW) never binds.
EXPORT_BORDERS = {
    CORRIDOR: ("South", "Centre-South"),
    "IT Sud -> Greece": ("South", "Greece 2"),
    "IT Sicilia -> Malta": ("Sicily", "Malta"),
}


# --------------------------------------------------------------------------- #
# dataset
# --------------------------------------------------------------------------- #

class Dataset:
    """The six CSV tables, indexed by time (Italian local time)."""

    def __init__(self, folder: str = DATA):
        self.prices = self._read(folder, "day_ahead_prices.csv", "zone", "price_eur_mwh")
        self.load_gen = self._read(folder, "load_generation.csv", ["zone", "source"], "mw", agg="sum")
        self.flows = self._read(folder, "cross_border_flows.csv", "border", "flow_mw")
        self.limits = self._read_local(folder, "transit_limits.csv",
                                      ["series", "zone_from", "zone_to"], "value_mw")
        self.outages = pd.read_csv(os.path.join(folder, "grid_unavailability.csv"))

    @staticmethod
    def _read(folder: str, name: str, by, value: str, agg: str = "last") -> pd.DataFrame:
        path = os.path.join(folder, name)
        frame = pd.read_csv(path, parse_dates=["timestamp_utc"])
        frame["t"] = frame["timestamp_utc"].dt.tz_convert(ROME)
        return frame.pivot_table(index="t", columns=by, values=value, aggfunc=agg)

    @staticmethod
    def _read_local(folder: str, name: str, by, value: str) -> pd.DataFrame:
        """Terna tables are published in Italian local time.

        Terna writes wall-clock time, so the hour that happens twice on the day
        the clocks go back (last Sunday of October) is ambiguous: it cannot be
        turned into an instant without knowing the offset. Those rows are
        dropped -- they are far outside the analysis window -- instead of being
        given a guess. The pivot keeps the border apart from the series, so the
        limit of one interface is never mixed with the limit of another.
        """
        path = os.path.join(folder, name)
        frame = pd.read_csv(path, parse_dates=["timestamp_local"])
        frame["t"] = frame["timestamp_local"].dt.tz_localize(
            ROME, ambiguous="NaT", nonexistent="shift_forward")
        frame = frame.dropna(subset=["t"])
        return frame.pivot_table(index="t", columns=by, values=value, aggfunc="last")

    # -- helpers ----------------------------------------------------------- #

    def price(self, zone: str) -> pd.Series:
        return self.prices[zone]

    def generation(self, zone: str, source: str) -> pd.Series:
        return self.load_gen[zone][source]

    def zone_surplus(self, zone: str) -> pd.Series:
        """Generation minus load of one zone (MW)."""
        sources = [c for c in self.load_gen[zone].columns if c != "load"]
        generation = self.load_gen[zone][sources].sum(axis=1)
        return generation - self.load_gen[zone]["load"]

    def macro_surplus(self) -> pd.Series:
        """Generation minus load of the whole southern macro-zone (MW)."""
        return sum(self.zone_surplus(zone) for zone in MACRO_SOUTH)

    def flow(self, border: str) -> pd.Series:
        return self.flows[border]

    def final_limit(self, border: str = CORRIDOR) -> pd.Series:
        """Terna final transit limit on one border (MW).

        The limit is an hourly value: it applies to every quarter-hour of the
        hour it is published for. Each border has its own series, so the limit
        of the corridor is never confused with the limit of another interface.
        """
        zone_from, zone_to = EXPORT_BORDERS[border]
        limits = self.limits["final_transit_limit"]
        column = (zone_from, zone_to)
        if column not in limits.columns:
            raise KeyError(f"no final transit limit published for {border} "
                           f"({zone_from} -> {zone_to})")
        return limits[column].groupby(pd.Grouper(freq="h")).max()


def window(frame: pd.Series, day: str, hour_from: int = 11, hour_to: int = 15) -> pd.Series:
    """Slice a series between two hours of a given local day."""
    start = pd.Timestamp(f"{day} {hour_from:02d}:00", tz=ROME)
    end = pd.Timestamp(f"{day} {hour_to:02d}:00", tz=ROME)
    return frame[(frame.index >= start) & (frame.index < end)]


# --------------------------------------------------------------------------- #
# diagnostics
# --------------------------------------------------------------------------- #

def zero_price_window(data: Dataset) -> pd.DataFrame:
    """Every quarter-hour in which the Sud zone was priced below 1 EUR/MWh."""
    prices = data.price("IT Sud")
    low = prices[prices < 1.0]
    # the transit limit is an hourly value: it applies to the whole hour
    limit = data.final_limit().reindex(low.index, method="ffill")
    return pd.DataFrame({
        "price": low,
        "macro_surplus_mw": data.macro_surplus().reindex(low.index),
        "corridor_flow_mw": data.flow(CORRIDOR).reindex(low.index),
        "corridor_limit_mw": limit.reindex(low.index),
    })


def bottleneck(data: Dataset) -> pd.DataFrame:
    """Final transit limit vs physical flow on the Sud -> Centro-Sud corridor.

    Terna publishes the limit for the whole hour, so the comparison is made
    between the hourly limit and the average physical flow of that hour; the
    peak quarter-hour of the same hour is reported as well.
    """
    limit = data.final_limit()
    flow = data.flow(CORRIDOR)
    hourly = pd.DataFrame({"limit_mw": limit}).dropna()
    hourly["flow_mw"] = flow.resample("h").mean()
    hourly["peak_flow_mw"] = flow.resample("h").max()
    hourly = hourly.dropna()
    hourly["utilisation"] = hourly["flow_mw"] / hourly["limit_mw"]
    hourly["peak_utilisation"] = hourly["peak_flow_mw"] / hourly["limit_mw"]
    return hourly


def daily_summary(data: Dataset) -> pd.DataFrame:
    """One row per day: surplus, corridor limit, corridor flow, price."""
    rows = []
    for day in CONTROL_DAYS:
        surplus = window(data.macro_surplus(), day)
        limit = window(data.final_limit(), day)
        flow = window(data.flow(CORRIDOR), day)
        rows.append({
            "day": day,
            "macro_surplus_mw": surplus.mean(),
            "corridor_limit_mw": limit.mean(),
            "corridor_flow_mw": flow.mean(),
            "utilisation": flow.mean() / limit.mean(),
            "sud_price_eur_mwh": window(data.price("IT Sud"), day).mean(),
            "italy_price_eur_mwh": window(data.price("IT Nord"), day).mean(),
        })
    return pd.DataFrame(rows).set_index("day")


def export_balance(data: Dataset) -> pd.DataFrame:
    """Southern surplus vs the power that actually left the macro-zone."""
    rows = []
    for day in CONTROL_DAYS:
        surplus = window(data.macro_surplus(), day).mean()
        exports = {
            border: window(data.flow(border), day).mean()
            for border in [CORRIDOR, "IT Sud -> Greece", "IT Sicilia -> Malta"]
        }
        total = sum(value for value in exports.values() if value == value)
        rows.append({"day": day, "macro_surplus_mw": surplus,
                     **exports, "total_exports_mw": total,
                     "not_exported_mw": surplus - total})
    return pd.DataFrame(rows).set_index("day")


def export_borders(data: Dataset, day: str = EVENT_DAY,
                   hour_from: int = 11, hour_to: int = 15) -> pd.DataFrame:
    """The three export interfaces of the macro-zone: Terna limit vs flow.

    The limit is an hourly value and the flow a quarterly one (hourly on the
    Greece border), so the average utilisation compares the average flow of the
    window with the average limit of the same window, while the peak
    utilisation compares the peak quarter-hour of an hour with the limit
    published for that hour.
    """
    rows = {}
    for border in EXPORT_BORDERS:
        limit = window(data.final_limit(border), day, hour_from, hour_to)
        flow = window(data.flow(border), day, hour_from, hour_to)
        hourly_limit = limit.resample("h").max()
        hourly_flow = flow.resample("h").mean()
        hourly_peak = flow.resample("h").max()
        rows[border] = {
            "limit_min_mw": hourly_limit.min(),
            "limit_max_mw": hourly_limit.max(),
            "limit_avg_mw": hourly_limit.mean(),
            "flow_avg_mw": hourly_flow.mean(),
            "flow_peak_mw": hourly_peak.max(),
            "flow_peak_at": hourly_peak.idxmax(),
            "utilisation_avg": hourly_flow.mean() / hourly_limit.mean(),
            "utilisation_max": (hourly_peak / hourly_limit).max(),
            "headroom_mw": hourly_limit.max() - hourly_peak.max(),
        }
    return pd.DataFrame(rows).T


def export_capacity(data: Dataset, day: str = EVENT_DAY,
                    hour_from: int = 11, hour_to: int = 15) -> pd.DataFrame:
    """How much the macro-zone could export, hour by hour, and what it could not.

    The capacity is the sum of the Terna limits of the three interfaces: what
    could not leave the macro-zone is the surplus minus that sum.
    """
    limits = pd.concat(
        {border: window(data.final_limit(border), day, hour_from, hour_to)
         for border in EXPORT_BORDERS}, axis=1)
    capacity = limits.sum(axis=1, min_count=len(EXPORT_BORDERS))
    surplus = window(data.macro_surplus(), day, hour_from, hour_to)
    frame = pd.DataFrame({"capacity_mw": capacity, "surplus_mw": surplus})
    frame["not_exported_mw"] = frame["surplus_mw"] - frame["capacity_mw"]
    return frame


def price_versus_surplus(data: Dataset) -> pd.DataFrame:
    """Average price of the Sud zone, grouped by local surplus."""
    frame = pd.DataFrame({
        "price": data.price("IT Sud"),
        "surplus": data.zone_surplus("IT Sud"),
    }).dropna()
    frame = frame[(frame.index >= pd.Timestamp("2026-10-15", tz=ROME))
                  & (frame.index < pd.Timestamp("2026-10-19", tz=ROME))]
    bins = [-float("inf"), 0, 1000, 2000, 3000, 4000, float("inf")]
    frame["bin"] = pd.cut(frame["surplus"], bins=bins)
    return frame.groupby("bin", observed=True).agg(
        quarters=("price", "size"),
        mean_price=("price", "mean"),
        min_price=("price", "min"),
    )


def generation_mix(data: Dataset) -> pd.DataFrame:
    """Midday generation mix and load of the southern macro-zone (MW)."""
    sources = [s for s in data.load_gen["IT Sud"].columns if s != "load"]
    rows = {}
    for day in CONTROL_DAYS:
        row = {}
        for source in sources:
            series = [data.generation(zone, source) for zone in MACRO_SOUTH
                      if source in data.load_gen[zone].columns]
            row[source] = sum(window(part, day).mean() for part in series)
        row["load"] = sum(window(data.load_gen[zone]["load"], day).mean()
                          for zone in MACRO_SOUTH)
        row["generation"] = sum(row[source] for source in sources)
        row["surplus"] = row["generation"] - row["load"]
        rows[day] = row
    return pd.DataFrame(rows).T


def quarter_hour_table(data: Dataset, day: str = EVENT_DAY,
                       hour_from: int = 9, hour_to: int = 16) -> pd.DataFrame:
    """The event hour by hour: price, surplus, corridor flow and limit."""
    limit = data.final_limit()
    frame = pd.DataFrame({
        "price": data.price("IT Sud"),
        "surplus": data.macro_surplus(),
        "flow": data.flow(CORRIDOR),
    })
    start = pd.Timestamp(f"{day} {hour_from:02d}:00", tz=ROME)
    end = pd.Timestamp(f"{day} {hour_to:02d}:00", tz=ROME)
    frame = frame[(frame.index >= start) & (frame.index < end)]
    frame["limit"] = limit.reindex(frame.index, method="ffill")
    frame["utilisation"] = frame["flow"] / frame["limit"]
    return frame


def neighbour_table(data: Dataset) -> pd.DataFrame:
    """Average midday price of the neighbouring countries (control group)."""
    rows = {}
    for day in CONTROL_DAYS:
        row = {"IT Sud": window(data.price("IT Sud"), day).mean()}
        for country in NEIGHBOURS:
            if country not in data.prices.columns:
                row[country] = float("nan")
                continue
            row[country] = window(data.price(country), day).mean()
        rows[day] = row
    return pd.DataFrame(rows).T


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #

def report(data: Dataset) -> None:
    print("=" * 78)
    print("WHY THE DAY-AHEAD PRICE WENT TO ZERO IN SOUTHERN ITALY ON 16 OCTOBER 2026")
    print("=" * 78)

    low = zero_price_window(data)
    print("\n1) THE ZERO-PRICE WINDOW")
    print(f"   quarter-hours below 1 EUR/MWh in the IT Sud zone : {len(low)}")
    print(f"   from {low.index.min():%d/%m %H:%M} to {low.index.max():%d/%m %H:%M} (Italian time)")
    print(f"   price: min {low['price'].min():.2f} | max {low['price'].max():.2f} EUR/MWh")
    for zone in MACRO_SOUTH:
        same = data.price(zone).reindex(low.index)
        print(f"   {zone:14s} price in the same quarter-hours: "
              f"min {same.min():.2f} | max {same.max():.2f}")
    print(f"   macro-zone surplus in those quarter-hours: "
          f"mean {low['macro_surplus_mw'].mean():.0f} | max {low['macro_surplus_mw'].max():.0f} MW")

    print("\n2) THE SAME MORNING IN THE OTHER ZONES (11:00-15:00 average)")
    for day in CONTROL_DAYS:
        print(f"   {day}")
        for zone in ITALY:
            value = window(data.price(zone), day).mean()
            print(f"      {zone:16s} {value:8.2f} EUR/MWh")

    print("\n2b) WHERE THE POWER CAME FROM: midday mix of the southern macro-zone (MW)")
    print(generation_mix(data).round(0).to_string())

    print("\n2c) THE EVENT, QUARTER-HOUR BY QUARTER-HOUR (16 October, 09:00-16:00)")
    print("   time     price  macro surplus  corridor flow  corridor limit  utilisation")
    table = quarter_hour_table(data)
    for instant, row in table.iterrows():
        print(f"   {instant:%H:%M}  {row['price']:7.2f}  {row['surplus']:12.0f}  "
              f"{row['flow']:13.0f}  {row['limit']:14.0f}  {row['utilisation'] * 100:11.0f}%")

    print("\n3) THE BOTTLENECK: Terna final transit limit vs physical flow")
    corridor = bottleneck(data)
    for day in CONTROL_DAYS:
        part = window(corridor["limit_mw"], day)
        flow = window(corridor["flow_mw"], day)
        peak = window(corridor["peak_flow_mw"], day)
        if part.empty:
            continue
        print(f"   {day}: limit mean {part.mean():.0f} MW | flow mean {flow.mean():.0f} MW "
              f"({flow.mean() / part.mean() * 100:.0f}% of the limit) | "
              f"peak quarter-hour {peak.max():.0f} MW ({peak.max() / part.mean() * 100:.0f}%)")
    zero_flow = low["corridor_flow_mw"].mean()
    zero_limit = low["corridor_limit_mw"].mean()
    print(f"   during the zero-price quarter-hours: limit {zero_limit:.0f} MW | "
          f"flow {zero_flow:.0f} MW ({zero_flow / zero_limit * 100:.0f}% of the limit)")

    print("\n3b) THE THREE INTERFACES OF THE MACRO-ZONE: TERNA LIMIT vs PHYSICAL FLOW")
    for border, row in export_borders(data).iterrows():
        print(f"   {border:26s} limit {row['limit_min_mw']:5.0f}-{row['limit_max_mw']:.0f} MW | "
              f"flow {row['flow_avg_mw']:5.0f} MW | utilisation "
              f"{row['utilisation_avg'] * 100:3.0f}% on average, "
              f"{row['utilisation_max'] * 100:3.0f}% at peak")
        print(f"   {'':26s} peak flow {row['flow_peak_mw']:.0f} MW at "
              f"{row['flow_peak_at']:%H:%M} | headroom to the limit "
              f"{row['headroom_mw']:+.0f} MW")
    capacity = export_capacity(data)
    surplus = capacity["surplus_mw"].mean()
    print(f"   export capacity of the three interfaces: "
          f"{capacity['capacity_mw'].min():.0f} - {capacity['capacity_mw'].max():.0f} MW")
    print(f"   surplus {surplus:.0f} MW -> at least "
          f"{surplus - capacity['capacity_mw'].min():.0f} MW could not leave the macro-zone")

    print("\n4) WHY THE SURPLUS COULD NOT LEAVE")
    balance = export_balance(data)
    print(balance.round(0).to_string())

    print("\n5) PRICE AS A FUNCTION OF THE LOCAL SURPLUS (IT Sud, 15-18 October)")
    print(price_versus_surplus(data).round(2).to_string())

    print("\n6) CONTROL GROUP: MIDDAY PRICES OF THE NEIGHBOURING COUNTRIES")
    print(neighbour_table(data).round(2).to_string())

    print("\n7) GRID OUTAGES DECLARED ON THE IT SUD <-> IT CALABRIA BORDER (A78)")
    for _, row in data.outages.iterrows():
        print(f"   {row['domain_in']} <-> {row['domain_out']} | available capacity "
              f"{row['available_capacity_mw']} {row['unit']} | from {row['start_utc']} "
              f"to {row['end_utc']} | document created {row['document_created_utc']}")

    print("\n8) THE OPPOSITE SIGN: SICILY AT THE 400 EUR/MWh CAP ON 17 OCTOBER")
    sicily = data.price("IT Sicilia")
    capped = sicily[sicily >= 399.99]
    if len(capped):
        nord = data.price("IT Nord").reindex(capped.index)
        print(f"   {len(capped)} quarter-hours at exactly 400.00 EUR/MWh in IT Sicilia "
              f"({capped.index.min():%d/%m %H:%M} - {capped.index.max():%d/%m %H:%M})")
        print(f"   while the rest of Italy was priced at {nord.mean():.2f} EUR/MWh on average")
    print()


def main() -> None:
    report(Dataset())


if __name__ == "__main__":
    main()
