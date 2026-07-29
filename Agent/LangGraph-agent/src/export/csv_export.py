"""
CSV export engine.
"""

from __future__ import annotations

import csv
import os
import uuid


def generate_csv(title: str, data: list[dict], output_dir: str = "") -> str:
    """Generate a CSV report. Returns the output file path."""
    output_dir = output_dir or "/tmp/fiber_reports"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{uuid.uuid4().hex}.csv")

    if data:
        headers = list(data[0].keys())
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(data)
    else:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("No data\n")

    return output_path
