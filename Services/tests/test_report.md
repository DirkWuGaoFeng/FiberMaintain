# FiberMaintService E2E 测试报告

## 基本信息

| 项目 | 值 |
|------|-----|
| 测试时间 | 2026-07-30 17:45:23 ~ 2026-07-30 17:50:16 |
| 测试环境 | WSL / localhost |
| 服务版本 | 4.0-synced |
| 总体结果 | **FAIL** |

## 总览

| 指标 | 值 |
|------|-----|
| 总用例数 | 41 |
| 通过 | 19 |
| 失败 | 22 |
| 通过率 | 46.3% |

## 分组结果

| 测试组 | 通过 | 失败 | 状态 |
|--------|------|------|------|
| Group 1: Scene 1 Color E2E | 2/6 | 4 | **FAIL** |
| Group 2: Scene 2 Case A Color E2E | 3/9 | 6 | **FAIL** |
| Group 3: Scene 2 Case B Color E2E | 1/3 | 2 | **FAIL** |
| Group 4: Scene 2 Case C Color E2E | 2/2 | 0 | PASS |
| Group 5: Fiber Event Scene Change | 3/10 | 7 | **FAIL** |
| Group 6: Performance & Spanloss Query | 2/4 | 2 | **FAIL** |
| Group 7: Batch Operations & Error Handling | 4/4 | 0 | PASS |
| Group 8: Statistics & Trend | 2/3 | 1 | **FAIL** |

## 失败详情

-   [FAIL] S1-02: dst CRITICAL = RED (expected=RED, actual=NOT_FOUND)
-   [FAIL] S1-03: dst MINOR = YELLOW (expected=YELLOW, actual=NOT_FOUND)
-   [FAIL] S1-05: CRITICAL+MINOR = RED (expected=RED, actual=NOT_FOUND)
-   [FAIL] S1-06: clear CRITICAL, remain MINOR = YELLOW (expected=YELLOW, actual=NOT_FOUND)
-   [FAIL] S2A-04: B=CRITICAL, A2=CRITICAL = RED (expected=RED, actual=NOT_FOUND)
-   [FAIL] S2A-05: B=MINOR, A2=empty = YELLOW (expected=YELLOW, actual=NOT_FOUND)
-   [FAIL] S2A-06: B=empty, A2=MINOR = YELLOW (expected=YELLOW, actual=NOT_FOUND)
-   [FAIL] S2A-07: B=CRITICAL, A2=MINOR = YELLOW (expected=YELLOW, actual=NOT_FOUND)
-   [FAIL] S2A-08: B=MINOR, A2=CRITICAL = YELLOW (expected=YELLOW, actual=NOT_FOUND)
-   [FAIL] S2A-09: B=MINOR, A2=MINOR = YELLOW (expected=YELLOW, actual=NOT_FOUND)
-   [FAIL] S2B-02: B CRITICAL = RED (expected=RED, actual=NOT_FOUND)
-   [FAIL] S2B-03: B MINOR = YELLOW (expected=YELLOW, actual=NOT_FOUND)
-   [FAIL] FE-01b: C->B after Port-2 fiber, B CRITICAL = RED (expected=RED, actual=NOT_FOUND)
-   [FAIL] FE-02a: Case B, B CRITICAL = RED (expected=RED, actual=NOT_FOUND)
-   [FAIL] FE-02b: B->A, both CRITICAL = RED (expected=RED, actual=NOT_FOUND)
-   [FAIL] FE-03a: Case A, both CRITICAL = RED (expected=RED, actual=NOT_FOUND)
-   [FAIL] FE-03b: A->B, B still CRITICAL = RED (expected=RED, actual=NOT_FOUND)
-   [FAIL] FE-04b: B->C, forced GREEN (expected=GREEN, actual=RED)
-   [FAIL] FE-05a: fiber is RED before delete (expected=RED, actual=NOT_FOUND)
-   [FAIL] PF-01: GetFiberPerformance failed: Fiber not found
-   [FAIL] PF-02: Fiber not found
-   [FAIL] ST-02: fiber not found in colored list

## 模拟器数据注入

- 状态: scene_simulator: 200 条拓扑; performance_simulator: 后台运行
- 说明: E2E 测试自建独立拓扑（唯一 ID），模拟器提供背景负载数据

## 测试日志

完整日志: `Services/logs/e2e_test_output.log`

---
*报告由 run_e2e_test.sh 自动生成*
