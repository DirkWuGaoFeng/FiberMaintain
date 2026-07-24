---
name: fiber_color_diagnosis
description: 光纤颜色诊断与告警处理
version: "1.0"
triggers: [颜色, 红色, 黄色, 告警, 中断, 紧急]
tools_required: [colored_fibers_query, alarm_query, fiber_performance_query, fiber_spanloss_query]
output_format: markdown
---

# 光纤颜色诊断技能

## 颜色含义

| 颜色 | 含义 | 紧急程度 | 响应时间 |
|------|------|----------|----------|
| 🟢 绿色 | 正常 | — | — |
| 🟡 黄色 | 次要告警/性能劣化 | 关注 | ≤4h |
| 🔴 红色 | 紧急告警/链路中断 | 立即 | ≤15min |

## 执行步骤

### Step 1: 获取颜色状态
- `colored_fibers_query(color="RED")` → 红色连纤列表
- `colored_fibers_query(color="YELLOW")` → 黄色连纤列表
- 后端返回 scene_type + scenario_case（Agent 仅展示，不做判定）

### Step 2: 获取关联告警
- 根据连纤的 board_id + port_id 调用 `alarm_query`

### Step 3: 获取性能数据
- `fiber_performance_query` + `fiber_spanloss_query` 确认当前状态

### Step 4: 综合诊断
- 红色：通常为 CRITICAL 告警触发
- 黄色：通常为 MINOR 告警或性能劣化
- 同网元对多条红色 → 疑似光缆故障（参考案例库）

### Step 5: 处理建议（按优先级）
- P0: 红色 + 紧急告警 → 15min 内响应
- P1: 红色 + 无告警 → 30min 内响应
- P2: 黄色 + 次要告警 → 4h 内处理
- P3: 黄色 + 趋势劣化 → 下次巡检

## 输出模板
### 光纤颜色诊断报告
### 当前状态
- 🔴 红色: {red_count} 条
- 🟡 黄色: {yellow_count} 条
### 详细分析
| 光纤 | 颜色 | 网元对 | 场景 | 情况 | 告警 | 优先级 |
|------|------|----------|----------|----------|----------|----------|

### 处理建议
{按照P0→P3处理建议}

### 参考
{RAG知识引用}


## 异常处理
- 颜色查询失败 → 提示后端不可用
- 告警数据为空 → 注明"无活跃告警"