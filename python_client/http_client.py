"""
HTTP 网关客户端 - 通过 API Gateway 调用后端服务
对应 API Gateway (port 8080) 暴露的所有 HTTP 端点
"""

import time
import json
import requests

import config


class FiberMaintainHttpClient:
    """光纤维护系统 HTTP 客户端，封装 API Gateway 所有接口"""

    def __init__(self, base_url=None):
        self.base_url = base_url or config.API_GATEWAY_URL
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "X-Source": "python-client"
        })

    def _request(self, method: str, path: str, params=None, json_data=None):
        """统一请求并打印请求/响应/耗时"""
        url = f"{self.base_url}{path}"
        
        print(f"\n{'='*60}")
        print(f"[HTTP] {method} {url}")
        if params:
            print(f"Query 参数: {params}")
        if json_data:
            print(f"请求 Body: {json.dumps(json_data, ensure_ascii=False, indent=2)}")
        
        start = time.time()
        try:
            resp = self.session.request(method, url, params=params, json=json_data, timeout=config.GRPC_TIMEOUT)
            elapsed = (time.time() - start) * 1000
            
            print(f"响应状态: {resp.status_code} (耗时 {elapsed:.1f}ms)")
            try:
                data = resp.json()
                print(f"响应 Body:\n{json.dumps(data, ensure_ascii=False, indent=2)}")
                return data
            except:
                print(f"响应 Body: {resp.text}")
                return resp.text
        except requests.exceptions.RequestException as e:
            elapsed = (time.time() - start) * 1000
            print(f"[ERROR] HTTP 请求失败 (耗时 {elapsed:.1f}ms)")
            print(f"  错误: {e}")
            return None

    # ═══════════════════════════════════════════════════════════
    # 通用接口
    # ═══════════════════════════════════════════════════════════

    def health_check(self):
        """健康检查"""
        return self._request("GET", "/health")

    # ═══════════════════════════════════════════════════════════
    # BoardService 接口
    # ═══════════════════════════════════════════════════════════

    def create_board(self, board_id: int, board_type: int, ne_id: int):
        """创建单板
        board_type: 1=ACTIVE, 2=PASSIVE
        """
        data = {"board_id": board_id, "board_type": board_type, "ne_id": ne_id}
        return self._request("POST", "/api/v1/boards", json_data=data)

    def delete_board(self, board_id: int):
        """删除单板"""
        return self._request("DELETE", f"/api/v1/boards/{board_id}")

    def get_board(self, board_id: int):
        """查询单板"""
        return self._request("GET", f"/api/v1/boards/{board_id}")

    def batch_get_boards(self, board_ids: list):
        """批量查询单板"""
        data = {"board_ids": board_ids}
        return self._request("POST", "/api/v1/boards/batch", json_data=data)

    def get_board_fibers(self, board_id: int):
        """查询单板关联光纤"""
        return self._request("GET", f"/api/v1/boards/{board_id}/fibers")

    # ═══════════════════════════════════════════════════════════
    # TopologyService 接口
    # ═══════════════════════════════════════════════════════════

    def create_fiber(self, src_board_id: int, src_port_id: int, dst_board_id: int, dst_port_id: int):
        """创建光纤"""
        data = {
            "src_board_id": src_board_id, "src_port_id": src_port_id,
            "dst_board_id": dst_board_id, "dst_port_id": dst_port_id
        }
        return self._request("POST", "/api/v1/topology/fibers", json_data=data)

    def delete_fiber(self, fiber_id: int):
        """删除光纤"""
        return self._request("DELETE", f"/api/v1/topology/fibers/{fiber_id}")

    def get_fiber(self, fiber_id: int):
        """查询光纤"""
        return self._request("GET", f"/api/v1/topology/fibers/{fiber_id}")

    def batch_get_fibers(self, fiber_ids: list):
        """批量查询光纤"""
        data = {"fiber_ids": fiber_ids}
        return self._request("POST", "/api/v1/topology/fibers/batch", json_data=data)

    def get_fiber_scene(self, fiber_id: int):
        """查询光纤场景信息"""
        return self._request("GET", f"/api/v1/topology/fibers/{fiber_id}/scene")

    # ═══════════════════════════════════════════════════════════
    # PerformanceService 接口
    # ═══════════════════════════════════════════════════════════

    def report_performance(self, board_id: int, port_id: int, oop_value: float, iop_value: float):
        """上报性能数据"""
        data = {"board_id": board_id, "port_id": port_id, "oop_value": oop_value, "iop_value": iop_value}
        return self._request("POST", "/api/v1/performance/report", json_data=data)

    def get_current_performance(self, board_id: int, port_id: int):
        """查询当前性能"""
        params = {"board_id": board_id, "port_id": port_id}
        return self._request("GET", "/api/v1/performance/current", params=params)

    def get_history_performance(self, board_id: int, port_id: int, start_time: str, end_time: str):
        """查询历史性能"""
        params = {"board_id": board_id, "port_id": port_id, "start_time": start_time, "end_time": end_time}
        return self._request("GET", "/api/v1/performance/history", params=params)

    # ═══════════════════════════════════════════════════════════
    # AlarmService 接口
    # ═══════════════════════════════════════════════════════════

    def report_alarm(self, board_id: int, port_id: int, alarm_level: int):
        """上报告警
        alarm_level: 1=CRITICAL, 2=MINOR
        """
        data = {"board_id": board_id, "port_id": port_id, "alarm_level": alarm_level}
        return self._request("POST", "/api/v1/alarms/report", json_data=data)

    def clear_alarm(self, board_id: int, port_id: int, alarm_level: int):
        """清除告警"""
        data = {"board_id": board_id, "port_id": port_id, "alarm_level": alarm_level}
        return self._request("POST", "/api/v1/alarms/clear", json_data=data)

    def get_current_alarms(self, board_id: int, port_id: int):
        """查询当前告警"""
        params = {"board_id": board_id, "port_id": port_id}
        return self._request("GET", "/api/v1/alarms/current", params=params)

    # ═══════════════════════════════════════════════════════════
    # FiberMaintService 接口
    # ═══════════════════════════════════════════════════════════

    def get_fiber_performance(self, fiber_id: int):
        """查询光纤性能"""
        return self._request("GET", f"/api/v1/fibers/{fiber_id}/performance")

    def get_fiber_spanloss(self, fiber_id: int):
        """查询光纤跨度损耗"""
        return self._request("GET", f"/api/v1/fibers/{fiber_id}/spanloss")

    def get_colored_fibers(self, color: str):
        """按颜色查询光纤
        color: "GREEN", "RED", "YELLOW"
        """
        params = {"color": color}
        return self._request("GET", "/api/v1/fibers/colored", params=params)

    def get_all_colored_fibers(self):
        """查询所有着色光纤"""
        return self._request("GET", "/api/v1/fibers/colored/all")

    def get_fiber_stats_realtime(self):
        """查询实时统计"""
        return self._request("GET", "/api/v1/fibers/stats/realtime")

    def get_fiber_stats_trend(self, start_time: str, end_time: str):
        """查询趋势统计"""
        params = {"start_time": start_time, "end_time": end_time}
        return self._request("GET", "/api/v1/fibers/stats/trend", params=params)


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
    client = FiberMaintainHttpClient()
    print("HTTP 客户端初始化成功")
    print(f"API Gateway: {client.base_url}")
    print("\n尝试健康检查...")
    client.health_check()
