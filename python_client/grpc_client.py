"""
gRPC 直连客户端 - 直接调用各后端 gRPC 服务
入参出参严格对齐 proto 定义，便于复现 Agent 调用后端 API 时的异常
"""

import sys
import os
import time
import grpc
from google.protobuf import text_format

# 添加 generated 目录到路径（使 proto 生成的模块可直接导入）
_generated_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'generated')
if _generated_dir not in sys.path:
    sys.path.insert(0, _generated_dir)

import board_pb2
import board_pb2_grpc
import topology_pb2
import topology_pb2_grpc
import performance_pb2
import performance_pb2_grpc
import alarm_pb2
import alarm_pb2_grpc
import fiber_maint_pb2
import fiber_maint_pb2_grpc
import common_pb2

import config


class FiberMaintainGrpcClient:
    """光纤维护系统 gRPC 客户端，封装所有 5 个后端服务"""

    def __init__(self):
        self.channels = {}
        self.stubs = {}
        self._init_stubs()

    def _init_stubs(self):
        """初始化所有 gRPC channel 和 stub"""
        services = {
            'board': (config.BOARD_SERVICE_ADDR, board_pb2_grpc.BoardServiceStub),
            'topology': (config.TOPOLOGY_SERVICE_ADDR, topology_pb2_grpc.TopologyServiceStub),
            'performance': (config.PERFORMANCE_SERVICE_ADDR, performance_pb2_grpc.PerformanceServiceStub),
            'alarm': (config.ALARM_SERVICE_ADDR, alarm_pb2_grpc.AlarmServiceStub),
            'fiber_maint': (config.FIBER_MAINT_SERVICE_ADDR, fiber_maint_pb2_grpc.FiberMaintServiceStub),
        }
        for name, (addr, stub_cls) in services.items():
            channel = grpc.insecure_channel(addr)
            self.channels[name] = channel
            self.stubs[name] = stub_cls(channel)

    def close(self):
        """关闭所有 channel"""
        for ch in self.channels.values():
            ch.close()

    def _call_and_print(self, method_name, stub_method, request, timeout=config.GRPC_TIMEOUT):
        """统一调用并打印请求/响应/耗时"""
        print(f"\n{'='*60}")
        print(f"[gRPC] {method_name}")
        print(f"请求参数:\n{text_format.MessageToString(request, as_one_line=False)}")
        
        start = time.time()
        try:
            response = stub_method(request, timeout=timeout)
            elapsed = (time.time() - start) * 1000
            print(f"响应结果 (耗时 {elapsed:.1f}ms):\n{text_format.MessageToString(response, as_one_line=False)}")
            return response
        except grpc.RpcError as e:
            elapsed = (time.time() - start) * 1000
            print(f"[ERROR] gRPC 调用失败 (耗时 {elapsed:.1f}ms)")
            print(f"  状态码: {e.code()}")
            print(f"  详情: {e.details()}")
            return None

    # ═══════════════════════════════════════════════════════════
    # BoardService 接口
    # ═══════════════════════════════════════════════════════════

    def create_board(self, board_id: int, board_type: int, ne_id: int):
        """创建单板
        board_type: 1=ACTIVE, 2=PASSIVE
        """
        req = board_pb2.CreateBoardRequest(board_id=board_id, board_type=board_type, ne_id=ne_id)
        return self._call_and_print("BoardService.CreateBoard", self.stubs['board'].CreateBoard, req)

    def delete_board(self, board_id: int):
        """删除单板"""
        req = board_pb2.DeleteBoardRequest(board_id=board_id)
        return self._call_and_print("BoardService.DeleteBoard", self.stubs['board'].DeleteBoard, req)

    def get_board(self, board_id: int):
        """查询单板"""
        req = board_pb2.GetBoardRequest(board_id=board_id)
        return self._call_and_print("BoardService.GetBoard", self.stubs['board'].GetBoard, req)

    def batch_get_boards(self, board_ids: list):
        """批量查询单板"""
        req = board_pb2.BatchGetBoardsRequest(board_ids=board_ids)
        return self._call_and_print("BoardService.BatchGetBoards", self.stubs['board'].BatchGetBoards, req)

    def list_boards(self):
        """列出所有单板"""
        req = board_pb2.ListBoardsRequest()
        return self._call_and_print("BoardService.ListBoards", self.stubs['board'].ListBoards, req)

    def get_board_fibers(self, board_id: int):
        """查询单板关联光纤"""
        req = board_pb2.GetBoardFibersRequest(board_id=board_id)
        return self._call_and_print("BoardService.GetBoardFibers", self.stubs['board'].GetBoardFibers, req)

    def update_port_occupied(self, board_id: int, port_id: int, occupied: bool):
        """更新端口占用状态"""
        req = board_pb2.UpdatePortOccupiedRequest(board_id=board_id, port_id=port_id, occupied=occupied)
        return self._call_and_print("BoardService.UpdatePortOccupied", self.stubs['board'].UpdatePortOccupied, req)

    def board_health_check(self):
        """BoardService 健康检查"""
        req = board_pb2.HealthCheckRequest()
        return self._call_and_print("BoardService.HealthCheck", self.stubs['board'].HealthCheck, req)

    # ═══════════════════════════════════════════════════════════
    # TopologyService 接口
    # ═══════════════════════════════════════════════════════════

    def create_fiber(self, src_board_id: int, src_port_id: int, dst_board_id: int, dst_port_id: int):
        """创建光纤"""
        req = topology_pb2.CreateFiberRequest(
            src_board_id=src_board_id, src_port_id=src_port_id,
            dst_board_id=dst_board_id, dst_port_id=dst_port_id
        )
        return self._call_and_print("TopologyService.CreateFiber", self.stubs['topology'].CreateFiber, req)

    def delete_fiber(self, fiber_id: int):
        """删除光纤"""
        req = topology_pb2.DeleteFiberRequest(fiber_id=fiber_id)
        return self._call_and_print("TopologyService.DeleteFiber", self.stubs['topology'].DeleteFiber, req)

    def get_fiber(self, fiber_id: int):
        """查询光纤"""
        req = topology_pb2.GetFiberRequest(fiber_id=fiber_id)
        return self._call_and_print("TopologyService.GetFiber", self.stubs['topology'].GetFiber, req)

    def batch_get_fibers(self, fiber_ids: list):
        """批量查询光纤"""
        req = topology_pb2.BatchGetFibersRequest(fiber_ids=fiber_ids)
        return self._call_and_print("TopologyService.BatchGetFibers", self.stubs['topology'].BatchGetFibers, req)

    def get_fibers_by_port(self, board_id: int, port_id: int):
        """按端口查询光纤"""
        req = topology_pb2.GetFibersByPortRequest(board_id=board_id, port_id=port_id)
        return self._call_and_print("TopologyService.GetFibersByPort", self.stubs['topology'].GetFibersByPort, req)

    def get_fiber_scene(self, inter_ne_fiber_id: int):
        """查询光纤场景信息"""
        req = topology_pb2.GetFiberSceneRequest(inter_ne_fiber_id=inter_ne_fiber_id)
        return self._call_and_print("TopologyService.GetFiberScene", self.stubs['topology'].GetFiberScene, req)

    def topology_health_check(self):
        """TopologyService 健康检查"""
        req = topology_pb2.HealthCheckRequest()
        return self._call_and_print("TopologyService.HealthCheck", self.stubs['topology'].HealthCheck, req)

    # ═══════════════════════════════════════════════════════════
    # PerformanceService 接口
    # ═══════════════════════════════════════════════════════════

    def report_performance(self, board_id: int, port_id: int, oop_value: float, iop_value: float):
        """上报性能数据"""
        req = performance_pb2.ReportPerformanceRequest(
            board_id=board_id, port_id=port_id, oop_value=oop_value, iop_value=iop_value
        )
        return self._call_and_print("PerformanceService.ReportPerformance", self.stubs['performance'].ReportPerformance, req)

    def get_current_performance(self, board_id: int, port_id: int):
        """查询当前性能"""
        req = performance_pb2.GetCurrentPerformanceRequest(board_id=board_id, port_id=port_id)
        return self._call_and_print("PerformanceService.GetCurrentPerformance", self.stubs['performance'].GetCurrentPerformance, req)

    def get_history_performance(self, board_id: int, port_id: int, start_time: str, end_time: str):
        """查询历史性能"""
        req = performance_pb2.GetHistoryPerformanceRequest(
            board_id=board_id, port_id=port_id, start_time=start_time, end_time=end_time
        )
        return self._call_and_print("PerformanceService.GetHistoryPerformance", self.stubs['performance'].GetHistoryPerformance, req)

    def batch_get_current_performance(self, ports: list):
        """批量查询当前性能
        ports: [(board_id, port_id), ...]
        """
        port_refs = [performance_pb2.PortRef(board_id=b, port_id=p) for b, p in ports]
        req = performance_pb2.BatchGetCurrentPerformanceRequest(ports=port_refs)
        return self._call_and_print("PerformanceService.BatchGetCurrentPerformance", self.stubs['performance'].BatchGetCurrentPerformance, req)

    def batch_get_history_performance(self, ports: list, start_time: str, end_time: str):
        """批量查询历史性能
        ports: [(board_id, port_id), ...]
        """
        port_refs = [performance_pb2.PortRef(board_id=b, port_id=p) for b, p in ports]
        req = performance_pb2.BatchGetHistoryPerformanceRequest(
            ports=port_refs, start_time=start_time, end_time=end_time
        )
        return self._call_and_print("PerformanceService.BatchGetHistoryPerformance", self.stubs['performance'].BatchGetHistoryPerformance, req)

    def performance_health_check(self):
        """PerformanceService 健康检查"""
        req = performance_pb2.HealthCheckRequest()
        return self._call_and_print("PerformanceService.HealthCheck", self.stubs['performance'].HealthCheck, req)

    # ═══════════════════════════════════════════════════════════
    # AlarmService 接口
    # ═══════════════════════════════════════════════════════════

    def report_alarm(self, board_id: int, port_id: int, alarm_level: int):
        """上报告警
        alarm_level: 1=CRITICAL, 2=MINOR
        """
        req = alarm_pb2.ReportAlarmRequest(board_id=board_id, port_id=port_id, alarm_level=alarm_level)
        return self._call_and_print("AlarmService.ReportAlarm", self.stubs['alarm'].ReportAlarm, req)

    def clear_alarm(self, board_id: int, port_id: int, alarm_level: int):
        """清除告警"""
        req = alarm_pb2.ClearAlarmRequest(board_id=board_id, port_id=port_id, alarm_level=alarm_level)
        return self._call_and_print("AlarmService.ClearAlarm", self.stubs['alarm'].ClearAlarm, req)

    def get_current_alarm(self, board_id: int, port_id: int):
        """查询当前告警"""
        req = alarm_pb2.GetCurrentAlarmRequest(board_id=board_id, port_id=port_id)
        return self._call_and_print("AlarmService.GetCurrentAlarm", self.stubs['alarm'].GetCurrentAlarm, req)

    def batch_get_current_alarms(self, ports: list):
        """批量查询当前告警
        ports: [(board_id, port_id), ...]
        """
        port_refs = [alarm_pb2.PortRef(board_id=b, port_id=p) for b, p in ports]
        req = alarm_pb2.BatchGetCurrentAlarmsRequest(ports=port_refs)
        return self._call_and_print("AlarmService.BatchGetCurrentAlarms", self.stubs['alarm'].BatchGetCurrentAlarms, req)

    def create_pull_call(self, ports: list, include_history: bool, expire_seconds: int, callback_service_addr: str):
        """创建拉调用
        ports: [(board_id, port_id), ...]
        """
        port_refs = [alarm_pb2.PortRef(board_id=b, port_id=p) for b, p in ports]
        req = alarm_pb2.CreatePullCallRequest(
            ports=port_refs, include_history=include_history,
            expire_seconds=expire_seconds, callback_service_addr=callback_service_addr
        )
        return self._call_and_print("AlarmService.CreatePullCall", self.stubs['alarm'].CreatePullCall, req)

    def get_pull_call_result(self, task_id: str):
        """查询拉调用结果"""
        req = alarm_pb2.GetPullCallResultRequest(task_id=task_id)
        return self._call_and_print("AlarmService.GetPullCallResult", self.stubs['alarm'].GetPullCallResult, req)

    def cancel_pull_call(self, task_id: str):
        """取消拉调用"""
        req = alarm_pb2.CancelPullCallRequest(task_id=task_id)
        return self._call_and_print("AlarmService.CancelPullCall", self.stubs['alarm'].CancelPullCall, req)

    def alarm_health_check(self):
        """AlarmService 健康检查"""
        req = alarm_pb2.HealthCheckRequest()
        return self._call_and_print("AlarmService.HealthCheck", self.stubs['alarm'].HealthCheck, req)

    # ═══════════════════════════════════════════════════════════
    # FiberMaintService 接口
    # ═══════════════════════════════════════════════════════════

    def get_fiber_performance(self, fiber_id: int):
        """查询光纤性能"""
        req = fiber_maint_pb2.GetFiberPerformanceRequest(fiber_id=fiber_id)
        return self._call_and_print("FiberMaintService.GetFiberPerformance", self.stubs['fiber_maint'].GetFiberPerformance, req)

    def batch_get_fiber_performance(self, fiber_ids: list):
        """批量查询光纤性能"""
        req = fiber_maint_pb2.BatchGetFiberPerformanceRequest(fiber_ids=fiber_ids)
        return self._call_and_print("FiberMaintService.BatchGetFiberPerformance", self.stubs['fiber_maint'].BatchGetFiberPerformance, req)

    def get_fiber_history_performance(self, fiber_id: int, start_time: str, end_time: str):
        """查询光纤历史性能"""
        req = fiber_maint_pb2.GetFiberHistoryPerformanceRequest(
            fiber_id=fiber_id, start_time=start_time, end_time=end_time
        )
        return self._call_and_print("FiberMaintService.GetFiberHistoryPerformance", self.stubs['fiber_maint'].GetFiberHistoryPerformance, req)

    def batch_get_fiber_history_performance(self, fiber_ids: list, start_time: str, end_time: str):
        """批量查询光纤历史性能"""
        req = fiber_maint_pb2.BatchGetFiberHistoryPerformanceRequest(
            fiber_ids=fiber_ids, start_time=start_time, end_time=end_time
        )
        return self._call_and_print("FiberMaintService.BatchGetFiberHistoryPerformance", self.stubs['fiber_maint'].BatchGetFiberHistoryPerformance, req)

    def get_fiber_spanloss(self, fiber_id: int):
        """查询光纤跨度损耗"""
        req = fiber_maint_pb2.GetFiberSpanlossRequest(fiber_id=fiber_id)
        return self._call_and_print("FiberMaintService.GetFiberSpanloss", self.stubs['fiber_maint'].GetFiberSpanloss, req)

    def batch_get_fiber_spanloss(self, fiber_ids: list):
        """批量查询光纤跨度损耗"""
        req = fiber_maint_pb2.BatchGetFiberSpanlossRequest(fiber_ids=fiber_ids)
        return self._call_and_print("FiberMaintService.BatchGetFiberSpanloss", self.stubs['fiber_maint'].BatchGetFiberSpanloss, req)

    def get_colored_fibers(self, color: int):
        """按颜色查询光纤
        color: 1=GREEN, 2=RED, 3=YELLOW
        """
        req = fiber_maint_pb2.GetColoredFibersRequest(color=color)
        return self._call_and_print("FiberMaintService.GetColoredFibers", self.stubs['fiber_maint'].GetColoredFibers, req)

    def get_all_colored_fibers(self):
        """查询所有着色光纤"""
        req = fiber_maint_pb2.GetAllColoredFibersRequest()
        return self._call_and_print("FiberMaintService.GetAllColoredFibers", self.stubs['fiber_maint'].GetAllColoredFibers, req)

    def get_fiber_stats_realtime(self):
        """查询实时统计"""
        req = fiber_maint_pb2.GetFiberStatsRealtimeRequest()
        return self._call_and_print("FiberMaintService.GetFiberStatsRealtime", self.stubs['fiber_maint'].GetFiberStatsRealtime, req)

    def get_fiber_stats_trend(self, start_time: str, end_time: str):
        """查询趋势统计"""
        req = fiber_maint_pb2.GetFiberStatsTrendRequest(start_time=start_time, end_time=end_time)
        return self._call_and_print("FiberMaintService.GetFiberStatsTrend", self.stubs['fiber_maint'].GetFiberStatsTrend, req)

    def pull_call_result_callback(self, task_id: str, status: str, alarms: list = None):
        """拉调用结果回调
        alarms: [AlarmRecord, ...] 可选
        """
        req = fiber_maint_pb2.PullCallResultCallbackRequest(task_id=task_id, status=status)
        if alarms:
            req.alarms.extend(alarms)
        return self._call_and_print("FiberMaintService.PullCallResultCallback", self.stubs['fiber_maint'].PullCallResultCallback, req)

    def fiber_maint_health_check(self):
        """FiberMaintService 健康检查"""
        req = fiber_maint_pb2.HealthCheckRequest()
        return self._call_and_print("FiberMaintService.HealthCheck", self.stubs['fiber_maint'].HealthCheck, req)

    # ═══════════════════════════════════════════════════════════
    # 流式接口（Subscribe 类）
    # ═══════════════════════════════════════════════════════════

    def subscribe_fiber_color_events(self, max_events=5, timeout=10):
        """订阅光纤颜色变化事件（流式）
        max_events: 最多接收事件数
        timeout: 超时秒数
        """
        print(f"\n{'='*60}")
        print(f"[gRPC] FiberMaintService.SubscribeFiberColorEvents (流式)")
        print(f"等待最多 {max_events} 个事件，超时 {timeout}s...")
        
        req = fiber_maint_pb2.SubscribeFiberColorEventsRequest()
        start = time.time()
        try:
            response_stream = self.stubs['fiber_maint'].SubscribeFiberColorEvents(req, timeout=timeout)
            events = []
            for i, event in enumerate(response_stream):
                if i >= max_events:
                    break
                elapsed = (time.time() - start) * 1000
                print(f"[事件 {i+1}] (耗时 {elapsed:.1f}ms):\n{text_format.MessageToString(event, as_one_line=False)}")
                events.append(event)
            return events
        except grpc.RpcError as e:
            elapsed = (time.time() - start) * 1000
            print(f"[ERROR] 流式调用失败 (耗时 {elapsed:.1f}ms)")
            print(f"  状态码: {e.code()}")
            print(f"  详情: {e.details()}")
            return []

    def subscribe_alarm_events(self, max_events=5, timeout=10):
        """订阅告警事件（流式）"""
        print(f"\n{'='*60}")
        print(f"[gRPC] AlarmService.SubscribeAlarmEvents (流式)")
        print(f"等待最多 {max_events} 个事件，超时 {timeout}s...")
        
        req = alarm_pb2.SubscribeAlarmEventsRequest()
        start = time.time()
        try:
            response_stream = self.stubs['alarm'].SubscribeAlarmEvents(req, timeout=timeout)
            events = []
            for i, event in enumerate(response_stream):
                if i >= max_events:
                    break
                elapsed = (time.time() - start) * 1000
                print(f"[事件 {i+1}] (耗时 {elapsed:.1f}ms):\n{text_format.MessageToString(event, as_one_line=False)}")
                events.append(event)
            return events
        except grpc.RpcError as e:
            elapsed = (time.time() - start) * 1000
            print(f"[ERROR] 流式调用失败 (耗时 {elapsed:.1f}ms)")
            print(f"  状态码: {e.code()}")
            print(f"  详情: {e.details()}")
            return []

    def subscribe_board_events(self, max_events=5, timeout=10):
        """订阅单板事件（流式）"""
        print(f"\n{'='*60}")
        print(f"[gRPC] BoardService.SubscribeBoardEvents (流式)")
        print(f"等待最多 {max_events} 个事件，超时 {timeout}s...")
        
        req = board_pb2.SubscribeBoardEventsRequest()
        start = time.time()
        try:
            response_stream = self.stubs['board'].SubscribeBoardEvents(req, timeout=timeout)
            events = []
            for i, event in enumerate(response_stream):
                if i >= max_events:
                    break
                elapsed = (time.time() - start) * 1000
                print(f"[事件 {i+1}] (耗时 {elapsed:.1f}ms):\n{text_format.MessageToString(event, as_one_line=False)}")
                events.append(event)
            return events
        except grpc.RpcError as e:
            elapsed = (time.time() - start) * 1000
            print(f"[ERROR] 流式调用失败 (耗时 {elapsed:.1f}ms)")
            print(f"  状态码: {e.code()}")
            print(f"  详情: {e.details()}")
            return []

    def subscribe_fiber_events(self, max_events=5, timeout=10):
        """订阅光纤事件（流式）"""
        print(f"\n{'='*60}")
        print(f"[gRPC] TopologyService.SubscribeFiberEvents (流式)")
        print(f"等待最多 {max_events} 个事件，超时 {timeout}s...")
        
        req = topology_pb2.SubscribeFiberEventsRequest()
        start = time.time()
        try:
            response_stream = self.stubs['topology'].SubscribeFiberEvents(req, timeout=timeout)
            events = []
            for i, event in enumerate(response_stream):
                if i >= max_events:
                    break
                elapsed = (time.time() - start) * 1000
                print(f"[事件 {i+1}] (耗时 {elapsed:.1f}ms):\n{text_format.MessageToString(event, as_one_line=False)}")
                events.append(event)
            return events
        except grpc.RpcError as e:
            elapsed = (time.time() - start) * 1000
            print(f"[ERROR] 流式调用失败 (耗时 {elapsed:.1f}ms)")
            print(f"  状态码: {e.code()}")
            print(f"  详情: {e.details()}")
            return []


