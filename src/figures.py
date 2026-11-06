"""Charts of the analysis. Run ``python src/figures.py`` to regenerate them.

Every figure is built from the CSV dataset in ``data/``, so it can be
reproduced without an API key.
"""

from __future__ import annotations

import os
import sys

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt          # noqa: E402
import pandas as pd                     # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import analysis as an                   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIGURES = os.path.join(HERE, "..", "figures")

plt.rcParams.update({
    "figure.dpi": 140,
    "savefig.bbox": "tight",
    "font.size": 10,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "axes.spines.top": False,
    "axes.spines.right": False,
})

ZONE_COLOURS = {
    "IT Nord": "#1f77b4",
    "IT Centro-Nord": "#2ca02c",
    "IT Centro-Sud": "#9467bd",
    "IT Sud": "#d62728",
    "IT Sicilia": "#ff7f0e",
    "IT Sardegna": "#8c564b",
    "IT Calabria": "#e377c2",
}


def save(figure, name: str) -> str:
    os.makedirs(FIGURES, exist_ok=True)
    path = os.path.join(FIGURES, name)
    figure.savefig(path)
    plt.close(figure)
    print(f"  saved {name}")
    return path


# --------------------------------------------------------------------------- #

def figure_prices(data: an.Dataset) -> None:
    """Day-ahead price of every Italian zone, 16-18 October."""
    prices = data.prices[[z for z in an.ITALY if z in data.prices.columns]]
    window = prices.loc["2026-10-16 00:00":"2026-10-18 23:45"]

    figure, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True,
                                 gridspec_kw={"height_ratios": [2, 1]})
    order = [z for z in an.ITALY if z != "IT Sud"] + ["IT Sud"]
    for zone in order:
        axes[0].plot(window.index, window[zone], label=zone, color=ZONE_COLOURS.get(zone),
                     linewidth=1.3, linestyle="--" if zone in ("IT Calabria", "IT Sicilia") else "-")
    axes[0].axhline(0, color="black", linewidth=0.8)
    axes[0].set_ylabel("EUR/MWh")
    axes[0].set_title("Italian day-ahead prices by bidding zone — 16 to 18 October 2026")
    axes[0].legend(ncol=4, fontsize=8, loc="upper left")
    axes[0].annotate("16 Oct: the South is priced at zero\nwhile the North stays at ~200 EUR/MWh",
                     xy=(pd.Timestamp("2026-10-16 13:00", tz="Europe/Rome"), 10),
                     xytext=(pd.Timestamp("2026-10-17 20:00", tz="Europe/Rome"), 60),
                     arrowprops=dict(arrowstyle="->", color="#d62728"), color="#d62728")
    axes[0].text(pd.Timestamp("2026-10-16 13:00", tz="Europe/Rome"), 320,
                 "IT Calabria and IT Sicilia follow IT Sud", fontsize=8, color="#333333")

    spread = window.max(axis=1) - window.min(axis=1)
    axes[1].fill_between(spread.index, 0, spread, color="#d62728", alpha=0.35)
    axes[1].set_ylabel("max - min\nacross zones")
    axes[1].set_title("Zonal price spread: the maximum and the minimum of the seven zones")
    axes[1].set_xlabel("Italian local time")
    figure.autofmt_xdate()
    save(figure, "fig1_prices_by_zone.png")


def figure_surplus(data: an.Dataset) -> None:
    """Southern surplus against the Sud price."""
    surplus = data.macro_surplus()
    price = data.price("IT Sud")
    window = slice("2026-10-15 00:00", "2026-10-18 23:45")

    figure, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    axes[0].fill_between(surplus.index[surplus.index < window.stop], 0,
                         surplus[surplus.index < window.stop], color="#2ca02c", alpha=0.35,
                         label="surplus of Sud + Calabria + Sicilia")
    axes[0].axhline(0, color="black", linewidth=0.8)
    axes[0].set_ylabel("MW")
    axes[0].legend(fontsize=8)
    axes[0].set_title("The southern macro-zone was long: generation minus load")

    axes[1].plot(price.index, price, color="#d62728", linewidth=1.6)
    axes[1].axhline(0, color="black", linewidth=0.8)
    axes[1].set_ylabel("EUR/MWh")
    axes[1].set_xlabel("Italian local time")
    axes[1].set_title("IT Sud day-ahead price")
    figure.autofmt_xdate()
    save(figure, "fig2_surplus_and_price.png")


