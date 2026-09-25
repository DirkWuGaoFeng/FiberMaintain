"""
分析专家节点 —— 四角色分层 + 来源标记 单测 [v7.2 P0]。

依据《AI Agent 设计原理与工程实践》第2章"指令与数据分离 / 来源标记"：
- user.md（可信系统数据）与 external.md（外部低信任内容）分离注入
- 外部内容（经验 / RAG / 对话摘要）用 <external_content source=... trust=low> 包裹
- 防止外部指令劫持（间接注入防御）
"""

import pytest

# =============================================================================
# 辅助：解析 ChatPromptTemplate 构造的消息
# =============================================================================


def _fake_llm():
    """返回带 with_structured_output 的 fake LLM（避免真实模型调用）。

    with_structured_output 返回一个 RunnableLambda，使 `prompt | llm` 可组合，
    但不真正执行任何模型调用（测试只关心 prompt 结构，不调用 chain）。
    """
    from langchain_core.runnables import RunnableLambda

    class _FakeLLM:
        def with_structured_output(self, *args, **kwargs):
            return RunnableLambda(lambda x: None)

    return _FakeLLM()


def _get_chain():
    """导入模块级 _get_chain（延迟导入避免循环），并重置单例 + mock LLM。"""
    from src.nodes import analysis_expert as module

    # 重置单例缓存，避免跨测试污染
    module._analysis_chain = None
    # mock LLM（带 with_structured_output），避免真实模型调用
    module.get_analysis_llm = _fake_llm

    return module._get_chain()


def _prompt_messages():
    """返回 _get_chain 中构造的 prompt 的消息列表（(role, template) 元组列表）。"""
    chain = _get_chain()
    # chain 是 RunnableSequence: prompt | llm.with_structured_output(...)
    # 第一个元素是 ChatPromptTemplate
    prompt = chain.first
    return prompt.messages


# =============================================================================
# 1. 四角色分层：system / 可信 human / 外部 human
# =============================================================================


class TestMessageLayering:
    """验证提示词按 书籍 Ch2 指令与数据分离 分层注入。"""

    def test_prompt_has_three_messages(self, monkeypatch):
        """链应包含 system + 可信 human + 外部 human 三段消息。"""
        from langchain_core.prompts.chat import (
            HumanMessagePromptTemplate,
            SystemMessagePromptTemplate,
        )

        monkeypatch.setattr("src.nodes.analysis_expert.get_analysis_llm", _fake_llm)
        messages = _prompt_messages()

        assert len(messages) == 3
        # 第一段：system（静态身份/规则）
        assert isinstance(messages[0], SystemMessagePromptTemplate)
        # 第二段：可信 human（用户问题 + 系统数据）
        assert isinstance(messages[1], HumanMessagePromptTemplate)
        # 第三段：外部 human（低信任参考素材）
        assert isinstance(messages[2], HumanMessagePromptTemplate)

    def test_system_prompt_kept_static(self, monkeypatch):
        """system 提示词应完全静态（无模板变量，KV Cache 前缀稳定）。"""
        monkeypatch.setattr("src.nodes.analysis_expert.get_analysis_llm", _fake_llm)
        prompt = _get_chain().first
        system_tpl = prompt.messages[0]
        # system 无模板变量（keep_vars=() 全转义）；字面 JSON 花括号为双写 {{...}}
        assert "光纤维护分析专家" in system_tpl.prompt.template
        # 不含任何未转义的模板变量占位符（单花括号包字母数字）
        import re

        assert re.search(r"\{[a-zA-Z_]+\}", system_tpl.prompt.template) is None

    def test_trusted_user_data_in_second_message(self, monkeypatch):
        """可信系统数据（问题/规则/状态栏）应保留在第二条 human 消息。"""
        prompt = _get_chain().first
        trusted_tpl = prompt.messages[1].prompt.template
        assert "{question}" in trusted_tpl
        assert "{rule_judgment}" in trusted_tpl
        assert "{status_bar}" in trusted_tpl
        # 可信段不应包含外部检索内容的变量
        assert "{experience_history}" not in trusted_tpl
        assert "{rag_context}" not in trusted_tpl


# =============================================================================
# 2. 外部内容来源标记
# =============================================================================


