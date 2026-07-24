
---
name: fiber_spanloss_analysis
description: 光纤衰耗分析完整流程
version: "1.0"
triggers: [衰耗, 光功率, spanloss, OOP, IOP, dB]
tools_required: [fiber_performance_query, fiber_spanloss_query, rag_query]
output_format: markdown
---
# 光纤衰耗分析技能

## 触发条件

用户询问光纤衰耗、光功率、OOP/IOP 相关问题。

## 执行步骤

### Step 1: 获取光纤性能数据

- 调用 `fiber_performance_query(fiber_id)` → 获取 OOP / IOP（dBm）
- 调用 `fiber_spanloss_query(fiber_id)` → 获取后端计算的衰耗值（dB）

### Step 2: 阈值判断（参考知识库）

| 光纤类型   | 波长   | 正常        | 告警 | 紧急 |
| ---------- | ------ | ----------- | ---- | ---- |
| G.652 单模 | 1310nm | ≤0.4 dB/km | >0.5 | >0.8 |
| G.652 单模 | 1550nm | ≤0.3 dB/km | >0.4 | >0.6 |
| G.655 单模 | 1550nm | ≤0.3 dB/km | >0.4 | >0.6 |
| G.651 多模 | 850nm  | ≤3.5 dB/km | >4.0 | >5.0 |

链路总衰耗判定：

| 链路长度 | 正常    | 关注  | 告警 |
| -------- | ------- | ----- | ---- |
| ≤10km   | ≤4 dB  | 4~6   | >6   |
| 10~40km  | ≤12 dB | 12~16 | >16  |
| 40~80km  | ≤22 dB | 22~28 | >28  |
| >80km    | ≤30 dB | 30~35 | >35  |

### Step 3: 状态判定

- 🟢 正常：衰耗在正常范围内
- 🟡 关注：超正常范围但未达告警阈值
- 🔴 异常：超告警阈值

### Step 4: 生成维护建议

- 调用 `rag_query` 检索维护规范
- 引用具体条款编号

## 输出模板

### 光纤 F 衰耗分析

| 指标     | 值             | 状态     |
| -------- | -------------- | -------- |
| 源端 OOP | {oop} dBm      | {status} |
| 宿端 IOP | {iop} dBm      | {status} |
| 衰耗值   | {spanloss} dB  | {status} |
| 阈值     | {threshold} dB | —       |

结论: {conclusion}
建议: {suggestion}
参考: {rag_reference}

## 异常处理
- 性能数据缺失 → 提示"暂无性能数据，请确认采集是否正常"
- 衰耗查询超时 → 重试 1 次，仍失败则提示用户
- fiber_id 不存在 → 提示"未找到该光纤，请确认 ID"