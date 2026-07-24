"""导出类 Tools（report-generator）。生成可下载文件，24h 有效。"""
from src.tools.registry import tool
from src.export.exporters import export_report

@tool(name="export_pdf", tags=["export"])
async def export_pdf(title: str, sections: list[dict],
                     chart: dict | None = None) -> dict:
    """生成 PDF 报告（含图表），返回下载链接。

    Args:
        title: 报告标题
        sections: 章节列表，每项 {heading, body} 或 {heading, table:{headers,rows}}
        chart: 可选图表 {title, x:[...], series:[{name,data:[...]}]}
    """
    return await export_report("pdf", title, sections, chart)

@tool(name="export_excel", tags=["export"])
async def export_excel(title: str, sections: list[dict],
                       chart: dict | None = None) -> dict:
    """生成 Excel 报告（表格可二次编辑），返回下载链接。

    Args:
        title: 报告标题
        sections: 章节列表，结构同 export_pdf
        chart: 可选图表数据（写入数据表）
    """
    return await export_report("excel", title, sections, chart)

@tool(name="export_csv", tags=["export"])
async def export_csv(title: str, sections: list[dict],
                     chart: dict | None = None) -> dict:
    """生成 CSV 数据文件（UTF-8 BOM，Excel 可直接打开），返回下载链接。

    Args:
        title: 文件标题
        sections: 章节列表，仅表格部分被导出
        chart: 可选图表数据（追加为数据行）
    """
    return await export_report("csv", title, sections, chart)