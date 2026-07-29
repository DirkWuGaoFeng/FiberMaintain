"""Phase 5: context_budget + fallback 单元测试。

测试覆盖:
- TokenEstimator: 中英文/JSON 估算
- BudgetConfig: 弹性区计算/校验
- ContextBudget: 全量分配/超限降级(P3→P2→P1)
- FallbackEngine: L1~L4 降级切换
- RuleEngine: scene_1/scene_2b 规则处理
- RateLimitMiddleware: 令牌桶限流
- CircuitBreaker (MCP): 熔断/半开/恢复
"""
import pytest
from src.agents.context_budget import (
    TokenEstimator, BudgetConfig, ContextBudget, BudgetAllocation,
    get_budget,
)
from src.agents.fallback import (
    FallbackEngine, FallbackContext, RuleEngine, RuleResult,
)
from src.middlewares.rate_limit import TokenBucket, RateLimitMiddleware


# ============================================================
#  TokenEstimator
# ============================================================

class TestTokenEstimator:
    def test_chinese_text(self):
        est = TokenEstimator()
        # 10 个中文字符 ≈ 15 tokens
        tokens = est.estimate("这是一个测试用例数据")
        assert 10 <= tokens <= 20

    def test_english_text(self):
        est = TokenEstimator()
        # 5 English words ≈ 5 tokens
        tokens = est.estimate("hello world test data value")
        assert 3 <= tokens <= 10

    def test_json_object(self):
        est = TokenEstimator()
        data = {"fiber_id": 1, "spanloss": 5.2, "color": "green"}
        tokens = est.estimate(data)
        assert tokens > 0

    def test_empty_string(self):
        est = TokenEstimator()
        assert est.estimate("") == 0

    def test_json_list(self):
        est = TokenEstimator()
        data = [1, 2, 3, 4, 5]
        tokens = est.estimate(data)
        assert tokens > 0


# ============================================================
#  BudgetConfig
# ============================================================

class TestBudgetConfig:
    def test_default_elastic(self):
        cfg = BudgetConfig(total=8192, fixed=1300, output_reserve=2000)
        assert cfg.elastic == 4892

    def test_validate_ok(self):
        cfg = BudgetConfig(p1_data=3000, p2_rag=1000, p3_memory=500)
        assert cfg.validate() is True

    def test_validate_overflow(self):
        cfg = BudgetConfig(total=8192, fixed=1300, output_reserve=2000,
                           p1_data=4000, p2_rag=1000, p3_memory=500)
        assert cfg.validate() is False

    def test_agent_budgets_exist(self):
        for name in ["lead", "data-collector", "analysis-expert",
                      "knowledge-assistant", "report-generator"]:
            budget = get_budget(name)
            assert budget.total == 8192


# ============================================================
#  ContextBudget — 正常分配
# ============================================================

class TestContextBudgetNormal:
    def test_no_overflow(self):
        cfg = BudgetConfig(total=8192, fixed=1300, output_reserve=2000,
                           p1_data=3000, p2_rag=1000, p3_memory=500)
        budget = ContextBudget(cfg)

        data = [{"value": i} for i in range(5)]
        rag = [{"content": f"知识片段{i}"} for i in range(2)]
        mem = [{"content": f"记忆{i}"} for i in range(2)]

        alloc = budget.allocate(data, rag, mem)
        assert alloc.overflow is False
        assert len(alloc.data_items) == 5
        assert len(alloc.rag_items) == 2
        assert len(alloc.memory_items) == 2


# ============================================================
#  ContextBudget — 超限降级
# ============================================================

class TestContextBudgetOverflow:
    def _make_large_items(self, count: int, size: int = 200) -> list[str]:
        return ["X" * size for _ in range(count)]

    def test_p3_degrades_first(self):
        cfg = BudgetConfig(total=8192, fixed=1300, output_reserve=2000,
                           p1_data=3000, p2_rag=1000, p3_memory=500)
        budget = ContextBudget(cfg)

        # 大量记忆项（远超 p3_memory=500）
        mem = [{"content": "A" * 1000} for _ in range(20)]
        data = [{"v": i} for i in range(3)]
        rag = [{"content": f"RAG{i}"} for i in range(2)]

        alloc = budget.allocate(data, rag, mem)
        # 应该触发 P3 降级
        assert alloc.overflow is True
        assert len(alloc.memory_items) <= 3
        assert len(alloc.degradation_log) > 0

    def test_p2_degrades_when_p3_insufficient(self):
        cfg = BudgetConfig(total=8192, fixed=1300, output_reserve=2000,
                           p1_data=3000, p2_rag=1000, p3_memory=500)
        budget = ContextBudget(cfg)

        # 大量 RAG 项（远超 p2_rag=1000）
        rag = [{"content": "B" * 1000} for _ in range(30)]
        data = [{"v": 1}]
        mem = []

        alloc = budget.allocate(data, rag, mem)
        assert alloc.overflow is True
        assert len(alloc.rag_items) <= 3


# ============================================================
#  FallbackEngine
# ============================================================

