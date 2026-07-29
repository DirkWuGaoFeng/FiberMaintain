# 光纤维护系统 Python API 客户端

用于调试和演示光纤维护系统后端 API 的 Python 客户端工具。支持 **gRPC 直连** 和 **HTTP 网关** 两种调用模式，入参出参严格对齐 proto 定义，便于复现 Agent 调用后端 API 时的异常。

## 目录结构

```
python_client/
├── proto/                  # Proto 定义文件（从 Services/src/proto 拷贝）
├── generated/              # protoc 生成的 Python gRPC stubs
├── grpc_client.py          # gRPC 直连客户端（封装 5 个服务的 stub）
├── http_client.py          # HTTP 网关客户端（requests 封装）
├── cli.py                  # 交互式命令行入口
├── config.py               # 服务地址配置
├── requirements.txt        # Python 依赖
└── README.md               # 本文件
```

## 快速开始

### 1. 安装依赖

```bash
cd python_client
pip install -r requirements.txt
```

### 2. 运行交互式客户端

```bash
# gRPC 直连模式（默认）
python cli.py

# HTTP 网关模式
python cli.py --mode http

# 直接运行演示流程
python cli.py --demo
```

### 3. 作为 Python 模块使用

```python
from grpc_client import FiberMaintainGrpcClient
from http_client import FiberMaintainHttpClient

# gRPC 客户端
grpc = FiberMaintainGrpcClient()
grpc.create_board(board_id=1, board_type=1, ne_id=1)
grpc.get_board(board_id=1)
grpc.close()

# HTTP 客户端
http = FiberMaintainHttpClient()
http.create_board(board_id=1, board_type=1, ne_id=1)
http.get_board(board_id=1)
```

## 配置

编辑 `config.py` 修改服务地址：

```python
# gRPC 服务直连地址
BOARD_SERVICE_ADDR = "localhost:50051"
TOPOLOGY_SERVICE_ADDR = "localhost:50062"
PERFORMANCE_SERVICE_ADDR = "localhost:50053"
ALARM_SERVICE_ADDR = "localhost:50054"
FIBER_MAINT_SERVICE_ADDR = "localhost:50055"

# HTTP API Gateway 地址
API_GATEWAY_URL = "http://localhost:8080"

# gRPC 超时设置（秒）
GRPC_TIMEOUT = 10
```

## 覆盖的接口

### BoardService (单板服务)

| 方法 | 说明 | gRPC | HTTP |
|------|------|:----:|:----:|
| CreateBoard | 创建单板 | ✓ | ✓ |
| DeleteBoard | 删除单板 | ✓ | ✓ |
| GetBoard | 查询单板 | ✓ | ✓ |
| BatchGetBoards | 批量查询 | ✓ | ✓ |
| ListBoards | 列出所有单板 | ✓ | - |
| GetBoardFibers | 查关联光纤 | ✓ | ✓ |
| UpdatePortOccupied | 更新端口占用 | ✓ | - |
| HealthCheck | 健康检查 | ✓ | - |

### TopologyService (拓扑服务)

| 方法 | 说明 | gRPC | HTTP |
|------|------|:----:|:----:|
| CreateFiber | 创建光纤 | ✓ | ✓ |
| DeleteFiber | 删除光纤 | ✓ | ✓ |
| GetFiber | 查询光纤 | ✓ | ✓ |
| BatchGetFibers | 批量查询 | ✓ | ✓ |
| GetFibersByPort | 按端口查光纤 | ✓ | - |
| GetFiberScene | 查光纤场景 | ✓ | ✓ |
| HealthCheck | 健康检查 | ✓ | - |

### PerformanceService (性能服务)

| 方法 | 说明 | gRPC | HTTP |
|------|------|:----:|:----:|
| ReportPerformance | 上报性能 | ✓ | ✓ |
| GetCurrentPerformance | 查当前性能 | ✓ | ✓ |
| GetHistoryPerformance | 查历史性能 | ✓ | ✓ |
| BatchGetCurrentPerformance | 批量当前性能 | ✓ | - |
| BatchGetHistoryPerformance | 批量历史性能 | ✓ | - |
| HealthCheck | 健康检查 | ✓ | - |

### AlarmService (告警服务)

