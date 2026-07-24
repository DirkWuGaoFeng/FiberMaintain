"""知识库入库管道：分块 → 向量化 → ChromaDB。
支持命令行全量重建：python -m src.rag.ingest --rebuild
"""
from __future__ import annotations
import argparse, asyncio, hashlib, re
from pathlib import Path

from src.settings import settings
from src.rag.engine import rag_engine

# 目录 → collection 映射
DIR_COLLECTION = {
    "01_设备技术手册": "device_manual",
    "02_维护操作规范": "maintenance_guide",
    "03_告警处理指南": "alarm_guide",
    "04_历史故障案例": "fault_cases",
    "05_衰耗阈值标准": "threshold_standard",
    "06_网元配置规范": "ne_config",
}

class RecursiveSplitter:
    """轻量递归字符分块器（512/50）。"""
    SEPS = ["\n## ", "\n### ", "\n\n", "\n", "。", "；", " "]

    def __init__(self, size: int = 512, overlap: int = 50):
        self.size, self.overlap = size, overlap

    def split(self, text: str, seps: list[str] | None = None) -> list[str]:
        seps = seps or self.SEPS
        if len(text) <= self.size:
            return [text] if text.strip() else []
        sep, rest = seps[0], seps[1:]
        parts = text.split(sep) if sep in text else [text]
        chunks: list[str] = []
        buf = ""
        for p in parts:
            piece = p if buf == "" else buf + sep + p
            if len(piece) <= self.size:
                buf = piece
            else:
                if buf:
                    chunks.append(buf)
                if len(p) > self.size:
                    chunks.extend(self.split(p, rest))
                    buf = ""
                else:
                    # 重叠：保留上一块尾部
                    buf = (buf[-self.overlap:] + sep + p) if buf else p
        if buf:
            chunks.append(buf)
        return [c for c in chunks if c.strip()]


def detect_collection(path: Path) -> str:
    for part in path.parts:
        if part in DIR_COLLECTION:
            return DIR_COLLECTION[part]
    return "maintenance_guide"


async def ingest_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    collection = detect_collection(path)
    splitter = RecursiveSplitter(settings.rag["chunk_size"],
                                 settings.rag["chunk_overlap"])
    chunks = splitter.split(text)
    source = str(path.relative_to(Path(settings.knowledge["approved_dir"])))
    ids, metas = [], []
    for i, ch in enumerate(chunks):
        cid = hashlib.md5(f"{source}:{i}".encode()).hexdigest()
        ids.append(cid)
        metas.append({"source": source, "chunk": i,
                      "collection": collection})
    await rag_engine.add_documents(collection, chunks, metas, ids)
    return {"source": source, "collection": collection, "chunks": len(chunks)}


async def rebuild_all() -> list[dict]:
    base = Path(settings.knowledge["approved_dir"])
    results = []
    for md in sorted(base.rglob("*.md")):
        results.append(await ingest_file(md))
    return results


async def ingest_approved_doc(doc_id: int) -> dict:
    """知识库管理接口：入库单篇已审核文档。"""
    from src.memory.store import memory
    doc = await memory.get_kb_doc(doc_id)
    if not doc or doc["status"] != "APPROVED":
        return {"error": "文档不存在或未通过审核"}
    path = Path(doc["file_path"])
    result = await ingest_file(path)
    await memory.update_kb_status(doc_id, "ACTIVE")
    return {"ingested": True, **result}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true",
                        help="全量重建知识库")
    args = parser.parse_args()
    if args.rebuild:
        results = asyncio.run(rebuild_all())
        total = sum(r["chunks"] for r in results)
        print(f"知识库重建完成: {len(results)} 篇文档 / {total} 个分块")
        for r in results:
            print(f"  [{r['collection']}] {r['source']} ({r['chunks']} chunks)")

if __name__ == "__main__":
    main()