# 颜色/级别名称映射
COLOR_NAMES = {0: "UNSPECIFIED", 1: "GREEN", 2: "RED", 3: "YELLOW"}
ALARM_LEVEL_NAMES = {0: "UNSPECIFIED", 1: "CRITICAL", 2: "MINOR"}
BOARD_TYPE_NAMES = {0: "UNSPECIFIED", 1: "ACTIVE", 2: "PASSIVE"}


def parse_color(color_str: str) -> int:
    """解析颜色字符串为枚举值"""
    color_map = {"GREEN": 1, "RED": 2, "YELLOW": 3}
    return color_map.get(color_str.upper(), 0)


def parse_alarm_level(level_str: str) -> int:
    """解析告警级别字符串为枚举值"""
    level_map = {"CRITICAL": 1, "MINOR": 2}
    return level_map.get(level_str.upper(), 0)


def parse_board_type(type_str: str) -> int:
    """解析单板类型字符串为枚举值"""
    type_map = {"ACTIVE": 1, "PASSIVE": 2}
    return type_map.get(type_str.upper(), 0)


if __name__ == "__main__":
    # 简单测试
    client = FiberMaintainGrpcClient()
    print("gRPC 客户端初始化成功")
    print("\n可用服务:")
    for name in client.stubs.keys():
        print(f"  - {name}")
    client.close()
