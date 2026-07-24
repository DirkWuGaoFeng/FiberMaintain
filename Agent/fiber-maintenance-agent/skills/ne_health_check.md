
---
name: ne_health_check
description: 网元级光纤健康巡检
version: "1.0"
triggers: [巡检, 健康, 网元, 检查]
tools_required: [board_query, fiber_connection_query, fiber_performance_query, fiber_spanloss_query, alarm_query, colored_fibers_query]
output_format: markdown
---
# 网元健康巡检技能

## 执行步骤

### Step 1: 获取网元关联连纤

- `board_query` → 网元下所有单盘
- `fiber_connection_query` → 关联连纤（仅网元间）

### Step 2: 逐条检查

- 性能：OOP/IOP 正常？
- 衰耗：在阈值内？
- 告警：有活跃告警？
- 颜色：绿色？

### Step 3: 健康评分

- 100 分：全绿 + 无告警
- 60-90：有黄色
- 0-60：有红色

### Step 4: 巡检报告

## 输出模板

### 网元 NE{ne_id} 健康巡检报告
### 健康评分: {score}/100 {emoji}
### 概览
- 关联连纤: {total} | 🟢{green} 🟡{yellow} 🔴{red}
- 活跃告警: {alarm_count}
### 问题清单
| 光纤 | 问题 | 问题类型 | 建议 |
|------|------|------|------|

### 维护建议
{按优先级}

### 下次巡检建议: {date}


## 异常处理
- 网元无关联连纤 → 提示"该网元无网元间连纤"
- 部分连纤查询失败 → 标注并继续
