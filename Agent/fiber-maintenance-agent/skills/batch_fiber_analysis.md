
---
name: batch_fiber_analysis
description: 批量光纤分析策略
version: "1.0"
triggers: [批量, 所有, 全部, 紧急告警光纤]
tools_required: [colored_fibers_query, all_colored_fibers_query, fiber_spanloss_query, fiber_performance_query]
output_format: markdown
---
# 批量光纤分析技能

## 触发条件

用户要求分析"所有告警光纤"、"批量分析"、"全部红色连纤"。

## 执行策略

### Step 1: 获取目标列表

- 紧急：`colored_fibers_query(color="RED")`
- 全部：`all_colored_fibers_query()`
- 上限：100 条/次，超出分批

### Step 2: 并行分析

- Lead Agent 通过 task tool 并行派遣（max 5 并发）
- FIFO 排队
- 每条光纤独立分析，失败不影响其他
- 单条超时 15s

### Step 3: 汇总报告

- 成功/失败统计
- 按严重程度排序（红→黄→绿）
- 共性问题归纳
- 优先处理建议

## 输出模板
### 批量分析报告
### 概览
- 分析总数:{total} | 成功: {success} | 失败: {failed}
- 🔴 {red} | 🟡 {yellow} | 🟢 {green}

### 紧急处理清单

| 优先级 | 光纤 | 问题 | 建议 |
|------|------|----------|----------|

### 共性问题
{归纳}

#### 失败条目

| 光纤 | 原因 |
|------|------|


## 异常处理
- 单条超时 → 记录失败原因，继续其他
- 全部失败 → 提示后端可能不可用