# AlarmService 功能时序图

---

## 1. 上报告警 (ReportAlarm)

```mermaid
sequenceDiagram
    participant Client as 客户端/设备
    participant AlarmService as AlarmService
    participant DB as 数据库
    participant Subscribers as 订阅者客户端

    Client->>AlarmService: ReportAlarm(board_id, port_id, alarm_level)
    
    AlarmService->>DB: INSERT INTO current_alarms
    DB-->>AlarmService: 插入成功
    
    AlarmService->>Subscribers: AlarmEvent(event_type=ALARM_REPORTED)
    
    AlarmService-->>Client: {success=true, message="Alarm reported"}
```

---

## 2. 清除告警 (ClearAlarm)

```mermaid
sequenceDiagram
    participant Client as 客户端/设备
    participant AlarmService as AlarmService
    participant DB as 数据库
    participant Subscribers as 订阅者客户端

    Client->>AlarmService: ClearAlarm(board_id, port_id, alarm_level)
    
    AlarmService->>DB: DELETE FROM current_alarms WHERE ...
    DB-->>AlarmService: 删除成功
    
    AlarmService->>Subscribers: AlarmEvent(event_type=ALARM_CLEARED)
    
    AlarmService-->>Client: {success=true, message="Alarm cleared"}
```

---

## 3. 获取当前告警 (GetCurrentAlarm)

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant AlarmService as AlarmService
    participant DB as 数据库

    Client->>AlarmService: GetCurrentAlarm(board_id, port_id)
    
    AlarmService->>DB: SELECT * FROM current_alarms WHERE board_id=? AND port_id=?
    DB-->>AlarmService: 告警记录列表
    
    AlarmService-->>Client: {alarms=[...]}
```

---

## 4. 批量获取当前告警 (BatchGetCurrentAlarms)

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant AlarmService as AlarmService
    participant DB as 数据库

    Client->>AlarmService: BatchGetCurrentAlarms(ports=[{board_id, port_id}, ...])
    
    loop 每个端口
        AlarmService->>DB: SELECT * FROM current_alarms WHERE board_id=? AND port_id=?
        DB-->>AlarmService: 告警记录列表
    end
    
    AlarmService-->>Client: {results=[{board_id, port_id, alarms}, ...]}
```

---

## 5. 订阅告警事件 (SubscribeAlarmEvents)

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant AlarmService as AlarmService

    Client->>AlarmService: SubscribeAlarmEvents()
    
    Note over AlarmService: 建立 gRPC Stream
    
    loop 告警发生时
        AlarmService->>Client: AlarmEvent(event_type, board_id, port_id, alarm_level)
    end
    
    Client-->>AlarmService: (Stream关闭)
```

---

## 6. 创建PullCall任务 (CreatePullCall)

```mermaid
sequenceDiagram
    participant Client as 客户端(FiberMaintService)
    participant AlarmService as AlarmService
    participant DB as 数据库

    Client->>AlarmService: CreatePullCall(ports, include_history, expire_seconds, callback_service_addr)
    
    AlarmService->>AlarmService: 生成task_id
    
    AlarmService->>AlarmService: 保存任务到内存
    
    AlarmService-->>Client: {task_id="xxx", status="processing"}
    
    Note over AlarmService: 异步线程处理任务
    
    AlarmService->>DB: SELECT * FROM current_alarms WHERE ...
    DB-->>AlarmService: 告警数据
    
    AlarmService->>AlarmService: 更新任务状态为completed
    
    alt callback_service_addr 不为空
        AlarmService->>Client: PullCallResultCallback(task_id, status, alarms)
    end
```

---

## 7. 获取PullCall结果 (GetPullCallResult)

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant AlarmService as AlarmService

    Client->>AlarmService: GetPullCallResult(task_id)
    
    AlarmService->>AlarmService: 查找任务
    
    alt 任务存在且未过期
        AlarmService-->>Client: {status="completed", data=[...]}
    else 任务过期
        AlarmService->>AlarmService: 删除任务
        AlarmService-->>Client: {status="failed"}
    else 任务不存在
        AlarmService-->>Client: {status="failed"}
    end
```

---

## 8. 取消PullCall任务 (CancelPullCall)

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant AlarmService as AlarmService

    Client->>AlarmService: CancelPullCall(task_id)
    
    AlarmService->>AlarmService: 查找并删除任务
    
    alt 任务存在
        AlarmService-->>Client: {success=true}
    else 任务不存在
        AlarmService-->>Client: {success=false}
    end
```

---

## 9. 健康检查 (HealthCheck)

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant AlarmService as AlarmService

    Client->>AlarmService: HealthCheck()
    
    AlarmService-->>Client: {serving=true, version="1.0.0"}
```

---

## 10. 主动回调 (PullCallResultCallback)

```mermaid
sequenceDiagram
    participant AlarmService as AlarmService
    participant FiberMaint as FiberMaintService
    participant AlarmCache as 告警缓存
    participant Worker as 颜色重算Worker

    AlarmService->>AlarmService: PullCall任务完成
    AlarmService->>AlarmService: 获取callback_service_addr
    
    AlarmService->>FiberMaint: PullCallResultCallback(task_id, status, alarms)
    
    FiberMaint->>AlarmCache: 写入告警缓存
    FiberMaint->>Worker: 触发全量颜色重算
    
    FiberMaint-->>AlarmService: {success=true, message="Alarm cache synced"}
    
    Note over AlarmService: 失败时指数退避重试<br/>最多重试3次: 500ms → 1s → 2s
```

---

## 功能列表

| 功能 | RPC方法 | 说明 |
|------|---------|------|
| 上报告警 | `ReportAlarm` | 设备上报端口告警 |
| 清除告警 | `ClearAlarm` | 设备清除端口告警 |
| 获取当前告警 | `GetCurrentAlarm` | 查询指定端口的当前告警 |
| 批量获取告警 | `BatchGetCurrentAlarms` | 批量查询多个端口的告警 |
| 订阅告警事件 | `SubscribeAlarmEvents` | gRPC Stream实时推送告警事件 |
| 创建PullCall | `CreatePullCall` | 异步拉取告警数据，支持回调 |
| 获取PullCall结果 | `GetPullCallResult` | 查询PullCall任务结果 |
| 取消PullCall | `CancelPullCall` | 取消PullCall任务 |
| 主动回调 | `PullCallResultCallback` | AlarmService主动回调FiberMaintService |
| 健康检查 | `HealthCheck` | 服务健康状态检查 |