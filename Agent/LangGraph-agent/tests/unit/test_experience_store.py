"""
Unit tests for Experience Store [改进清单 P1-A].

Tests:
- Deterministic save rules (WARNING/CRITICAL only, non-empty fiber key)
- Color-change-style dedup (same severity skipped, severity change written)
- Query recency/limit and fiber_key normalization
- analysis_expert deterministic write + prompt injection (LLM mocked)
"""

import pytest

from src.memory.experience_store import ExperienceStore


@pytest.fixture
def store(tmp_path):
    return ExperienceStore(db_path=str(tmp_path / "memory.db"))


class TestExperienceStore:
    def test_save_warning(self, store):
        assert store.save("5", "WARNING", "衰耗超阈值", ["spanloss=0.85"]) is True
        records = store.query("5")
        assert len(records) == 1
        assert records[0]["severity"] == "WARNING"
        assert records[0]["conclusion"] == "衰耗超阈值"

    def test_dedup_same_severity(self, store):
        assert store.save("5", "WARNING", "第一次") is True
        assert store.save("5", "WARNING", "重复告警") is False
        assert len(store.query("5")) == 1

    def test_severity_change_written(self, store):
        assert store.save("5", "WARNING", "升级前") is True
        assert store.save("5", "CRITICAL", "升级为严重") is True
        assert len(store.query("5")) == 2
        assert store.latest_severity("5") == "CRITICAL"

    def test_normal_severity_rejected(self, store):
        assert store.save("5", "NORMAL", "正常不写") is False
        assert store.query("5") == []

    def test_empty_fiber_key_rejected(self, store):
        assert store.save("", "CRITICAL", "无光纤标识") is False

    def test_fiber_key_of(self, store):
        assert store.fiber_key_of([3]) == "3"
        assert store.fiber_key_of([1, 2, 3]) == "1,2,3"
        assert store.fiber_key_of([]) == ""
        assert store.fiber_key_of(None) == ""
        # capped at 5 ids
        assert store.fiber_key_of(list(range(10))) == "0,1,2,3,4"

    def test_query_empty_key(self, store):
        assert store.query("") == []
        assert store.latest_severity("") is None


class TestAnalysisExpertDeterministicMemory:
    """analysis_expert writes experience deterministically (no LLM agency)."""

    @pytest.mark.asyncio
    async def test_warning_verdict_persisted_and_experience_injected(
        self, tmp_path, monkeypatch
    ):
        from src.graph.state import AnalysisVerdict
        from src.nodes import analysis_expert as module

        store = ExperienceStore(db_path=str(tmp_path / "memory.db"))
        # Pre-existing experience must be injected into the prompt context
        store.save("5", "CRITICAL", "历史断纤经验")

        captured: dict = {}

        class FakeChain:
            async def ainvoke(self, inputs):
                captured.update(inputs)
                return AnalysisVerdict(
                    conclusion="衰耗超标需检修",
                    severity="WARNING",
                    evidence=["spanloss=0.9"],
                    confidence=0.9,
                    need_more_data=False,
                )

        monkeypatch.setattr(module, "_get_chain", lambda: FakeChain())
        monkeypatch.setattr(module, "get_experience_store", lambda: store)

        state = {
            "user_input": "分析光纤5衰耗异常的原因",
            "normalized_params": {"fiber_ids": [5]},
            "rule_judgment": {"status": "WARNING", "findings": ["超标"], "metrics": {}},
        }
        updates = await module.analysis_expert_node(state)

        # Deterministic write happened
        records = store.query("5")
        assert any(r["conclusion"] == "衰耗超标需检修" for r in records)
        # Historical experience injected into prompt context
        assert "历史断纤经验" in captured["experience_history"]
        assert updates["analysis_verdict"]["severity"] == "WARNING"

    @pytest.mark.asyncio
    async def test_normal_verdict_not_persisted(self, tmp_path, monkeypatch):
        from src.graph.state import AnalysisVerdict
        from src.nodes import analysis_expert as module

        store = ExperienceStore(db_path=str(tmp_path / "memory.db"))

        class FakeChain:
            async def ainvoke(self, inputs):
                return AnalysisVerdict(
                    conclusion="一切正常",
                    severity="NORMAL",
                    evidence=[],
                    confidence=0.95,
                    need_more_data=False,
                )

        monkeypatch.setattr(module, "_get_chain", lambda: FakeChain())
        monkeypatch.setattr(module, "get_experience_store", lambda: store)

        state = {
            "user_input": "分析光纤5",
            "normalized_params": {"fiber_ids": [5]},
        }
        await module.analysis_expert_node(state)
        assert store.query("5") == []