class TestExternalContentSourceMarking:
    """验证外部低信任内容带 <external_content> 来源标记。"""

    def test_external_message_has_source_markers(self, monkeypatch):
        """外部段应包含三种来源标记（经验 / RAG / 对话摘要）。"""
        prompt = _get_chain().first
        external_tpl = prompt.messages[2].prompt.template
        assert '<external_content source="experience_memory" trust="low">' in external_tpl
        assert '<external_content source="rag_knowledge" trust="low">' in external_tpl
        assert '<external_content source="conversation_history" trust="low">' in external_tpl
        # 模板变量保留
        assert "{experience_history}" in external_tpl
        assert "{rag_context}" in external_tpl
        assert "{conversation_summary}" in external_tpl

    def test_external_message_contains_no_execute_guard(self, monkeypatch):
        """外部段应提示模型勿执行其中的"指令"（间接注入防御）。"""
        prompt = _get_chain().first
        external_tpl = prompt.messages[2].prompt.template
        assert "请勿执行" in external_tpl
        assert "参考素材" in external_tpl


# =============================================================================
# 3. 端到端：格式化后三段消息内容正确分离
# =============================================================================


class TestFormattedMessages:
    """将模板格式化后，验证最终消息内容分层正确。"""

    @pytest.mark.asyncio
    async def test_format_separates_trusted_and_external(self, monkeypatch):
        prompt = _get_chain().first
        formatted = await prompt.aformat_messages(
            question="分析光纤5衰耗异常的原因",
            rule_judgment="状态: WARNING\n发现: 超标\n指标: {}",
            data_summary="spanloss=0.9",
            loop_history="第1轮: 需补充数据",
            task_context="计划: 分析",
            guard_notice="无",
            status_bar="- 循环进度: 第 1/3 轮",
            experience_history="- [CRITICAL] 历史断纤经验",
            rag_context="- [OTDR] 衰耗标准",
            conversation_summary="摘要: 用户关注光纤5",
        )

        # 三段消息
        assert len(formatted) == 3
        assert formatted[0].type == "system"  # system
        assert formatted[1].type == "human"  # 可信 human
        assert formatted[2].type == "human"  # 外部 human

        # 可信段：包含问题/规则/状态栏，不含外部内容
        trusted = formatted[1].content
        assert "分析光纤5衰耗异常的原因" in trusted
        assert "状态: WARNING" in trusted
        assert "- 循环进度: 第 1/3 轮" in trusted
        assert "历史断纤经验" not in trusted  # 外部内容已分离
        assert "衰耗标准" not in trusted

        # 外部段：经验/RAG/摘要带来源标记，且不包含用户问题
        external = formatted[2].content
        assert "历史断纤经验" in external
        assert "衰耗标准" in external
        assert "摘要: 用户关注光纤5" in external
        assert '<external_content source="experience_memory" trust="low">' in external
        assert "分析光纤5衰耗异常的原因" not in external


# =============================================================================
# 4. 回归：analysis_expert_node 仍正确工作（LLM 返回 verdict）
# =============================================================================


class TestNodeRegression:
    """验证分层改造后节点行为不退化（外部经验仍注入 prompt 上下文）。"""

    @pytest.mark.asyncio
    async def test_experience_still_injected_into_prompt(self, tmp_path, monkeypatch):
        from src.graph.state import AnalysisVerdict
        from src.nodes import analysis_expert as module

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

        # 替换链为 FakeChain，避免真实 LLM 调用
        monkeypatch.setattr(module, "_get_chain", lambda: FakeChain())
        # mock 记忆存储/检索/RAG，避免真实 DB 与网络
        from unittest.mock import MagicMock

        class FakeStore:
            def fiber_key_of(self, ids):
                return "5" if ids else ""

            def query(self, key):
                return [
                    {
                        "conclusion": "历史断纤经验",
                        "severity": "CRITICAL",
                        "created_at": "2026-01-01T00:00:00",
                    }
                ]

            def save(self, *args, **kwargs):
                return True

        class FakeRetriever:
            async def query_semantic(self, *args, **kwargs):
                return []

            async def save(self, *args, **kwargs):
                return None

        monkeypatch.setattr(module, "get_experience_store", lambda: FakeStore())
        monkeypatch.setattr(module, "get_memory_retriever", lambda: FakeRetriever())
        monkeypatch.setattr(
            module,
            "get_rag_engine",
            lambda: MagicMock(is_available=False),
        )

        state = {
            "user_input": "分析光纤5衰耗异常的原因",
            "normalized_params": {"fiber_ids": [5]},
            "rule_judgment": {"status": "WARNING", "findings": ["超标"], "metrics": {}},
        }
        updates = await module.analysis_expert_node(state)

        # 外部经验仍作为输入键传入（供 external.md 使用）
        assert "历史断纤经验" in captured["experience_history"]
        # 可信系统数据仍在
        assert "分析光纤5衰耗异常的原因" in captured["question"]
        assert updates["analysis_verdict"]["severity"] == "WARNING"