class TestFallbackEngine:
    def test_l1_normal(self):
        engine = FallbackEngine()
        ctx = FallbackContext(llm_available=True, backend_available=True)
        assert engine.decide_level(ctx) == 0

    def test_l2_model_degradation(self):
        engine = FallbackEngine()
        ctx = FallbackContext(llm_available=True, backend_available=False)
        assert engine.decide_level(ctx) == 1

    def test_l3_rule_fallback(self):
        engine = FallbackEngine()
        ctx = FallbackContext(llm_available=False, backend_available=True)
        assert engine.decide_level(ctx) == 2

    def test_l4_knowledge_mode(self):
        engine = FallbackEngine()
        ctx = FallbackContext(llm_available=False, backend_available=False)
        assert engine.decide_level(ctx) == 3

    @pytest.mark.asyncio
    async def test_l3_rule_scene1(self):
        engine = FallbackEngine()
        context = {
            "fiber_id": 123,
            "performance": {"src_oop": -10.5, "dst_iop": -15.3, "spanloss": 5.2},
            "backend_available": True,
            "llm_available": False,
        }
        level, resp, meta = await engine.handle("scene_1", "查询光纤123",
                                                  context=context)
        assert level == 2
        assert "F123" in resp
        assert meta["fallback"] is True

    @pytest.mark.asyncio
    async def test_l3_rule_scene2b(self):
        engine = FallbackEngine()
        context = {
            "fiber_id": 456,
            "spanloss": 12.5,
            "backend_available": True,
            "llm_available": False,
        }
        level, resp, meta = await engine.handle("scene_2b", "颜色判定",
                                                  context=context)
        assert level == 2
        assert "橙色" in resp or "orange" in resp.lower()

    @pytest.mark.asyncio
    async def test_l4_knowledge_with_snippets(self):
        engine = FallbackEngine()
        context = {"backend_available": False, "llm_available": False}
        snippets = [
            {"content": "衰耗超过15dB为红色紧急状态", "source": "阈值标准"},
            {"content": "建议立即派遣维护人员", "source": "维护规范"},
        ]
        level, resp, meta = await engine.handle(
            "scene_3", "分析", context=context, knowledge_snippets=snippets)
        assert level == 3
        assert "知识模式" in resp
        assert meta["snippet_count"] == 2


# ============================================================
#  RuleEngine
# ============================================================

class TestRuleEngine:
    def test_scene1_normal(self):
        engine = RuleEngine()
        result = engine.try_handle("scene_1", {
            "fiber_id": 1,
            "performance": {"src_oop": -10.0, "dst_iop": -15.0, "spanloss": 3.0},
        })
        assert result.handled is True
        assert "正常" in result.response

    def test_scene1_abnormal(self):
        engine = RuleEngine()
        result = engine.try_handle("scene_1", {
            "fiber_id": 2,
            "performance": {"src_oop": -35.0, "dst_iop": -15.0, "spanloss": 20.0},
        })
        assert result.handled is True
        assert "异常" in result.response
        assert len(result.data["issues"]) > 0

    def test_scene2b_green(self):
        engine = RuleEngine()
        result = engine.try_handle("scene_2b", {
            "fiber_id": 3, "spanloss": 2.0})
        assert result.handled is True
        assert result.data["color"] == "green"

    def test_scene2b_red(self):
        engine = RuleEngine()
        result = engine.try_handle("scene_2b", {
            "fiber_id": 4, "spanloss": 20.0})
        assert result.handled is True
        assert result.data["color"] == "red"

    def test_unknown_scene(self):
        engine = RuleEngine()
        result = engine.try_handle("unknown_scene", {})
        assert result.handled is False


# ============================================================
#  TokenBucket
# ============================================================

class TestTokenBucket:
    def test_initial_burst(self):
        bucket = TokenBucket(rate=10 / 60.0, burst=20)
        # 初始 burst=20，应该能消费
        assert bucket.consume() is True

    def test_exhaustion(self):
        bucket = TokenBucket(rate=0.001, burst=2)
        assert bucket.consume() is True
        assert bucket.consume() is True
        # 第三个应该失败
        assert bucket.consume() is False


# ============================================================
#  MCP CircuitBreaker (import from fiber_backend)
# ============================================================

class TestMCPCircuitBreaker:
    def test_initial_closed(self):
        from src.mcp.fiber_backend import CircuitBreaker
        cb = CircuitBreaker(threshold=3, cooldown=1.0)
        assert cb.state == CircuitBreaker.CLOSED
        assert cb.allow_request() is True

    def test_open_after_threshold(self):
        from src.mcp.fiber_backend import CircuitBreaker
        cb = CircuitBreaker(threshold=3, cooldown=1.0)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN
        assert cb.allow_request() is False

    def test_half_open_after_cooldown(self):
        from src.mcp.fiber_backend import CircuitBreaker
        import time
        cb = CircuitBreaker(threshold=2, cooldown=0.5)
        for _ in range(2):
            cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN
        time.sleep(0.6)
        assert cb.state == CircuitBreaker.HALF_OPEN
        assert cb.allow_request() is True

    def test_recovery_on_success(self):
        from src.mcp.fiber_backend import CircuitBreaker
        import time
        cb = CircuitBreaker(threshold=2, cooldown=0.5)
        for _ in range(2):
            cb.record_failure()
        time.sleep(0.6)
        # 确认进入半开状态
        assert cb.state == CircuitBreaker.HALF_OPEN
        # 半开状态下成功 → 恢复关闭
        cb.record_success()
        assert cb.state == CircuitBreaker.CLOSED
