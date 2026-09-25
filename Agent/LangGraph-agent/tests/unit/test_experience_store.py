"""
体验库（Experience Store）单元测试 [改进清单 P1-A]。

测试：
- 确定性保存规则（仅 WARNING/CRITICAL，非空光纤键）
- 变色式去重（同严重度跳过，严重度变化写入）
- 查询时效性/条数限制与 fiber_key 归一化
- analysis_expert 确定性写入 + prompt 注入（LLM 已 mock）
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
        # 最多保留 5 个 id
        assert store.fiber_key_of(list(range(10))) == "0,1,2,3,4"

    def test_query_empty_key(self, store):
        assert store.query("") == []
        assert store.latest_severity("") is None


class TestQualityVeto:
    """经验质量门禁（书籍 Ch3：保存≠学习，坏经验拒绝入库）。"""

    def test_grounded_numbers_written(self, store):
        # 结论数字可溯源到 evidence → 写入
        assert store.save("5", "WARNING", "衰耗0.85dB需关注", ["spanloss=0.85"]) is True
        assert len(store.query("5")) == 1

    def test_hallucinated_number_vetoed(self, store):
        # 结论数字无法溯源到 evidence → 拒绝写入
        assert store.save("5", "WARNING", "衰耗0.88dB需关注", ["spanloss=0.85"]) is False
        assert store.query("5") == []

    def test_fiber_id_not_vetoed(self, store):
        # 光纤 ID（良性数字 0-31）不触发 veto
        assert store.save("5", "CRITICAL", "光纤5断纤", ["fiber_id=5"]) is True


class TestAnalysisExpertDeterministicMemory:
    """analysis_expert 确定性写入经验（无 LLM 自主性）。"""

    @pytest.mark.asyncio
    async def test_warning_verdict_persisted_and_experience_injected(self, tmp_path, monkeypatch):
        from src.graph.state import AnalysisVerdict
        from src.nodes import analysis_expert as module

        store = ExperienceStore(db_path=str(tmp_path / "memory.db"))
        # 已有经验必须注入提示词上下文
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

        # 发生了确定性写入
        records = store.query("5")
        assert any(r["conclusion"] == "衰耗超标需检修" for r in records)
        # 历史经验被注入 prompt 上下文
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
