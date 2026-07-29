"""
服务地址配置 - 集中管理所有后端服务地址
可通过环境变量或直接修改默认值来调整连接地址
"""

# ── gRPC 服务直连地址 ──
BOARD_SERVICE_ADDR = "localhost:50051"
TOPOLOGY_SERVICE_ADDR = "localhost:50062"
PERFORMANCE_SERVICE_ADDR = "localhost:50053"
ALARM_SERVICE_ADDR = "localhost:50054"
FIBER_MAINT_SERVICE_ADDR = "localhost:50055"

# ── HTTP API Gateway 地址 ──
API_GATEWAY_URL = "http://localhost:8080"

# ── gRPC 超时设置（秒）──
GRPC_TIMEOUT = 10
