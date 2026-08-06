"""数字模板填充 + 幻觉校验测试。"""
import pytest

from src.governance.number_validator import (
    extract_numbers,
    validate_narration_numbers,
    fill_template,
)


class TestExtractNumbers:
    def test_extract_db_values(self):
        text = "衰耗为3.2dB，阈值5.0dB"
        nums = extract_numbers(text)
        assert 3.2 in nums
        assert 5.0 in nums

    def test_extract_negative(self):
        text = "OOP为-8.5dBm"
        nums = extract_numbers(text)
        assert -8.5 in nums

    def test_extract_integer(self):
        text = "光纤3有2条告警"
        nums = extract_numbers(text)
        assert 3 in nums
        assert 2 in nums

    def test_empty_text(self):
        assert extract_numbers("没有数字") == []


class TestValidateNarration:
    def test_valid_narration(self):
        source_data = {"spanloss": 3.2, "threshold": 5.0, "fiber_id": 3}
        narration = "光纤3的衰耗为3.2dB，低于阈值5.0dB"
        errors = validate_narration_numbers(narration, source_data)
        assert errors == []

    def test_hallucinated_number(self):
        source_data = {"spanloss": 3.2, "threshold": 5.0}
        narration = "衰耗为12.5dB，严重超标"
        errors = validate_narration_numbers(narration, source_data)
        assert len(errors) > 0
        assert any("12.5" in e for e in errors)

    def test_empty_source_allows_common_numbers(self):
        source_data = {}
        narration = "共100条光纤"
        errors = validate_narration_numbers(narration, source_data)
        assert errors == []

    def test_list_values_in_source(self):
        source_data = {"fiber_ids": [1, 2, 3], "spanloss": 4.5}
        narration = "光纤1的衰耗为4.5dB"
        errors = validate_narration_numbers(narration, source_data)
        assert errors == []


class TestFillTemplate:
    def test_basic_fill(self):
        template = "光纤{fiber_id}的衰耗为{spanloss}dB，状态{status}。"
        data = {"fiber_id": 3, "spanloss": 3.2, "status": "正常"}
        result = fill_template(template, data)
        assert result == "光纤3的衰耗为3.2dB，状态正常。"

    def test_missing_key_kept(self):
        template = "光纤{fiber_id}的衰耗为{spanloss}dB"
        data = {"fiber_id": 3}
        result = fill_template(template, data)
        assert "{spanloss}" in result
        assert "3" in result
