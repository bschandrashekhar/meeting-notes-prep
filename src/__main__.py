"""CLI entry point: python -m src [--date YYYY-MM-DD]"""

import argparse
import logging
import sys
from datetime import datetime, timedelta

from src.config import IST, LOGS_DIR
from src.pipeline import run_pipeline, should_run_today


def main() -> None:
    parser = argparse.ArgumentParser(description="Meeting Preparation Pipeline")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Target date (YYYY-MM-DD). Defaults to tomorrow.",
    )
    args = parser.parse_args()

    # Logging
    log_file = LOGS_DIR / f"pipeline_{datetime.now(IST).strftime('%Y-%m-%d')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(name)-30s  %(levelname)-8s  %(message)s",
        handlers=[
            logging.FileHandler(str(log_file), encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        if not should_run_today():
            print("Skipping — today is Friday or Saturday (IST)")
            return
        target_date = datetime.now(IST).date() + timedelta(days=1)

    print(f"Running pipeline for {target_date}")
    results = run_pipeline(target_date)
    print(f"Processed {len(results)} meeting(s)")


if __name__ == "__main__":
    main()
