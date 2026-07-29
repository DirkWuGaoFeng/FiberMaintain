"""
PDF export engine using reportlab + matplotlib.
"""

from __future__ import annotations

import os
import uuid


def generate_pdf(title: str, content: str, charts: list[dict] | None = None, output_dir: str = "") -> str:
    """Generate a PDF report. Returns the output file path."""
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors

    output_dir = output_dir or "/tmp/fiber_reports"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{uuid.uuid4().hex}.pdf")

    doc = SimpleDocTemplate(output_path, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(title, styles["Title"]))
    story.append(Spacer(1, 12))

    for para in content.split("\n\n"):
        stripped = para.strip()
        if stripped:
            if stripped.startswith("#"):
                story.append(Paragraph(stripped.lstrip("#"), styles["Heading2"]))
            elif stripped.startswith("- ") or stripped.startswith("* "):
                story.append(Paragraph(stripped, styles["Normal"]))
            else:
                story.append(Paragraph(stripped, styles["Normal"]))
            story.append(Spacer(1, 6))

    doc.build(story)
    return output_path
