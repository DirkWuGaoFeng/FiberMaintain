# FiberMaintain 微服务后端

C++17 实现的光纤网络维护微服务集群，基于 gRPC 内部通信 + HTTP/REST 对外暴露。

## 微服务一览

| 服务 | 端口 | 职责 |
|------|------|------|
| BoardService | 50051 | 板卡管理：端口分配、板卡查询、NE 关联 |
| TopologyService | 50062 | 光纤拓扑：连接关系、场景判定、路径计算 |
| PerformanceService | 50053 | 性能采集：OOP/IOP 实时与历史查询 |
| AlarmService | 50054 | 告警处理：当前告警、历史告警、告警统计 |
| FiberMaintService | 50055 | 光纤维护：颜色标记、衰耗分析、SpanLoss、趋势预测 |
| API Gateway | 8080 (HTTP) / 8081 (WS) | REST 路由 × 23、CORS、WebSocket 代理 |

## 目录结构

```
Services/
├── src/
│   ├── common/               # 公共库
│   │   ├── config.h/cpp      # 配置加载 (.conf 文件)
│   │   ├── logger.h/cpp      # 日志（文件+控制台）
│   │   ├── db_connection_pool.h/cpp  # MySQL 连接池
│   │   ├── grpc_client_wrapper.h/cpp # gRPC 客户端封装
│   │   ├── scene_resolver.h/cpp      # 场景解析器
│   │   └── utils.h/cpp       # 工具函数
│   ├── board_service/         # 板卡服务
│   ├── topology_service/      # 拓扑服务
│   ├── performance_service/   # 性能服务
│   ├── alarm_service/         # 告警服务
│   ├── fiber_maint_service/   # 光纤维护服务
│   │   ├── fiber_topology_resolver  # 光纤拓扑解析
│   │   ├── target_builders          # 目标构建器
│   │   ├── color_strategy           # 颜色标记策略
│   │   ├── perf_executor            # 性能执行器
│   │   ├── spanloss_calculator      # SpanLoss 计算
│   │   ├── dependency_builder       # 依赖构建器
│   │   ├── output_layer             # 输出层
│   │   └── pull_callback            # 拉取回调
│   ├── api_gateway/           # API 网关
│   │   ├── http_server.h/cpp  # HTTP 路由 + 代理
│   │   └── websocket_server.h/cpp  # WebSocket 代理
│   ├── proto/                 # Protobuf 接口定义
│   │   ├── common.proto
│   │   ├── board.proto
│   │   ├── topology.proto
│   │   ├── performance.proto
│   │   ├── alarm.proto
│   │   └── fiber_maint.proto
│   └── simulators/            # 模拟器
│       ├── scene_simulator    # 场景模拟器（创建测试数据）
│       ├── alarm_simulator    # 告警模拟器（持续上报告警）
│       └── performance_simulator  # 性能模拟器
├── scripts/
│   ├── start_services.sh      # 一键启动（6 个服务）
│   ├── stop_services.sh       # 一键停止（优雅关闭）
│   └── init_database.sql      # 数据库初始化（5 个库 + 表）
├── config/                    # 服务配置
│   ├── board_service.conf
│   ├── topology_service.conf
│   ├── performance_service.conf
│   ├── alarm_service.conf
│   ├── fiber_maint_service.conf
│   └── api_gateway.conf
├── logs/                      # 运行日志 + PID 文件
├── tests/                     # C++ 集成测试
└── CMakeLists.txt             # 顶层 CMake
```

## 编译（WSL Ubuntu）

### 依赖

- GCC 11+ (C++17)
- CMake 3.16+
- Protobuf 3.12+
- gRPC 1.30+
- MySQL Client
- libmicrohttpd

### 编译步骤

```bash
cd Services
mkdir -p build && cd build
cmake ..
make -j4
```

编译产物在 `build/src/` 下各子目录。

## 初始化数据库

```bash
mysql -u root -p < scripts/init_database.sql
```

创建 5 个数据库：`db_board`、`db_topology`、`db_performance`、`db_alarm`、`db_fiber_maint`

## 启动 / 停止

```bash
# 一键启动（按依赖顺序：Board → Topology → Performance → Alarm → FiberMaint → Gateway）
bash scripts/start_services.sh

# 一键停止（逆序优雅关闭，超时 10s 强制终止）
bash scripts/stop_services.sh
```

## 模拟器

启动服务后，可运行模拟器生成测试数据：

```bash
# 场景模拟器：创建光纤拓扑测试数据
cd build/src/simulators
./scene_simulator

# 告警模拟器：持续上报告警
./alarm_simulator localhost:50051 localhost:50054 1000

# 性能模拟器：持续上报性能数据
./performance_simulator localhost:50051 localhost:50053 5000
```

## API Gateway 路由

共 23 个 REST 路由，前缀 `/api/v1/`：

| 模块 | 路由 | 方法 |
|------|------|------|
| Board | `/boards` | GET |
| Board | `/boards/{id}` | GET |
| Board | `/boards/{id}/ports` | GET |
| Board | `/boards/{id}/ports/{portId}` | GET, PUT |
| Topology | `/topology/fibers` | GET |
| Topology | `/topology/fibers/{id}` | GET |
| Topology | `/topology/fibers/{id}/scene` | GET |
| Topology | `/topology/paths` | POST |
| Topology | `/topology/neighbors` | GET |
| Performance | `/performance/current` | GET |
| Performance | `/performance/history` | GET |
| Performance | `/performance/realtime` | GET |
| Alarm | `/alarms/current` | GET |
| Alarm | `/alarms/history` | GET |
| Alarm | `/alarms/statistics` | GET |
| FiberMaint | `/fiber/colors` | GET |
| FiberMaint | `/fiber/colors/{id}` | GET, PUT |
| FiberMaint | `/fiber/analyze` | POST |
| FiberMaint | `/fiber/spanloss` | POST |
| FiberMaint | `/fiber/trend` | POST |
| FiberMaint | `/fiber/batch-analyze` | POST |
| Health | `/health` | GET |

所有路由支持 OPTIONS preflight（CORS）。

## 配置说明

每个服务对应 `config/` 下的 `.conf` 文件，格式为 `key=value`：

```ini
# 示例：api_gateway.conf
port=8080
ws_port=8081
board_service=localhost:50051
topology_service=localhost:50062
performance_service=localhost:50053
alarm_service=localhost:50054
fiber_maint_service=localhost:50055
```