| 方法 | 说明 | gRPC | HTTP |
|------|------|:----:|:----:|
| ReportAlarm | 上报告警 | ✓ | ✓ |
| ClearAlarm | 清除告警 | ✓ | ✓ |
| GetCurrentAlarm | 查当前告警 | ✓ | ✓ |
| BatchGetCurrentAlarms | 批量查告警 | ✓ | - |
| CreatePullCall | 创建拉调用 | ✓ | - |
| GetPullCallResult | 查拉调用结果 | ✓ | - |
| CancelPullCall | 取消拉调用 | ✓ | - |
| HealthCheck | 健康检查 | ✓ | - |

### FiberMaintService (光纤维护服务)

| 方法 | 说明 | gRPC | HTTP |
|------|------|:----:|:----:|
| GetFiberPerformance | 查光纤性能 | ✓ | ✓ |
| BatchGetFiberPerformance | 批量光纤性能 | ✓ | - |
| GetFiberHistoryPerformance | 光纤历史性能 | ✓ | - |
| BatchGetFiberHistoryPerformance | 批量历史性能 | ✓ | - |
| GetFiberSpanloss | 查跨度损耗 | ✓ | ✓ |
| BatchGetFiberSpanloss | 批量跨度损耗 | ✓ | - |
| GetColoredFibers | 按颜色查光纤 | ✓ | ✓ |
| GetAllColoredFibers | 查所有着色光纤 | ✓ | ✓ |
| GetFiberStatsRealtime | 实时统计 | ✓ | ✓ |
| GetFiberStatsTrend | 趋势统计 | ✓ | ✓ |
| PullCallResultCallback | 拉调用回调 | ✓ | - |
| HealthCheck | 健康检查 | ✓ | - |

### 流式订阅接口 (仅 gRPC)

| 方法 | 说明 |
|------|------|
| SubscribeFiberColorEvents | 订阅光纤颜色变化事件 |
| SubscribeAlarmEvents | 订阅告警事件 |
| SubscribeBoardEvents | 订阅单板事件 |
| SubscribeFiberEvents | 订阅光纤事件 |

## 枚举值定义

### BoardType (单板类型)
- `1` = ACTIVE (有源板)
- `2` = PASSIVE (无源板)

### AlarmLevel (告警级别)
- `1` = CRITICAL (紧急)
- `2` = MINOR (次要)

### FiberColor (光纤颜色)
- `1` = GREEN (绿色)
- `2` = RED (红色)
- `3` = YELLOW (黄色)

## 演示流程

运行 `python cli.py --demo` 将执行以下完整业务流程：

1. 创建两个单板（源/目的）
2. 查询创建的单板
3. 创建光纤连接
4. 查询光纤信息
5. 上报性能数据
6. 查询性能数据
7. 报告告警
8. 查询当前告警
9. 清除告警
10. 清理资源（删除光纤和单板）

## 调试技巧

### 查看请求/响应详情

每次调用都会打印：
- 请求参数（proto 格式或 JSON）
- 响应结果
- 调用耗时

### 对比 gRPC 与 HTTP 结果

可以分别用两种模式调用相同接口，对比结果：

```bash
# gRPC 模式
python cli.py --mode grpc
# 选择服务 -> 选择方法 -> 输入参数

# HTTP 模式
python cli.py --mode http
# 选择相同的服务和方法，输入相同参数
```

### 流式接口测试

流式接口（Subscribe 类）只支持 gRPC 模式，会持续接收事件直到超时或达到最大事件数。

## 重新生成 Proto Stubs

如果 proto 文件有更新，需要重新生成 Python stubs：

```bash
cd python_client

# 拷贝最新的 proto 文件
cp ../Services/src/proto/*.proto proto/

# 重新生成
python -m grpc_tools.protoc -I./proto --python_out=./generated --grpc_python_out=./generated \
    ./proto/common.proto \
    ./proto/alarm.proto \
    ./proto/board.proto \
    ./proto/topology.proto \
    ./proto/performance.proto \
    ./proto/fiber_maint.proto
```

## 故障排查

### 连接失败

- 检查后端服务是否启动
- 检查 `config.py` 中的地址配置是否正确
- 检查防火墙/网络是否允许连接

### Proto 导入错误

- 确保 `generated/` 目录包含所有 `_pb2.py` 和 `_pb2_grpc.py` 文件
- 重新运行 proto 生成命令

### 模块导入错误

- 确保在 `python_client/` 目录下运行
- 或确保 `python_client/` 已添加到 PYTHONPATH