def figure_bottleneck(data: an.Dataset) -> None:
    """Terna transit limit against the physical flow on the corridor."""
    corridor = an.bottleneck(data)
    window = corridor.loc["2026-10-16 00:00":"2026-10-18 23:00"]

    figure, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    axes[0].step(window.index, window["limit_mw"], where="post", color="#1f77b4",
                 linewidth=1.8, label="final transit limit (Terna)")
    axes[0].plot(window.index, window["flow_mw"], color="#d62728", linewidth=1.6,
                 label="physical flow, hourly average (negative = import)")
    axes[0].axhline(0, color="black", linewidth=0.8)
    axes[0].set_ylabel("MW")
    axes[0].legend(fontsize=8)
    axes[0].set_title("The Sud \u2192 Centro-Sud corridor was saturated on 16 October")
    axes[0].annotate("16 Oct, 12:00-13:00:\nlimit cut to 2400 MW\nwhile the flow stays at 2450 MW",
                     xy=(pd.Timestamp("2026-10-16 12:30", tz="Europe/Rome"), 2500),
                     xytext=(pd.Timestamp("2026-10-16 20:00", tz="Europe/Rome"), 3300),
                     arrowprops=dict(arrowstyle="->", color="#333333"), fontsize=8, color="#333333")

    axes[1].bar(window.index, window["utilisation"] * 100, width=0.035, color="#1f77b4")
    axes[1].axhline(100, color="#d62728", linewidth=1.2, linestyle="--")
    axes[1].set_ylabel("% of the limit")
    axes[1].set_xlabel("Italian local time")
    axes[1].set_title("Corridor utilisation")
    figure.autofmt_xdate()
    save(figure, "fig3_bottleneck.png")


def figure_balance(data: an.Dataset) -> None:
    """Surplus against the power that actually left the macro-zone."""
    surplus = data.macro_surplus()
    exports = (data.flow(an.CORRIDOR)
               + data.flow("IT Sud -> Greece").resample("h").mean()
               + data.flow("IT Sicilia -> Malta").resample("h").mean())
    frame = pd.DataFrame({"surplus": surplus, "exports": exports}).dropna()
    frame = frame.loc["2026-10-16 00:00":"2026-10-18 23:00"]

    figure, axis = plt.subplots(figsize=(11, 4.5))
    shift = pd.Timedelta(minutes=8)
    axis.bar(frame.index - shift, frame["surplus"], width=0.025, color="#2ca02c",
             alpha=0.8, label="surplus of the macro-zone")
    axis.bar(frame.index + shift, frame["exports"], width=0.025, color="#1f77b4",
             alpha=0.8, label="power that actually left the macro-zone")
    axis.axhline(0, color="black", linewidth=0.8)
    axis.set_ylabel("MW")
    axis.set_xlabel("Italian local time")
    axis.set_title("On 16 October the surplus was there, the export capacity was not")
    axis.legend(fontsize=8)
    figure.autofmt_xdate()
    save(figure, "fig4_surplus_vs_exports.png")


def figure_scatter(data: an.Dataset) -> None:
    """Local surplus against the local price."""
    frame = pd.DataFrame({
        "price": data.price("IT Sud"),
        "surplus": data.zone_surplus("IT Sud"),
    }).dropna()
    frame = frame.loc["2026-10-15 00:00":"2026-10-18 23:45"]
    zero = frame[frame["price"] < 1.0]

    figure, axis = plt.subplots(figsize=(8, 5.2))
    axis.scatter(frame["surplus"], frame["price"], s=22, color="#1f77b4", alpha=0.65,
                 label="quarter-hours, 15-18 October")
    axis.scatter(zero["surplus"], zero["price"], s=70, color="#d62728", zorder=3,
                 label="priced below 1 EUR/MWh")
    axis.axhline(1, color="#d62728", linewidth=0.8, linestyle="--")
    axis.set_xlabel("surplus of the IT Sud zone (MW)")
    axis.set_ylabel("IT Sud day-ahead price (EUR/MWh)")
    axis.set_title("The price collapses once the local surplus is large enough")
    axis.legend(fontsize=8)
    save(figure, "fig5_price_vs_surplus.png")


def main() -> None:
    data = an.Dataset()
    print("figures:")
    figure_prices(data)
    figure_surplus(data)
    figure_bottleneck(data)
    figure_balance(data)
    figure_scatter(data)


if __name__ == "__main__":
    main()
