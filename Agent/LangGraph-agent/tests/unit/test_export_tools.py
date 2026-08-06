"""
Unit tests for Export Tools [v7.1].

Tests:
- PDF export (reportlab)
- Excel export (openpyxl)
- CSV export
- Empty data handling
- Error handling
"""

import os

import pytest

from src.tools.export_tools import export_csv, export_excel, export_pdf


class TestExportCsv:
    """CSV export tests."""

    @pytest.mark.asyncio
    async def test_basic_csv_export(self, tmp_path, monkeypatch):
        """Export basic tabular data to CSV."""
        monkeypatch.setenv("EXPORT_DIR", str(tmp_path))
        # Re-import to pick up new env
        import src.tools.export_tools as et
        monkeypatch.setattr(et, "EXPORT_DIR", str(tmp_path))

        data = [
            {"fiber_id": 1, "spanloss": 3.2, "color": "GREEN"},
            {"fiber_id": 2, "spanloss": 6.5, "color": "YELLOW"},
            {"fiber_id": 3, "spanloss": 9.2, "color": "RED"},
        ]
        result = await export_csv.ainvoke({"title": "Fiber Report", "data": data})
        assert "CSV exported" in result
        # Verify file exists
        file_path = result.split(": ")[1]
        assert os.path.exists(file_path)

    @pytest.mark.asyncio
    async def test_csv_content_correct(self, tmp_path, monkeypatch):
        """Verify CSV file content matches input data."""
        import src.tools.export_tools as et
        monkeypatch.setattr(et, "EXPORT_DIR", str(tmp_path))

        data = [{"name": "FIB-001", "value": 3.2}]
        result = await export_csv.ainvoke({"title": "Test", "data": data})
        file_path = result.split(": ")[1]

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "name" in content
        assert "FIB-001" in content
        assert "3.2" in content

    @pytest.mark.asyncio
    async def test_csv_empty_data(self, tmp_path, monkeypatch):
        """Empty data list should produce 'No data' file."""
        import src.tools.export_tools as et
        monkeypatch.setattr(et, "EXPORT_DIR", str(tmp_path))

        result = await export_csv.ainvoke({"title": "Empty", "data": []})
        assert "CSV exported" in result
        file_path = result.split(": ")[1]
        with open(file_path, "r", encoding="utf-8") as f:
            assert "No data" in f.read()


class TestExportExcel:
    """Excel export tests."""

    @pytest.mark.asyncio
    async def test_basic_excel_export(self, tmp_path, monkeypatch):
        """Export data to Excel file."""
        import src.tools.export_tools as et
        monkeypatch.setattr(et, "EXPORT_DIR", str(tmp_path))

        data = [
            {"fiber_id": 1, "spanloss": 3.2, "status": "normal"},
            {"fiber_id": 2, "spanloss": 6.5, "status": "warning"},
        ]
        result = await export_excel.ainvoke({
            "title": "Fiber Data",
            "data": data,
            "sheet_name": "Fibers",
        })
        assert "Excel exported" in result
        file_path = result.split(": ")[1]
        assert os.path.exists(file_path)
        assert file_path.endswith(".xlsx")

    @pytest.mark.asyncio
    async def test_excel_empty_data(self, tmp_path, monkeypatch):
        """Empty data should still create a valid Excel file."""
        import src.tools.export_tools as et
        monkeypatch.setattr(et, "EXPORT_DIR", str(tmp_path))

        result = await export_excel.ainvoke({
            "title": "Empty",
            "data": [],
            "sheet_name": "Sheet1",
        })
        assert "Excel exported" in result

    @pytest.mark.asyncio
    async def test_excel_custom_sheet_name(self, tmp_path, monkeypatch):
        """Custom sheet name should be applied."""
        import src.tools.export_tools as et
        monkeypatch.setattr(et, "EXPORT_DIR", str(tmp_path))

        from openpyxl import load_workbook

        data = [{"col1": "val1"}]
        result = await export_excel.ainvoke({
            "title": "Test",
            "data": data,
            "sheet_name": "CustomSheet",
        })
        file_path = result.split(": ")[1]
        wb = load_workbook(file_path)
        assert "CustomSheet" in wb.sheetnames


class TestExportPdf:
    """PDF export tests."""

    @pytest.mark.asyncio
    async def test_basic_pdf_export(self, tmp_path, monkeypatch):
        """Export report content to PDF."""
        import src.tools.export_tools as et
        monkeypatch.setattr(et, "EXPORT_DIR", str(tmp_path))

        result = await export_pdf.ainvoke({
            "title": "Fiber Maintenance Report",
            "content": "All fibers are within normal parameters.\n\nTotal: 120 fibers.",
        })
        assert "PDF exported" in result
        file_path = result.split(": ")[1]
        assert os.path.exists(file_path)
        assert file_path.endswith(".pdf")

    @pytest.mark.asyncio
    async def test_pdf_empty_content(self, tmp_path, monkeypatch):
        """Empty content should still produce a PDF with title."""
        import src.tools.export_tools as et
        monkeypatch.setattr(et, "EXPORT_DIR", str(tmp_path))

        result = await export_pdf.ainvoke({
            "title": "Empty Report",
            "content": "",
        })
        assert "PDF exported" in result

    @pytest.mark.asyncio
    async def test_pdf_long_content(self, tmp_path, monkeypatch):
        """Long content should be handled without error."""
        import src.tools.export_tools as et
        monkeypatch.setattr(et, "EXPORT_DIR", str(tmp_path))

        long_content = "\n\n".join([f"Paragraph {i}: " + "x" * 200 for i in range(50)])
        result = await export_pdf.ainvoke({
            "title": "Long Report",
            "content": long_content,
        })
        assert "PDF exported" in result
