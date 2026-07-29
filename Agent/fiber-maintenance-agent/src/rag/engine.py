"""RAG 引擎：ChromaDB + BM25 + Reranker 混合检索。
权重：Vector 0.6 + BM25 0.4 → Rerank → Top-3。
Embedding/Reranker 模型缺失时自动降级（纯 BM25 / 纯向量）。
"""
from __future__ import annotations
import asyncio, logging
from functools import lru_cache
from typing import Any

import jieba
import numpy as np
from rank_bm25 import BM25Okapi

from src.settings import settings
from src.monitoring.metrics import RAG_DURATION

logger = logging.getLogger("fiber.rag")

def _lazy_chroma():
    import chromadb
    return chromadb.PersistentClient(path=settings.rag["chromadb_path"])

class Embedder:
    """优先 Ollama 本地 Embedding（nomic-embed-text），回退 sentence-transformers。"""
    def __init__(self) -> None:
        self._model = None
        self._mode = "ollama"
        self._ollama_model = settings.rag.get("embedding_model", "nomic-embed-text")
        # 如果配置的就是 Ollama 本地模型，直接使用
        if "nomic" in self._ollama_model or "embed" in self._ollama_model:
            self._mode = "ollama"
            logger.info("Embedding: Ollama local (%s)", self._ollama_model)
            return
        # 否则尝试 sentence-transformers
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._ollama_model)
            self._mode = "st"
            logger.info("Embedding: sentence-transformers (%s)",
                        self._ollama_model)
        except Exception:
            self._mode = "ollama"
            logger.warning("sentence-transformers 不可用，退回 Ollama embedding (%s)",
                           self._ollama_model)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self._mode == "st":
            return await asyncio.to_thread(
                lambda: self._model.encode(texts, normalize_embeddings=True)
                .tolist())
        # Ollama 本地 Embedding（nomic-embed-text 等）
        import httpx
        async with httpx.AsyncClient(timeout=30) as cli:
            out = []
            base = settings.llm["base_url"].replace("/v1", "")
            for t in texts:
                r = await cli.post(f"{base}/api/embeddings",
                                   json={"model": self._ollama_model, "prompt": t})
                r.raise_for_status()
                out.append(r.json()["embedding"])
            return out

class Reranker:
    """bge-reranker-v2-m3，缺失时跳过（使用加权分数）。"""
    def __init__(self) -> None:
        self._model = None
        model_name = settings.rag.get("reranker_model", "")
        # Ollama 本地模型不支持 FlagReranker，跳过
        if "nomic" in model_name or "embed" in model_name:
            logger.info("Reranker: 跳过（Ollama 本地模型 %s 不支持 FlagReranker）",
                        model_name)
            return
        try:
            from FlagEmbedding import FlagReranker
            self._model = FlagReranker(model_name, use_fp16=True)
            logger.info("Reranker: %s", model_name)
        except Exception:
            logger.warning("FlagEmbedding 不可用，跳过重排（使用加权分数）")

    def rerank(self, query: str, docs: list[dict], top_k: int) -> list[dict]:
        if not self._model:
            return sorted(docs, key=lambda d: d["score"], reverse=True)[:top_k]
        pairs = [[query, d["text"]] for d in docs]
        scores = self._model.compute_score(pairs, normalize=True)
        if isinstance(scores, float):
            scores = [scores]
        for d, s in zip(docs, scores):
            d["rerank_score"] = float(s)
        return sorted(docs, key=lambda d: d["rerank_score"],
                      reverse=True)[:top_k]


