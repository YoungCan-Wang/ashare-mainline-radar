#!/usr/bin/env python3
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ashare_mainline_radar.feishu import post_feishu_text, write_feishu_status


def main() -> int:
    webhook_url = os.getenv("FEISHU_WEBHOOK_URL")
    output_path = Path(os.getenv("FEISHU_STATUS_PATH", "reports/latest/notification_status.json"))
    if not webhook_url:
        print("FEISHU_WEBHOOK_URL is not set")
        return 2
    status = post_feishu_text(
        webhook_url,
        "A股市场主线雷达 webhook diagnostic: this is a connectivity test.",
    )
    write_feishu_status(output_path, status)
    print(f"Feishu status: {status.status}; code={status.code}; message={status.message}")
    return 0 if status.status == "sent" else 1


if __name__ == "__main__":
    raise SystemExit(main())
