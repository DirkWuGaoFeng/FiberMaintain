# FiberMaintain Services — Agent Instructions

C++17 光纤网络维护微服务集群，基于 gRPC 内部通信 + HTTP/REST（libmicrohttpd）对外暴露。
共 6 个微服务 + 1 个 API Gateway，通过 CMake 构建，MySQL 持久化，Protobuf 定义接口契约。

## Module Boundaries

```
src/
├── common/                 # 公共库（所有服务共享）
│   ├── config.h/cpp           # .conf 配置加载（key=value）
│   ├── logger.h/cpp           # 日志（文件 + 控制台双输出）
│   ├── db_connection_pool.h/cpp  # MySQL 连接池
│   ├── grpc_client_wrapper.h/cpp # gRPC 客户端封装
│   ├── scene_resolver.h/cpp   # 场景解析器（拓扑场景判定）
│   └── utils.h/cpp            # 工具函数
├── proto/                  # Protobuf 接口定义（6 个 .proto 文件）
│   ├── common.proto           # 公共消息类型
│   ├── board.proto            # 板卡服务接口
│   ├── topology.proto         # 拓扑服务接口
│   ├── performance.proto      # 性能服务接口
│   ├── alarm.proto            # 告警服务接口
│   └── fiber_maint.proto      # 光纤维护服务接口
├── board_service/          # 板卡服务（:50051）— 端口分配、板卡查询、NE 关联
├── topology_service/       # 拓扑服务（:50062）— 连接关系、场景判定、路径计算
├── performance_service/    # 性能服务（:50053）— OOP/IOP 实时与历史查询
├── alarm_service/          # 告警服务（:50054）— 当前/历史告警、告警统计
├── fiber_maint_service/    # 光纤维护服务（:50055）— 核心业务逻辑
│   ├── fiber_maint_service_impl  # 服务主实现
│   ├── fiber_topology_resolver   # 光纤拓扑解析
│   ├── target_builders           # 目标构建器
│   ├── color_strategy            # 颜色标记策略
│   ├── perf_executor             # 性能执行器
│   ├── spanloss_calculator       # SpanLoss 计算
│   ├── dependency_builder        # 依赖构建器
│   ├── output_layer              # 输出层
│   ├── pull_callback             # 拉取回调
│   ├── event_queue.h / spsc_queue.h  # 无锁队列
│   ├── flap_detector.h           # 抖动检测器
│   └── types.h                   # 领域类型定义
├── api_gateway/            # API Gateway（:8080 HTTP / :8081 WS）
│   ├── http_server.h/cpp      # HTTP 路由（23 个 REST 端点）+ gRPC 代理
│   └── websocket_server.h/cpp # WebSocket 代理
└── simulators/             # 模拟器（开发/测试用）
    ├── scene_simulator        # 场景模拟器（创建测试数据）
    ├── alarm_simulator        # 告警模拟器（持续上报）
    └── performance_simulator  # 性能模拟器（持续上报）

config/                     # 每个服务的 .conf 配置文件
scripts/                    # 启动/停止/数据库初始化脚本
tests/                      # C++ 集成测试（test_all_services, test_fiber_maint, e2e）
build/                      # CMake 编译产物
```

## Commands

| 用途 | 命令 |
|------|------|
| 编译（WSL Ubuntu） | `cd Services && mkdir -p build && cd build && cmake .. && make -j4` |
| 初始化数据库 | `mysql -u root -p < scripts/init_database.sql` |
| 一键启动（6 服务） | `bash scripts/start_services.sh` |
| 一键停止 | `bash scripts/stop_services.sh` |
| 运行场景模拟器 | `cd build/src/simulators && ./scene_simulator` |
| 运行告警模拟器 | `./alarm_simulator localhost:50051 localhost:50054 1000` |
| 运行性能模拟器 | `./performance_simulator localhost:50051 localhost:50053 5000` |
| C++ 集成测试 | `cd build && ctest` 或直接运行 `./tests/test_all_services` |
| E2E 测试 | `bash scripts/run_e2e_test.sh` |
| PowerShell API 测试 | `pwsh tests/api_full_test.ps1` |

## Validation Route

编译变更后必须执行：

```bash
cd build && cmake .. && make -j4    # 重新编译
./tests/test_all_services            # C++ 集成测试
```

API 变更后运行 E2E：

```bash
bash scripts/run_e2e_test.sh         # 全链路 E2E
```

## Key Constraints

- **C++17 + GCC 11+**，CMake 3.16+ 构建
- **gRPC + Protobuf**：服务间通信全部通过 gRPC，接口定义在 `src/proto/*.proto`；修改接口必须同时更新 .proto 和重新编译
- **libmicrohttpd**：API Gateway 的 HTTP 层使用 libmicrohttpd，无第三方 JSON 库（手写极简 JSON 解析）
- **MySQL 持久化**：5 个独立数据库（`db_board`、`db_topology`、`db_performance`、`db_alarm`、`db_fiber_maint`）
- **配置文件**：每个服务对应 `config/*.conf`，格式为 `key=value`，通过 `common/config.h` 加载
- **启动顺序**：Board → Topology → Performance → Alarm → FiberMaint → Gateway（按依赖顺序）
- **fiber_maint_service 是核心业务**：包含颜色标记、衰耗分析、SpanLoss 计算、趋势预测等核心逻辑，修改需特别注意 `types.h` 中的领域类型
- **API Gateway 是 Agent 层的唯一入口**：Agent 通过 `http://localhost:8080/api/v1/` 访问所有 23 个 REST 端点
- **int32 对齐**：Agent 层的 `NormalizedParams` 必须与本层 Protobuf 定义的 int32/enum 类型严格对齐
- **编译环境**：WSL Ubuntu（Linux），不在 Windows 原生编译；依赖 Protobuf 3.12+、gRPC 1.30+、MySQL Client、libmicrohttpd
