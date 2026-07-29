#!/usr/bin/env python3
"""
交互式命令行客户端 - 光纤维护系统 API 演示工具
支持 gRPC 直连和 HTTP 网关两种模式
"""

import sys
import argparse
import time

from grpc_client import FiberMaintainGrpcClient, parse_color, parse_alarm_level, parse_board_type
from http_client import FiberMaintainHttpClient


class InteractiveCLI:
    """交互式命令行界面"""

    def __init__(self, mode='grpc'):
        self.mode = mode
        self.grpc_client = None
        self.http_client = None
        self._init_client()

    def _init_client(self):
        """根据模式初始化客户端"""
        if self.mode == 'grpc':
            self.grpc_client = FiberMaintainGrpcClient()
            print("[模式] gRPC 直连")
        else:
            self.http_client = FiberMaintainHttpClient()
            print(f"[模式] HTTP 网关 ({self.http_client.base_url})")

    def close(self):
        """关闭客户端"""
        if self.grpc_client:
            self.grpc_client.close()

    def _input_int(self, prompt, default=0):
        """输入整数"""
        val = input(f"{prompt} [{default}]: ").strip()
        return int(val) if val else default

    def _input_float(self, prompt, default=0.0):
        """输入浮点数"""
        val = input(f"{prompt} [{default}]: ").strip()
        return float(val) if val else default

    def _input_str(self, prompt, default=""):
        """输入字符串"""
        val = input(f"{prompt} [{default}]: ").strip()
        return val if val else default

    def _input_bool(self, prompt, default=False):
        """输入布尔值"""
        d = "Y/n" if default else "y/N"
        val = input(f"{prompt} [{d}]: ").strip().lower()
        if not val:
            return default
        return val in ('y', 'yes', 'true', '1')

    def _input_list(self, prompt, item_type=int):
        """输入列表（逗号分隔）"""
        val = input(f"{prompt}: ").strip()
        if not val:
            return []
        return [item_type(x.strip()) for x in val.split(',')]

    def _input_ports(self, prompt):
        """输入端口列表 (board_id:port_id,board_id:port_id)"""
        val = input(f"{prompt} (格式 board_id:port_id,board_id:port_id): ").strip()
        if not val:
            return []
        ports = []
        for pair in val.split(','):
            parts = pair.strip().split(':')
            if len(parts) == 2:
                ports.append((int(parts[0]), int(parts[1])))
        return ports

    # ═══════════════════════════════════════════════════════════
    # 菜单定义
    # ═══════════════════════════════════════════════════════════

    MENU = {
        "1": {
            "name": "BoardService (单板服务)",
            "methods": {
                "1": ("CreateBoard - 创建单板", "create_board"),
                "2": ("DeleteBoard - 删除单板", "delete_board"),
                "3": ("GetBoard - 查询单板", "get_board"),
                "4": ("BatchGetBoards - 批量查询单板", "batch_get_boards"),
                "5": ("ListBoards - 列出所有单板", "list_boards"),
                "6": ("GetBoardFibers - 查询单板关联光纤", "get_board_fibers"),
                "7": ("UpdatePortOccupied - 更新端口占用 (仅gRPC)", "update_port_occupied"),
                "8": ("HealthCheck - 健康检查", "board_health_check"),
            }
        },
        "2": {
            "name": "TopologyService (拓扑服务)",
            "methods": {
                "1": ("CreateFiber - 创建光纤", "create_fiber"),
                "2": ("DeleteFiber - 删除光纤", "delete_fiber"),
                "3": ("GetFiber - 查询光纤", "get_fiber"),
                "4": ("BatchGetFibers - 批量查询光纤", "batch_get_fibers"),
                "5": ("GetFibersByPort - 按端口查光纤 (仅gRPC)", "get_fibers_by_port"),
                "6": ("GetFiberScene - 查光纤场景", "get_fiber_scene"),
                "7": ("HealthCheck - 健康检查", "topology_health_check"),
            }
        },
        "3": {
            "name": "PerformanceService (性能服务)",
            "methods": {
                "1": ("ReportPerformance - 上报性能", "report_performance"),
                "2": ("GetCurrentPerformance - 查当前性能", "get_current_performance"),
                "3": ("GetHistoryPerformance - 查历史性能", "get_history_performance"),
                "4": ("BatchGetCurrentPerformance - 批量当前性能 (仅gRPC)", "batch_get_current_performance"),
                "5": ("BatchGetHistoryPerformance - 批量历史性能 (仅gRPC)", "batch_get_history_performance"),
                "6": ("HealthCheck - 健康检查", "performance_health_check"),
            }
        },
        "4": {
            "name": "AlarmService (告警服务)",
            "methods": {
                "1": ("ReportAlarm - 上报告警", "report_alarm"),
                "2": ("ClearAlarm - 清除告警", "clear_alarm"),
                "3": ("GetCurrentAlarm - 查当前告警", "get_current_alarm"),
                "4": ("BatchGetCurrentAlarms - 批量查告警 (仅gRPC)", "batch_get_current_alarms"),
                "5": ("CreatePullCall - 创建拉调用 (仅gRPC)", "create_pull_call"),
                "6": ("GetPullCallResult - 查拉调用结果 (仅gRPC)", "get_pull_call_result"),
                "7": ("CancelPullCall - 取消拉调用 (仅gRPC)", "cancel_pull_call"),
                "8": ("HealthCheck - 健康检查", "alarm_health_check"),
            }
        },
        "5": {
            "name": "FiberMaintService (光纤维护服务)",
            "methods": {
                "1": ("GetFiberPerformance - 查光纤性能", "get_fiber_performance"),
                "2": ("BatchGetFiberPerformance - 批量光纤性能 (仅gRPC)", "batch_get_fiber_performance"),
                "3": ("GetFiberHistoryPerformance - 光纤历史性能 (仅gRPC)", "get_fiber_history_performance"),
                "4": ("BatchGetFiberHistoryPerformance - 批量历史性能 (仅gRPC)", "batch_get_fiber_history_performance"),
                "5": ("GetFiberSpanloss - 查光纤跨度损耗", "get_fiber_spanloss"),
                "6": ("BatchGetFiberSpanloss - 批量跨度损耗 (仅gRPC)", "batch_get_fiber_spanloss"),
                "7": ("GetColoredFibers - 按颜色查光纤", "get_colored_fibers"),
                "8": ("GetAllColoredFibers - 查所有着色光纤", "get_all_colored_fibers"),
                "9": ("GetFiberStatsRealtime - 实时统计", "get_fiber_stats_realtime"),
                "10": ("GetFiberStatsTrend - 趋势统计", "get_fiber_stats_trend"),
                "11": ("PullCallResultCallback - 拉调用回调 (仅gRPC)", "pull_call_result_callback"),
                "12": ("HealthCheck - 健康检查", "fiber_maint_health_check"),
            }
        },
        "6": {
            "name": "流式订阅接口 (仅gRPC)",
            "methods": {
                "1": ("SubscribeFiberColorEvents - 订阅光纤颜色事件", "subscribe_fiber_color_events"),
                "2": ("SubscribeAlarmEvents - 订阅告警事件", "subscribe_alarm_events"),
                "3": ("SubscribeBoardEvents - 订阅单板事件", "subscribe_board_events"),
                "4": ("SubscribeFiberEvents - 订阅光纤事件", "subscribe_fiber_events"),
            }
        },
        "0": ("演示流程 (Demo)", "run_demo"),
    }

    # ═══════════════════════════════════════════════════════════
    # 方法参数收集与调用
    # ═══════════════════════════════════════════════════════════

    def _call_method(self, method_name):
        """调用指定方法"""
        client = self.grpc_client if self.mode == 'grpc' else self.http_client
        
        # BoardService
        if method_name == "create_board":
            board_id = self._input_int("board_id")
            board_type = self._input_int("board_type (1=ACTIVE, 2=PASSIVE)", 1)
            ne_id = self._input_int("ne_id")
            return client.create_board(board_id, board_type, ne_id)
        elif method_name == "delete_board":
            board_id = self._input_int("board_id")
            return client.delete_board(board_id)
        elif method_name == "get_board":
            board_id = self._input_int("board_id")
            return client.get_board(board_id)
        elif method_name == "batch_get_boards":
            board_ids = self._input_list("board_ids (逗号分隔)")
            return client.batch_get_boards(board_ids)
        elif method_name == "list_boards":
            return client.list_boards()
        elif method_name == "get_board_fibers":
            board_id = self._input_int("board_id")
            return client.get_board_fibers(board_id)
        elif method_name == "update_port_occupied":
            if self.mode != 'grpc':
                print("[提示] 此接口仅支持 gRPC 模式")
                return
            board_id = self._input_int("board_id")
            port_id = self._input_int("port_id")
            occupied = self._input_bool("occupied", True)
            return self.grpc_client.update_port_occupied(board_id, port_id, occupied)
        elif method_name == "board_health_check":
            return client.board_health_check()

        # TopologyService
        elif method_name == "create_fiber":
            src_board_id = self._input_int("src_board_id")
            src_port_id = self._input_int("src_port_id")
            dst_board_id = self._input_int("dst_board_id")
            dst_port_id = self._input_int("dst_port_id")
            return client.create_fiber(src_board_id, src_port_id, dst_board_id, dst_port_id)
        elif method_name == "delete_fiber":
            fiber_id = self._input_int("fiber_id")
            return client.delete_fiber(fiber_id)
        elif method_name == "get_fiber":
            fiber_id = self._input_int("fiber_id")
            return client.get_fiber(fiber_id)
        elif method_name == "batch_get_fibers":
            fiber_ids = self._input_list("fiber_ids (逗号分隔)")
            return client.batch_get_fibers(fiber_ids)
        elif method_name == "get_fibers_by_port":
            if self.mode != 'grpc':
                print("[提示] 此接口仅支持 gRPC 模式")
                return
            board_id = self._input_int("board_id")
            port_id = self._input_int("port_id")
            return self.grpc_client.get_fibers_by_port(board_id, port_id)
        elif method_name == "get_fiber_scene":
            fiber_id = self._input_int("inter_ne_fiber_id")
            return client.get_fiber_scene(fiber_id)
        elif method_name == "topology_health_check":
            return client.topology_health_check()

        # PerformanceService
        elif method_name == "report_performance":
            board_id = self._input_int("board_id")
            port_id = self._input_int("port_id")
            oop_value = self._input_float("oop_value (dBm)")
            iop_value = self._input_float("iop_value (dBm)")
            return client.report_performance(board_id, port_id, oop_value, iop_value)
        elif method_name == "get_current_performance":
            board_id = self._input_int("board_id")
            port_id = self._input_int("port_id")
            return client.get_current_performance(board_id, port_id)
        elif method_name == "get_history_performance":
            board_id = self._input_int("board_id")
            port_id = self._input_int("port_id")
            start_time = self._input_str("start_time (YYYY-MM-DD HH:MM:SS)", "2024-01-01 00:00:00")
            end_time = self._input_str("end_time (YYYY-MM-DD HH:MM:SS)", "2024-12-31 23:59:59")
            return client.get_history_performance(board_id, port_id, start_time, end_time)
        elif method_name == "batch_get_current_performance":
            if self.mode != 'grpc':
                print("[提示] 此接口仅支持 gRPC 模式")
                return
            ports = self._input_ports("ports")
            return self.grpc_client.batch_get_current_performance(ports)
        elif method_name == "batch_get_history_performance":
            if self.mode != 'grpc':
                print("[提示] 此接口仅支持 gRPC 模式")
                return
            ports = self._input_ports("ports")
            start_time = self._input_str("start_time", "2024-01-01 00:00:00")
            end_time = self._input_str("end_time", "2024-12-31 23:59:59")
            return self.grpc_client.batch_get_history_performance(ports, start_time, end_time)
        elif method_name == "performance_health_check":
            return client.performance_health_check()

        # AlarmService
        elif method_name == "report_alarm":
            board_id = self._input_int("board_id")
            port_id = self._input_int("port_id")
            alarm_level = self._input_int("alarm_level (1=CRITICAL, 2=MINOR)", 1)
            return client.report_alarm(board_id, port_id, alarm_level)
        elif method_name == "clear_alarm":
            board_id = self._input_int("board_id")
            port_id = self._input_int("port_id")
            alarm_level = self._input_int("alarm_level (1=CRITICAL, 2=MINOR)", 1)
            return client.clear_alarm(board_id, port_id, alarm_level)
        elif method_name == "get_current_alarm":
            board_id = self._input_int("board_id")
            port_id = self._input_int("port_id")
            return client.get_current_alarm(board_id, port_id)
        elif method_name == "batch_get_current_alarms":
            if self.mode != 'grpc':
                print("[提示] 此接口仅支持 gRPC 模式")
                return
            ports = self._input_ports("ports")
            return self.grpc_client.batch_get_current_alarms(ports)
        elif method_name == "create_pull_call":
            if self.mode != 'grpc':
                print("[提示] 此接口仅支持 gRPC 模式")
                return
            ports = self._input_ports("ports")
            include_history = self._input_bool("include_history", False)
            expire_seconds = self._input_int("expire_seconds", 60)
            callback_addr = self._input_str("callback_service_addr", "localhost:50055")
            return self.grpc_client.create_pull_call(ports, include_history, expire_seconds, callback_addr)
        elif method_name == "get_pull_call_result":
            if self.mode != 'grpc':
                print("[提示] 此接口仅支持 gRPC 模式")
                return
            task_id = self._input_str("task_id")
            return self.grpc_client.get_pull_call_result(task_id)
        elif method_name == "cancel_pull_call":
            if self.mode != 'grpc':
                print("[提示] 此接口仅支持 gRPC 模式")
                return
            task_id = self._input_str("task_id")
            return self.grpc_client.cancel_pull_call(task_id)
        elif method_name == "alarm_health_check":
            return client.alarm_health_check()

        # FiberMaintService
        elif method_name == "get_fiber_performance":
            fiber_id = self._input_int("fiber_id")
            return client.get_fiber_performance(fiber_id)
        elif method_name == "batch_get_fiber_performance":
            if self.mode != 'grpc':
                print("[提示] 此接口仅支持 gRPC 模式")
                return
            fiber_ids = self._input_list("fiber_ids (逗号分隔)")
            return self.grpc_client.batch_get_fiber_performance(fiber_ids)
        elif method_name == "get_fiber_history_performance":
            if self.mode != 'grpc':
                print("[提示] 此接口仅支持 gRPC 模式")
                return
            fiber_id = self._input_int("fiber_id")
            start_time = self._input_str("start_time", "2024-01-01 00:00:00")
            end_time = self._input_str("end_time", "2024-12-31 23:59:59")
            return self.grpc_client.get_fiber_history_performance(fiber_id, start_time, end_time)
        elif method_name == "batch_get_fiber_history_performance":
            if self.mode != 'grpc':
                print("[提示] 此接口仅支持 gRPC 模式")
                return
            fiber_ids = self._input_list("fiber_ids (逗号分隔)")
            start_time = self._input_str("start_time", "2024-01-01 00:00:00")
            end_time = self._input_str("end_time", "2024-12-31 23:59:59")
            return self.grpc_client.batch_get_fiber_history_performance(fiber_ids, start_time, end_time)
        elif method_name == "get_fiber_spanloss":
            fiber_id = self._input_int("fiber_id")
            return client.get_fiber_spanloss(fiber_id)
        elif method_name == "batch_get_fiber_spanloss":
            if self.mode != 'grpc':
                print("[提示] 此接口仅支持 gRPC 模式")
                return
            fiber_ids = self._input_list("fiber_ids (逗号分隔)")
            return self.grpc_client.batch_get_fiber_spanloss(fiber_ids)
        elif method_name == "get_colored_fibers":
            color_str = self._input_str("color (GREEN/RED/YELLOW)", "RED")
            color = parse_color(color_str)
            return client.get_colored_fibers(color)
        elif method_name == "get_all_colored_fibers":
            return client.get_all_colored_fibers()
        elif method_name == "get_fiber_stats_realtime":
            return client.get_fiber_stats_realtime()
        elif method_name == "get_fiber_stats_trend":
            start_time = self._input_str("start_time", "2024-01-01 00:00:00")
            end_time = self._input_str("end_time", "2024-12-31 23:59:59")
            return client.get_fiber_stats_trend(start_time, end_time)
        elif method_name == "pull_call_result_callback":
            if self.mode != 'grpc':
                print("[提示] 此接口仅支持 gRPC 模式")
                return
            task_id = self._input_str("task_id")
            status = self._input_str("status", "completed")
            return self.grpc_client.pull_call_result_callback(task_id, status)
        elif method_name == "fiber_maint_health_check":
            return client.fiber_maint_health_check()

        # 流式接口
        elif method_name == "subscribe_fiber_color_events":
            if self.mode != 'grpc':
                print("[提示] 流式接口仅支持 gRPC 模式")
                return
            max_events = self._input_int("max_events", 5)
            return self.grpc_client.subscribe_fiber_color_events(max_events)
        elif method_name == "subscribe_alarm_events":
            if self.mode != 'grpc':
                print("[提示] 流式接口仅支持 gRPC 模式")
                return
            max_events = self._input_int("max_events", 5)
            return self.grpc_client.subscribe_alarm_events(max_events)
        elif method_name == "subscribe_board_events":
            if self.mode != 'grpc':
                print("[提示] 流式接口仅支持 gRPC 模式")
                return
            max_events = self._input_int("max_events", 5)
            return self.grpc_client.subscribe_board_events(max_events)
        elif method_name == "subscribe_fiber_events":
            if self.mode != 'grpc':
                print("[提示] 流式接口仅支持 gRPC 模式")
                return
            max_events = self._input_int("max_events", 5)
            return self.grpc_client.subscribe_fiber_events(max_events)

        else:
            print(f"[错误] 未知方法: {method_name}")

    # ═══════════════════════════════════════════════════════════
    # 演示流程
    # ═══════════════════════════════════════════════════════════

    def run_demo(self):
        """运行演示流程：创建单板 -> 创建光纤 -> 查性能 -> 查告警 -> 清理"""
        print("\n" + "="*60)
        print("演示流程：完整业务场景模拟")
        print("="*60)
        
        client = self.grpc_client if self.mode == 'grpc' else self.http_client
        
        # Step 1: 创建单板
        print("\n[Step 1] 创建两个单板 (源/目的)")
        client.create_board(board_id=100, board_type=1, ne_id=1)
        client.create_board(board_id=101, board_type=1, ne_id=2)
        
        # Step 2: 查询单板
        print("\n[Step 2] 查询创建的单板")
        client.get_board(100)
        client.get_board(101)
        
        # Step 3: 创建光纤
        print("\n[Step 3] 创建光纤连接")
        client.create_fiber(src_board_id=100, src_port_id=1, dst_board_id=101, dst_port_id=1)
        
        # Step 4: 查询光纤
        print("\n[Step 4] 查询光纤信息")
        client.get_fiber(1)
        
        # Step 5: 上报性能
        print("\n[Step 5] 上报性能数据")
        client.report_performance(board_id=100, port_id=1, oop_value=-5.5, iop_value=-6.2)
        
        # Step 6: 查询性能
        print("\n[Step 6] 查询性能数据")
        client.get_current_performance(board_id=100, port_id=1)
        
        # Step 7: 报告告警
        print("\n[Step 7] 报告告警")
        client.report_alarm(board_id=100, port_id=1, alarm_level=2)
        
        # Step 8: 查询告警
        print("\n[Step 8] 查询当前告警")
        client.get_current_alarms(board_id=100, port_id=1)
        
        # Step 9: 清除告警
        print("\n[Step 9] 清除告警")
        client.clear_alarm(board_id=100, port_id=1, alarm_level=2)
        
        # Step 10: 清理 - 删除光纤和单板
        print("\n[Step 10] 清理资源")
        client.delete_fiber(1)
        client.delete_board(100)
        client.delete_board(101)
        
        print("\n" + "="*60)
        print("演示流程完成!")
        print("="*60)

    # ═══════════════════════════════════════════════════════════
    # 主循环
    # ═══════════════════════════════════════════════════════════

    def run(self):
        """运行交互式菜单"""
        while True:
            print("\n" + "="*60)
            print("光纤维护系统 API 客户端")
            print(f"当前模式: {'gRPC 直连' if self.mode == 'grpc' else 'HTTP 网关'}")
            print("="*60)
            
            for key, val in self.MENU.items():
                if key == "0":
                    print(f"  {key}. {val[0]}")
                else:
                    print(f"  {key}. {val['name']}")
            print("  q. 退出")
            
            choice = input("\n请选择服务 [0-6/q]: ").strip().lower()
            
            if choice == 'q':
                break
            elif choice == '0':
                self.run_demo()
            elif choice in self.MENU:
                service = self.MENU[choice]
                self._show_service_menu(service)
            else:
                print("[错误] 无效选择")

    def _show_service_menu(self, service):
        """显示服务子菜单"""
        while True:
            print(f"\n--- {service['name']} ---")
            for key, (name, _) in service['methods'].items():
                print(f"  {key}. {name}")
            print("  b. 返回上级")
            
            choice = input("\n请选择方法: ").strip().lower()
            
            if choice == 'b':
                break
            elif choice in service['methods']:
                _, method_name = service['methods'][choice]
                self._call_method(method_name)
            else:
                print("[错误] 无效选择")


def main():
    parser = argparse.ArgumentParser(description="光纤维护系统 API 客户端")
    parser.add_argument('--mode', '-m', choices=['grpc', 'http'], default='grpc',
                        help='调用模式: grpc(直连) 或 http(网关)')
    parser.add_argument('--demo', '-d', action='store_true',
                        help='直接运行演示流程')
    
    args = parser.parse_args()
    
    cli = InteractiveCLI(mode=args.mode)
    
    try:
        if args.demo:
            cli.run_demo()
        else:
            cli.run()
    except KeyboardInterrupt:
        print("\n\n[退出] 用户中断")
    finally:
        cli.close()


if __name__ == "__main__":
    main()