class RAGEngine:
    def __init__(self) -> None:
        cfg = settings.rag
        self.prefix = cfg["collection_prefix"]
        self.vector_weight = cfg["vector_weight"]
        self.vector_k = cfg["vector_top_k"]
        self.bm25_k = cfg["bm25_top_k"]
        self.final_k = cfg["final_top_k"]
        self.embedder = Embedder()
        self.reranker = Reranker()
        self._client = None
        self._bm25_cache: dict[str, Any] = {}

    @property
    def client(self):
        if self._client is None:
            self._client = _lazy_chroma()
        return self._client

    def _col(self, name: str):
        return self.client.get_or_create_collection(f"{self.prefix}_{name}")

    # ─────────────── 检索 ───────────────
    async def vector_search(self, query: str, top_k: int | None = None,
                            collection: str | None = None) -> list[dict]:
        top_k = top_k or self.vector_k
        emb = (await self.embedder.embed([query]))[0]
        cols = ([collection] if collection
                else self._all_collections())
        hits = []
        for c in cols:
            try:
                col = self._col(c)
                res = col.query(query_embeddings=[emb], n_results=top_k,
                                include=["documents", "metadatas", "distances"])
            except Exception:
                continue
            for i, doc in enumerate(res["documents"][0]):
                dist = res["distances"][0][i]
                hits.append({
                    "text": doc,
                    "source": (res["metadatas"][0][i] or {}).get("source", c),
                    "collection": c,
                    "score": max(0.0, 1.0 - dist),
                })
        return sorted(hits, key=lambda h: h["score"], reverse=True)[:top_k]

    def _all_collections(self) -> list[str]:
        names = []
        for c in self.client.list_collections():
            cname = c.name if hasattr(c, "name") else c
            if cname.startswith(self.prefix + "_"):
                names.append(cname.replace(self.prefix + "_", ""))
        return names

    def _build_bm25(self, collection: str | None) -> tuple[Any, list[dict]]:
        key = collection or "__all__"
        if key in self._bm25_cache:
            return self._bm25_cache[key]
        docs = []
        for c in ([collection] if collection else self._all_collections()):
            try:
                col = self._col(c)
                data = col.get(include=["documents", "metadatas"])
            except Exception:
                continue
            for i, doc in enumerate(data["documents"]):
                docs.append({"text": doc,
                             "source": (data["metadatas"][i] or {}).get("source", c),
                             "collection": c})
        tokenized = [list(jieba.cut(d["text"])) for d in docs]
        bm25 = BM25Okapi(tokenized) if tokenized else None
        self._bm25_cache[key] = (bm25, docs)
        return bm25, docs

    async def bm25_search(self, query: str, top_k: int | None = None,
                          collection: str | None = None) -> list[dict]:
        top_k = top_k or self.bm25_k
        bm25, docs = await asyncio.to_thread(self._build_bm25, collection)
        if not bm25 or not docs:
            return []
        scores = bm25.get_scores(list(jieba.cut(query)))
        order = np.argsort(scores)[::-1][:top_k]
        return [{"text": docs[i]["text"], "source": docs[i]["source"],
                 "collection": docs[i]["collection"],
                 "score": float(scores[i])} for i in order if scores[i] > 0]

    async def hybrid_search(self, query: str,
                            collections: list[str] | str | None = None,
                            top_k: int | None = None) -> list[dict]:
        """混合检索主入口。collections 支持单个或列表。"""
        top_k = top_k or self.final_k
        cols = None
        if isinstance(collections, str):
            cols = collections
        elif isinstance(collections, list) and len(collections) == 1:
            cols = collections[0]

        with RAG_DURATION.time():
            if isinstance(collections, list) and len(collections) > 1:
                # 多 collection：分别检索后合并
                v_hits, b_hits = [], []
                for c in collections:
                    v_hits += await self.vector_search(query, self.vector_k, c)
                    b_hits += await self.bm25_search(query, self.bm25_k, c)
            else:
                v_hits = await self.vector_search(query, self.vector_k, cols)
                b_hits = await self.bm25_search(query, self.bm25_k, cols)

        # 归一化 + 加权融合
        def _norm(hits):
            if not hits:
                return {}
            mx = max(h["score"] for h in hits) or 1.0
            return {(h["source"], h["text"][:64]):
                    {**h, "score": h["score"] / mx} for h in hits}
        vn, bn = _norm(v_hits), _norm(b_hits)
        merged: dict[str, dict] = {}
        for k, h in vn.items():
            merged[k] = {**h, "score": h["score"] * self.vector_weight}
        for k, h in bn.items():
            if k in merged:
                merged[k]["score"] += h["score"] * (1 - self.vector_weight)
            else:
                merged[k] = {**h, "score": h["score"] * (1 - self.vector_weight)}
        candidates = list(merged.values())

        # Rerank → Top-K
        final = await asyncio.to_thread(
            self.reranker.rerank, query, candidates, top_k)
        return final

    # ─────────────── 入库 ───────────────
    async def add_documents(self, collection: str, texts: list[str],
                            metadatas: list[dict], ids: list[str]) -> None:
        embs = await self.embedder.embed(texts)
        col = self._col(collection)
        await asyncio.to_thread(col.upsert, embeddings=embs, documents=texts,
                                metadatas=metadatas, ids=ids)
        self._bm25_cache.pop(collection, None)
        self._bm25_cache.pop("__all__", None)

    def delete_by_source(self, collection: str, source: str) -> None:
        col = self._col(collection)
        col.delete(where={"source": source})
        self._bm25_cache.pop(collection, None)
        self._bm25_cache.pop("__all__", None)


rag_engine = RAGEngine()