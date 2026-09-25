"""
导出工具集 —— PDF、Excel 和 CSV 报告生成。

这些工具在本地运行（不调用后端 API）。
"""

from __future__ import annotations

import csv
import logging
import os
import uuid
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# 默认导出目录
EXPORT_DIR = os.environ.get("EXPORT_DIR", "/tmp/fiber_reports")


class ExportPdfInput(BaseModel):
    title: str = Field(description="Report title")
    content: str = Field(description="Report content (Markdown)")
    charts: Optional[list[dict]] = Field(default=[], description="Chart data for matplotlib")


class ExportExcelInput(BaseModel):
    title: str = Field(description="Report/sheet title")
    data: list[dict] = Field(description="Tabular data as list of dicts")
    sheet_name: str = Field(default="Sheet1", description="Excel sheet name")


class ExportCsvInput(BaseModel):
    title: str = Field(description="Report title")
    data: list[dict] = Field(description="Tabular data as list of dicts")


@tool(args_schema=ExportPdfInput)
async def export_pdf(title: str, content: str, charts: Optional[list[dict]] = None) -> str:
    """将分析报告导出为 PDF 文件。
    返回：生成 PDF 的文件路径。"""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

        os.makedirs(EXPORT_DIR, exist_ok=True)
        output_path = os.path.join(EXPORT_DIR, f"{uuid.uuid4().hex}.pdf")

        doc = SimpleDocTemplate(output_path, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []

        # 标题
        story.append(Paragraph(title, styles["Title"]))
        story.append(Spacer(1, 12))

        # 内容（按段落切分）
        for para in content.split("\n\n"):
            if para.strip():
                story.append(Paragraph(para.strip(), styles["Normal"]))
                story.append(Spacer(1, 6))

        doc.build(story)
        return f"PDF exported: {output_path}"
    except Exception as e:
        logger.error(f"[Export] PDF failed: {e}")
        return f"PDF export failed: {e}"


@tool(args_schema=ExportExcelInput)
async def export_excel(title: str, data: list[dict], sheet_name: str = "Sheet1") -> str:
    """将表格数据导出为 Excel 文件。
    返回：生成 Excel 的文件路径。"""
    try:
        from openpyxl import Workbook

        os.makedirs(EXPORT_DIR, exist_ok=True)
        output_path = os.path.join(EXPORT_DIR, f"{uuid.uuid4().hex}.xlsx")

        wb = Workbook()
        ws = wb.active
        ws.title = sheet_name

        if data:
            # 表头
            headers = list(data[0].keys())
            ws.append(headers)
            # 数据行
            for row in data:
                ws.append([row.get(h, "") for h in headers])

        wb.save(output_path)
        return f"Excel exported: {output_path}"
    except Exception as e:
        logger.error(f"[Export] Excel failed: {e}")
        return f"Excel export failed: {e}"


@tool(args_schema=ExportCsvInput)
async def export_csv(title: str, data: list[dict]) -> str:
    """将表格数据导出为 CSV 文件。
    返回：生成 CSV 的文件路径。"""
    try:
        os.makedirs(EXPORT_DIR, exist_ok=True)
        output_path = os.path.join(EXPORT_DIR, f"{uuid.uuid4().hex}.csv")

        if data:
            headers = list(data[0].keys())
            with open(output_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                writer.writerows(data)
        else:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write("No data")

        return f"CSV exported: {output_path}"
    except Exception as e:
        logger.error(f"[Export] CSV failed: {e}")
        return f"CSV export failed: {e}"
