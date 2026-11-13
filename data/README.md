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
| `cross_border_flows_directional.csv` | 3 264 | gross physical flows, one row per published direction: export and import kept apart | ENTSO-E **A11** |
| `grid_unavailability.csv` | 2 | outage declarations on the transmission grid (IT Sud ↔ IT Calabria) | ENTSO-E **A78** |
| `transit_limits.csv` | 14 650 | transit limits declared by Terna, hourly: final limits for the five interfaces of the macro-zone, plus forecast and post-session margins for the Sud ↔ Centro-Sud corridor | Terna, download centre |

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
* **Directional flows.** `cross_border_flows_directional.csv` keeps the two sides
  of every border apart: one row per direction ENTSO-E publishes, with the gross
  flow that really went in that direction (zeros included). The net of the two
  directions of a border is exactly the value stored in
  `cross_border_flows.csv` — the two files are verified against each other.
* **Transit limits** are MW, one value per hour, in Italian local time. The zone
  names are Terna's own: `South`, `Centre-South`, `Calabria`, `Sicily`, `Malta`,
  `Greece 2`. **`Greece 2` is the physical interconnection** with Greece (500 MW);
  `Greece` is the commercial coupling point, whose limit (10 000 MW) never binds.

## Two traps worth knowing about

1. **Sparse curves (`curveType A03`).** ENTSO-E writes a quarter-hour only when
   its value changes; the omitted positions repeat the previous one. Between 10
   and 29 quarter-hours per zone had to be reconstructed here. `src/entsoe.py`
   does it; skipping it shifts every timestamp and biases every average.
2. **Different resolutions on the same border.** The Italy ↔ Greece interconnectors
   are published with an **hourly** resolution, the Italian internal borders and
   Sicily ↔ Malta with 15 minutes.

## Licences

* ENTSO-E Transparency Platform: free, non-commercial use under the platform's
  terms of use.
* Terna: public open data.

The derived files in this folder inherit the terms of the original sources.
