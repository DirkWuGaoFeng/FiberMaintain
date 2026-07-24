
---
name: fiber_trend_analysis
description: 光纤趋势分析与异常检测
version: "1.0"
triggers: [趋势, 变化, 统计, 历史, 走势, 对比]
tools_required: [fiber_trend_query, fiber_stats_query, memory_query]
output_format: markdown
---
# 光纤趋势分析技能

## 触发条件

用户询问趋势、变化、统计、历史对比。

## 执行步骤

### Step 1: 获取趋势数据

- `fiber_trend_query(start_time, end_time)`
- 支持：1h / 6h / 24h / 7d / 30d
- 粒度：5 分钟

### Step 2: 获取实时统计

- `fiber_stats_query()` → 当前红/黄数量

### Step 3: 对比分析（如需要）

- 纵向：`memory_query(fiber_id, time_range)` → 历史分析结果
- 横向：同网元对下多条连纤对比

### Step 4: 异常检测

- 突增：短时间内红色数量急剧增加
- 趋势预警：黄色持续增加
- 周期：是否存在周期性波动

### Step 5: 生成报告 + 预测建议

## 输出模板

### 光纤趋势分析 ({time_range})
### 当前状态
- 🔴 {red} | 🟡 {yellow} | 总计 {total}
### 趋势概要
- 红色峰值: {max_red} @ {time}
- 变化趋势: {上升/下降/平稳}
### 对比分析（如有）
| 时间 | 衰耗 | 变化 |
|------|------|------|
### 异常事件
| 时间 | 事件 | 影响 |
|------|------|------|

### 建议
{基于趋势的维护建议}


## 异常处理
- 趋势数据为空 → 提示"该时间范围内无数据"
- 时间范围无效 → 提示正确格式