# TopologyService 功能时序图

---

## 1. 创建连纤 (CreateFiber)

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant TopologyService as TopologyService
    participant DB as 数据库
    participant FiberMaint as FiberMaintService

    Client->>TopologyService: CreateFiber(src_board_id, src_port_id, dst_board_id, dst_port_id)
    
    TopologyService->>DB: INSERT INTO fiber_connections
    DB-->>TopologyService: 返回fiber_id
    
    TopologyService->>FiberMaint: FiberEvent(event_type=FIBER_CREATED, fiber_id)
    
    TopologyService-->>Client: {success=true, fiber_id=xxx, message="Fiber created"}
```

---

## 2. 删除连纤 (DeleteFiber)

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant TopologyService as TopologyService
    participant DB as 数据库
    participant FiberMaint as FiberMaintService

    Client->>TopologyService: DeleteFiber(fiber_id)
    
    TopologyService->>DB: DELETE FROM fiber_connections WHERE fiber_id=?
    DB-->>TopologyService: 删除成功
    
    TopologyService->>FiberMaint: FiberEvent(event_type=FIBER_DELETED, fiber_id)
    
    TopologyService-->>Client: {success=true, message="Fiber deleted"}
```

---

## 3. 获取连纤信息 (GetFiber)

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant TopologyService as TopologyService
    participant DB as 数据库

    Client->>TopologyService: GetFiber(fiber_id)
    
    TopologyService->>DB: SELECT * FROM fiber_connections WHERE fiber_id=?
    DB-->>TopologyService: 连纤记录
    
    TopologyService-->>Client: {fiber={fiber_id, src_board_id, src_port_id, dst_board_id, dst_port_id}}
```

---

## 4. 批量获取连纤 (BatchGetFibers)

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant TopologyService as TopologyService
    participant DB as 数据库

    Client->>TopologyService: BatchGetFibers(fiber_ids=[1, 2, 3, ...])
    
    loop 每个fiber_id
        TopologyService->>DB: SELECT * FROM fiber_connections WHERE fiber_id=?
        DB-->>TopologyService: 连纤记录
    end
    
    TopologyService-->>Client: {results=[{found, fiber, error_message}, ...]}
```

---

## 5. 按端口获取连纤 (GetFibersByPort)

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant TopologyService as TopologyService
    participant DB as 数据库

    Client->>TopologyService: GetFibersByPort(board_id, port_id)
    
    TopologyService->>DB: SELECT * FROM fiber_connections WHERE src_board_id=? AND src_port_id=? OR dst_board_id=? AND dst_port_id=?
    DB-->>TopologyService: 连纤列表
    
    TopologyService-->>Client: {fibers=[...]}
```

---

## 6. 订阅连纤事件 (SubscribeFiberEvents)

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant TopologyService as TopologyService

    Client->>TopologyService: SubscribeFiberEvents()
    
    Note over TopologyService: 建立 gRPC Stream
    
    loop 连纤变更时
        TopologyService->>Client: FiberEvent(event_type=FIBER_CREATED/FIBER_DELETED, fiber_id)
    end
    
    Client-->>TopologyService: (Stream关闭)
```

---

## 7. 获取连纤场景信息 (GetFiberScene)

```mermaid
sequenceDiagram
    participant Client as 客户端/FiberMaintService
    participant TopologyService as TopologyService
    participant BoardService as BoardService
    participant DB as 数据库

    Client->>TopologyService: GetFiberScene(inter_ne_fiber_id=F001)
    
    TopologyService->>DB: SELECT * FROM fiber_connections WHERE fiber_id=F001
    DB-->>TopologyService: 网元间连纤信息
    
    Note over TopologyService: 判断场景类型
    
    alt 场景1: 宿端是有源盘
        TopologyService->>DB: SELECT * FROM boards WHERE board_id=src_board_id
        DB-->>TopologyService: 源端有源盘信息
        
        TopologyService->>DB: SELECT * FROM boards WHERE board_id=dst_board_id
        DB-->>TopologyService: 宿端有源盘信息
        
        TopologyService-->>Client: {scene_type=1, inter_ne_fiber=F001, src_active_board, dst_active_board}
    
    else 场景2: 宿端是无源盘
        TopologyService->>DB: SELECT * FROM boards WHERE board_id=dst_board_id
        DB-->>TopologyService: 宿端无源盘信息
        
        Note over TopologyService: 查询无源盘的网元内连纤
        
        TopologyService->>DB: SELECT * FROM fiber_connections WHERE (src_board_id=dst_board_id AND src_port_id IN (2,3)) OR (dst_board_id=dst_board_id AND dst_port_id IN (2,3))
        DB-->>TopologyService: 网元内连纤列表
        
        Note over TopologyService: 查询连接的有源盘
        
        TopologyService->>DB: SELECT * FROM boards WHERE board_id IN (connected_active_boards)
        DB-->>TopologyService: 连接的有源盘信息
        
        TopologyService-->>Client: {scene_type=2, inter_ne_fiber=F001, src_active_board, passive_boards, ne_internal_fibers, dst_active_board}
    end
```

---

## 8. 健康检查 (HealthCheck)

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant TopologyService as TopologyService

    Client->>TopologyService: HealthCheck()
    
    TopologyService-->>Client: {serving=true, version="1.0.0"}
```

---

## 功能列表

| 功能 | RPC方法 | 说明 |
|------|---------|------|
| 创建连纤 | `CreateFiber` | 创建新的连纤连接 |
| 删除连纤 | `DeleteFiber` | 删除指定连纤 |
| 获取连纤 | `GetFiber` | 查询单条连纤详情 |
| 批量获取连纤 | `BatchGetFibers` | 批量查询多条连纤 |
| 按端口查询 | `GetFibersByPort` | 查询指定端口的所有连纤 |
| 获取连纤场景 | `GetFiberScene` | 获取网元间连纤的完整场景信息(包含有源盘、无源盘、网元内连纤) |
| 订阅连纤事件 | `SubscribeFiberEvents` | gRPC Stream实时推送连纤变更事件 |
| 健康检查 | `HealthCheck` | 服务健康状态检查 |