"""One-shot entry point: print the report and rebuild the figures.

    python src/run.py

The script only reads the CSV dataset in ``data/``; no API key is needed.
Use ``python src/build_dataset.py --raw <folder>`` to rebuild that dataset
from fresh ENTSO-E and Terna downloads.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import analysis      # noqa: E402
import figures       # noqa: E402


def main() -> None:
    data = analysis.Dataset()
    analysis.report(data)
    print("figures:")
    figures.figure_prices(data)
    figures.figure_surplus(data)
    figures.figure_bottleneck(data)
    figures.figure_balance(data)
    figures.figure_scatter(data)


if __name__ == "__main__":
    main()
