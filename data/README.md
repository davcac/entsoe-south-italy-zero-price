# Data

Everything in this folder is derived from two public sources. The raw documents
are **not** versioned (they are large); this folder is the compact, analysis-ready
version of them, so that every figure and every number in the README can be
checked without an API key.

Retrieved on **19 October 2026** for the delivery days **16–18 October 2026**
(15 October for load, generation and flows, which are downloaded with one extra
day of history).

| file | rows | content | source |
|---|---:|---|---|
| `day_ahead_prices.csv` | 3 744 | day-ahead prices of the 7 Italian zones and 6 neighbouring countries, 15-minute resolution | ENTSO-E **A44** |
| `load_generation.csv` | 29 184 | load and generation per zone, split by technology (solar / wind / hydro / gas / other) | ENTSO-E **A65**, **A75** |
| `cross_border_flows.csv` | 1 632 | net physical flows on the five borders that matter, in one canonical direction per border | ENTSO-E **A11** |
| `grid_unavailability.csv` | 2 | outage declarations on the transmission grid (IT Sud ↔ IT Calabria) | ENTSO-E **A78** |
| `transit_limits.csv` | 7 016 | transit limits between the Sud and Centro-Sud zones, hourly: final, forecast and post-session margins | Terna, download centre |

## Conventions

* **Time.** Every timestamp is stored twice: `timestamp_utc` (ISO 8601, UTC) and
  `timestamp_local` (Italian local time). Italy is on CET/CEST; the delivery days
  analysed are entirely inside CEST (UTC+2).
* **Prices** are EUR/MWh, day-ahead (MGP), as published by ENTSO-E.
* **Loads and generation** are MW, per zone, aggregated over the technologies of
  the `source` column.
* **Flows** are MW. The sign is the **net** flow in the direction of the `border`
  label: positive means the power flows from the first zone to the second.
  ENTSO-E publishes one document per direction and each document carries a value
  only while the flow actually runs that way, so the net flow is
  `f(forward) − f(backward)`.
* **Transit limits** are MW, one value per hour, in Italian local time.

## Two traps worth knowing about

1. **Sparse curves (`curveType A03`).** ENTSO-E writes a quarter-hour only when
   its value changes; the omitted positions repeat the previous one. Between 10
   and 29 quarter-hours per zone had to be reconstructed here. `src/entsoe.py`
   does it; skipping it shifts every timestamp and biases every average.
2. **Different resolutions on the same border.** The Italy ↔ Greece and
   Sicily ↔ Malta interconnectors are published with an **hourly** resolution,
   the Italian internal borders with 15 minutes.

## Licences

* ENTSO-E Transparency Platform: free, non-commercial use under the platform's
  terms of use.
* Terna: public open data.

The derived files in this folder inherit the terms of the original sources.
