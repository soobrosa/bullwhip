#!/usr/bin/env python3
"""Anomaly detection on log file sizes.

Computes the median total log size for the past 7 days, then checks if
today's log size is within 90%-115% of the median.  If not, it fails.
Requires at least 5 days of log history.
"""

import argparse
import datetime
import glob
import os
import sys


def valid_date(s):
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"Not a valid date: {s}")


def median(lst):
    if not lst:
        return None
    sorted_lst = sorted(lst)
    n = len(sorted_lst)
    mid = n // 2
    if n % 2 == 1:
        return sorted_lst[mid]
    return (sorted_lst[mid - 1] + sorted_lst[mid]) / 2.0


def get_log_size_for_date(date):
    files = glob.glob(f"logs/{date}/attempt-*.log")
    return sum(os.path.getsize(f) for f in files if os.path.exists(f))


def get_log_sizes_for_last_week(date):
    return [s for s in (
        get_log_size_for_date(date - datetime.timedelta(days=i))
        for i in range(7)
    ) if s > 0]


def main():
    parser = argparse.ArgumentParser(prog="test_log_sizes")
    parser.add_argument("-d", "--date", type=valid_date,
                        default=str(datetime.date.today()))
    args = parser.parse_args()

    log_sizes = get_log_sizes_for_last_week(args.date)
    if not log_sizes:
        print("[!] No log files were found!")
        sys.exit(0)

    if len(log_sizes) < 5:
        print("[!] Not enough log files are available!")
        sys.exit(0)

    med = median(log_sizes)
    min_thr = int(med * 0.9)
    max_thr = int(med * 1.15)
    today_size = get_log_size_for_date(args.date)

    if today_size > max_thr or today_size < min_thr:
        print(f"[!] Log size is below or above threshold:")
        print(f"Expected min: {min_thr} < actual: {today_size} < max: {max_thr}")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
