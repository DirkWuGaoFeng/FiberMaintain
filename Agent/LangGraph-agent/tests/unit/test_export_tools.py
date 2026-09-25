"""
导出工具单元测试 [v7.1]。

测试：
- PDF 导出（reportlab）
- Excel 导出（openpyxl）
- CSV 导出
- 空数据处理
- 错误处理
"""

import os

import pytest

from src.tools.export_tools import export_csv, export_excel, export_pdf


class TestExportCsv:
    """CSV 导出测试。"""

    @pytest.mark.asyncio
    async def test_basic_csv_export(self, tmp_path, monkeypatch):
        """将基本表格数据导出为 CSV。"""
        monkeypatch.setenv("EXPORT_DIR", str(tmp_path))
        # 重新导入以获取新环境变量
        import src.tools.export_tools as et

        monkeypatch.setattr(et, "EXPORT_DIR", str(tmp_path))

        data = [
            {"fiber_id": 1, "spanloss": 3.2, "color": "GREEN"},
            {"fiber_id": 2, "spanloss": 6.5, "color": "YELLOW"},
            {"fiber_id": 3, "spanloss": 9.2, "color": "RED"},
        ]
        result = await export_csv.ainvoke({"title": "Fiber Report", "data": data})
        assert "CSV exported" in result
        # 验证文件已创建
        file_path = result.split(": ")[1]
        assert os.path.exists(file_path)

    @pytest.mark.asyncio
    async def test_csv_content_correct(self, tmp_path, monkeypatch):
        """验证 CSV 文件内容与输入数据一致。"""
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
        """空数据列表应生成 'No data' 文件。"""
        import src.tools.export_tools as et

        monkeypatch.setattr(et, "EXPORT_DIR", str(tmp_path))

        result = await export_csv.ainvoke({"title": "Empty", "data": []})
        assert "CSV exported" in result
        file_path = result.split(": ")[1]
        with open(file_path, "r", encoding="utf-8") as f:
            assert "No data" in f.read()


class TestExportExcel:
    """Excel 导出测试。"""

    @pytest.mark.asyncio
    async def test_basic_excel_export(self, tmp_path, monkeypatch):
        """将数据导出为 Excel 文件。"""
        import src.tools.export_tools as et

        monkeypatch.setattr(et, "EXPORT_DIR", str(tmp_path))

        data = [
            {"fiber_id": 1, "spanloss": 3.2, "status": "normal"},
            {"fiber_id": 2, "spanloss": 6.5, "status": "warning"},
        ]
        result = await export_excel.ainvoke(
            {
                "title": "Fiber Data",
                "data": data,
                "sheet_name": "Fibers",
            }
        )
        assert "Excel exported" in result
        file_path = result.split(": ")[1]
        assert os.path.exists(file_path)
        assert file_path.endswith(".xlsx")

    @pytest.mark.asyncio
    async def test_excel_empty_data(self, tmp_path, monkeypatch):
        """空数据也应创建有效的 Excel 文件。"""
        import src.tools.export_tools as et

        monkeypatch.setattr(et, "EXPORT_DIR", str(tmp_path))

        result = await export_excel.ainvoke(
            {
                "title": "Empty",
                "data": [],
                "sheet_name": "Sheet1",
            }
        )
        assert "Excel exported" in result

    @pytest.mark.asyncio
    async def test_excel_custom_sheet_name(self, tmp_path, monkeypatch):
        """应应用自定义的工作表名称。"""
        import src.tools.export_tools as et

        monkeypatch.setattr(et, "EXPORT_DIR", str(tmp_path))

        from openpyxl import load_workbook

        data = [{"col1": "val1"}]
        result = await export_excel.ainvoke(
            {
                "title": "Test",
                "data": data,
                "sheet_name": "CustomSheet",
            }
        )
        file_path = result.split(": ")[1]
        wb = load_workbook(file_path)
        assert "CustomSheet" in wb.sheetnames


class TestExportPdf:
    """PDF 导出测试。"""

    @pytest.mark.asyncio
    async def test_basic_pdf_export(self, tmp_path, monkeypatch):
        """将报告内容导出为 PDF。"""
        import src.tools.export_tools as et

        monkeypatch.setattr(et, "EXPORT_DIR", str(tmp_path))

        result = await export_pdf.ainvoke(
            {
                "title": "Fiber Maintenance Report",
                "content": "All fibers are within normal parameters.\n\nTotal: 120 fibers.",
            }
        )
        assert "PDF exported" in result
        file_path = result.split(": ")[1]
        assert os.path.exists(file_path)
        assert file_path.endswith(".pdf")

    @pytest.mark.asyncio
    async def test_pdf_empty_content(self, tmp_path, monkeypatch):
        """空内容也应生成带标题的 PDF。"""
        import src.tools.export_tools as et

        monkeypatch.setattr(et, "EXPORT_DIR", str(tmp_path))

        result = await export_pdf.ainvoke(
            {
                "title": "Empty Report",
                "content": "",
            }
        )
        assert "PDF exported" in result

    @pytest.mark.asyncio
    async def test_pdf_long_content(self, tmp_path, monkeypatch):
        """长内容应无错误地被处理。"""
        import src.tools.export_tools as et

        monkeypatch.setattr(et, "EXPORT_DIR", str(tmp_path))

        long_content = "\n\n".join([f"Paragraph {i}: " + "x" * 200 for i in range(50)])
        result = await export_pdf.ainvoke(
            {
                "title": "Long Report",
                "content": long_content,
            }
        )
        assert "PDF exported" in result
