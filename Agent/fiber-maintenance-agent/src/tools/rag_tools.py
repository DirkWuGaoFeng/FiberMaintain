"""RAG 类 Tools（rag-retriever / report-generator）。"""
from src.tools.registry import tool
from src.rag.engine import rag_engine
from pathlib import Path

@tool(name="read_file", tags=["rag", "file"])
async def read_file(file_path: str) -> dict:
    """读取指定路径的文件内容。

    Args:
        file_path: 文件绝对路径
    """
    path = Path(file_path)
    if not path.exists():
        return {"error": f"文件不存在: {file_path}", "success": False}
    try:
        content = path.read_text(encoding="utf-8")
        return {"content": content, "file_path": str(path), "success": True}
    except Exception as e:
        return {"error": f"读取文件失败: {str(e)}", "success": False}

@tool(name="rag_query", tags=["rag"])
async def rag_query(query: str, collection: str | None = None,
                    top_k: int = 3) -> dict:
    """混合检索知识库（Vector+BM25+Rerank），返回 Top-K 知识片段。

    Args:
        query: 检索问题
        collection: 知识库分类（可选，缺省全库检索）
        top_k: 返回片段数
    """
    hits = await rag_engine.hybrid_search(query, collection, top_k)
    return {"query": query, "hits": hits, "count": len(hits)}

@tool(name="vector_search", tags=["rag"])
async def vector_search(query: str, top_k: int = 10) -> dict:
    """向量语义检索。

    Args:
        query: 检索问题
        top_k: 返回条数
    """
    return {"hits": await rag_engine.vector_search(query, top_k)}

@tool(name="bm25_search", tags=["rag"])
async def bm25_search(query: str, top_k: int = 10) -> dict:
    """BM25 关键词检索。

    Args:
        query: 检索问题
        top_k: 返回条数
    """
    return {"hits": await rag_engine.bm25_search(query, top_k)}

@tool(name="knowledge_upload", tags=["rag", "admin"])
async def knowledge_upload(doc_id: int) -> dict:
    """将已审核通过的待入库文档执行分块+向量化入库。

    Args:
        doc_id: 知识库管理接口中的文档 ID
    """
    from src.rag.ingest import ingest_approved_doc
    return await ingest_approved_doc(doc_id)

@tool(name="knowledge_ingest", tags=["rag", "admin"])
async def knowledge_ingest(doc_id: int) -> dict:
    """knowledge_upload 的别名，兼容旧代码。"""
    return await knowledge_upload(doc_id)