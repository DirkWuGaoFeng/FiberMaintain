# PerformanceService 功能时序图

---

## 1. 上报性能数据 (ReportPerformance)

```mermaid
sequenceDiagram
    participant Client as 客户端/设备
    participant PerformanceService as PerformanceService
    participant DB as 数据库

    Client->>PerformanceService: ReportPerformance(board_id, port_id, oop_value, iop_value)
    
    PerformanceService->>DB: INSERT INTO performance_data (board_id, port_id, oop_value, iop_value)
    DB-->>PerformanceService: 插入成功
    
    PerformanceService->>DB: UPDATE current_performance SET ... WHERE board_id=? AND port_id=?
    DB-->>PerformanceService: 更新成功
    
    PerformanceService-->>Client: {success=true, message="Performance reported"}
```

---

## 2. 获取当前性能 (GetCurrentPerformance)

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant PerformanceService as PerformanceService
    participant DB as 数据库

    Client->>PerformanceService: GetCurrentPerformance(board_id, port_id)
    
    PerformanceService->>DB: SELECT * FROM current_performance WHERE board_id=? AND port_id=?
    DB-->>PerformanceService: 性能记录
    
    PerformanceService-->>Client: {board_id, port_id, oop_value, iop_value, updated_at}
```

---

## 3. 获取历史性能 (GetHistoryPerformance)

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant PerformanceService as PerformanceService
    participant DB as 数据库

    Client->>PerformanceService: GetHistoryPerformance(board_id, port_id, start_time, end_time)
    
    PerformanceService->>DB: SELECT * FROM performance_data WHERE board_id=? AND port_id=? AND recorded_at BETWEEN ? AND ?
    DB-->>PerformanceService: 历史记录列表
    
    PerformanceService-->>Client: {records=[{recorded_at, oop_value, iop_value}, ...]}
```

---

## 4. 批量获取当前性能 (BatchGetCurrentPerformance)

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant PerformanceService as PerformanceService
    participant DB as 数据库

    Client->>PerformanceService: BatchGetCurrentPerformance(ports=[{board_id, port_id}, ...])
    
    loop 每个端口
        PerformanceService->>DB: SELECT * FROM current_performance WHERE board_id=? AND port_id=?
        DB-->>PerformanceService: 性能记录
    end
    
    PerformanceService-->>Client: {results=[{found, board_id, port_id, oop_value, iop_value}, ...]}
```

---

## 5. 批量获取历史性能 (BatchGetHistoryPerformance)

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant PerformanceService as PerformanceService
    participant DB as 数据库

    Client->>PerformanceService: BatchGetHistoryPerformance(ports=[...], start_time, end_time)
    
    loop 每个端口
        PerformanceService->>DB: SELECT * FROM performance_data WHERE board_id=? AND port_id=? AND recorded_at BETWEEN ? AND ?
        DB-->>PerformanceService: 历史记录列表
    end
    
    PerformanceService-->>Client: {results=[{board_id, port_id, records=[...]}, ...]}
```

---

## 6. 健康检查 (HealthCheck)

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant PerformanceService as PerformanceService

    Client->>PerformanceService: HealthCheck()
    
    PerformanceService-->>Client: {serving=true, version="1.0.0"}
```

---

## 功能列表

| 功能 | RPC方法 | 说明 |
|------|---------|------|
| 上报性能 | `ReportPerformance` | 设备上报端口性能数据(OOP/IOP) |
| 获取当前性能 | `GetCurrentPerformance` | 查询指定端口当前性能 |
| 获取历史性能 | `GetHistoryPerformance` | 查询指定端口历史性能趋势 |
| 批量获取当前性能 | `BatchGetCurrentPerformance` | 批量查询多个端口当前性能 |
| 批量获取历史性能 | `BatchGetHistoryPerformance` | 批量查询多个端口历史性能 |
| 健康检查 | `HealthCheck` | 服务健康状态检查 |