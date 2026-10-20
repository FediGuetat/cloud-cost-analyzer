"""Command line: python -m cloud_cost_analyzer [file] [options]"""

import argparse
from pathlib import Path

from .analysis import DEFAULT_COST, analyze, select_month
from .load import load_focus
from .report import console_summary, write_chart, write_excel, write_powerbi

DEFAULT_DATA = Path("data/focus_sample_100000.csv.gz")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="cloud_cost_analyzer",
        description="Analyse a FOCUS cloud billing export and find savings.",
    )
    parser.add_argument("file", nargs="?", default=DEFAULT_DATA, type=Path,
                        help="FOCUS export, .csv or .csv.gz (default: the sample data)")
    parser.add_argument("--out", default=Path("reports"), type=Path, help="output folder (default: reports)")
    parser.add_argument("--month", default="auto",
                        help="billing month YYYY-MM, 'auto' (biggest month) or 'all'")
    parser.add_argument("--cost", default=DEFAULT_COST, choices=["BilledCost", "EffectiveCost"],
                        help="which cost to analyse (default: BilledCost = the invoice)")
    parser.add_argument("--top", default=10, type=int, help="rows per breakdown before 'Other'")
    args = parser.parse_args(argv)

    df = select_month(load_focus(args.file), args.month)
    if df.empty:
        parser.error(f"no rows for month {args.month}")
    results = analyze(df, cost=args.cost, top=args.top)

    print(console_summary(results))
    print()
    print("written:")
    print(" ", write_excel(results, args.out / "cost_report.xlsx"))
    print(" ", write_powerbi(df, args.out / "powerbi_costs.csv"))
    print(" ", write_chart(results, args.out / "daily_cost.png"))


if __name__ == "__main__":
    main()
