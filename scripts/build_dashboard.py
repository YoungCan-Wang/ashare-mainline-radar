#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ashare_mainline_radar.dashboard import fetch_dashboard_history, write_dashboard


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the static A-share radar dashboard.")
    parser.add_argument("--bundle", type=Path, default=Path("reports/latest/storage_bundle.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("reports/latest/dashboard"))
    parser.add_argument("--source-dir", type=Path, default=Path("dashboard/dist"))
    parser.add_argument("--local-only", action="store_true")
    args = parser.parse_args()

    history = None if args.local_only else fetch_dashboard_history()
    data_path = write_dashboard(args.bundle, args.output_dir, args.source_dir, history=history)
    print(f"Wrote dashboard data to {data_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
