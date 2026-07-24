# BoardService 功能时序图

---

## 1. 创建单盘 (CreateBoard)

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant BoardService as BoardService
    participant DB as 数据库
    participant Subscribers as 订阅者客户端

    Client->>BoardService: CreateBoard(board_id, board_type, ne_id)
    
    BoardService->>DB: INSERT INTO boards (board_id, board_type, ne_id)
    DB-->>BoardService: 插入成功
    
    BoardService->>Subscribers: BoardEvent(event_type=BOARD_CREATED, board_id, board_type, ne_id)
    
    BoardService-->>Client: {success=true, message="Board created"}
```

---

## 2. 删除单盘 (DeleteBoard)

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant BoardService as BoardService
    participant Topology as TopologyService
    participant DB as 数据库
    participant Subscribers as 订阅者客户端

    Client->>BoardService: DeleteBoard(board_id)
    
    BoardService->>Topology: GetBoardFibers(board_id)
    Topology-->>BoardService: [fiber_id1, fiber_id2, ...]
    
    loop 每个关联连纤
        BoardService->>Topology: DeleteFiber(fiber_id)
        Topology-->>BoardService: 删除成功
    end
    
    BoardService->>DB: DELETE FROM boards WHERE board_id=?
    DB-->>BoardService: 删除成功
    
    BoardService->>Subscribers: BoardEvent(event_type=BOARD_DELETED, board_id)
    
    BoardService-->>Client: {success=true, message="Board deleted", deleted_fiber_ids=[...]}
```

---

## 3. 获取单盘信息 (GetBoard)

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant BoardService as BoardService
    participant DB as 数据库

    Client->>BoardService: GetBoard(board_id)
    
    BoardService->>DB: SELECT * FROM boards WHERE board_id=?
    DB-->>BoardService: 单盘记录
    
    BoardService-->>Client: {board={board_id, board_type, ne_id}}
```

---

## 4. 批量获取单盘 (BatchGetBoards)

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant BoardService as BoardService
    participant DB as 数据库

    Client->>BoardService: BatchGetBoards(board_ids=[1, 2, 3, ...])
    
    loop 每个board_id
        BoardService->>DB: SELECT * FROM boards WHERE board_id=?
        DB-->>BoardService: 单盘记录
    end
    
    BoardService-->>Client: {results=[{found, board, error_message}, ...]}
```

---

## 5. 获取单盘连纤 (GetBoardFibers)

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant BoardService as BoardService
    participant Topology as TopologyService

    Client->>BoardService: GetBoardFibers(board_id)
    
    BoardService->>Topology: GetFibersByPort(board_id, port_id)
    Topology-->>BoardService: 连纤列表
    
    BoardService-->>Client: {fibers=[...]}
```

---

## 6. 订阅单盘事件 (SubscribeBoardEvents)

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant BoardService as BoardService

    Client->>BoardService: SubscribeBoardEvents()
    
    Note over BoardService: 建立 gRPC Stream
    
    loop 单盘变更时
        BoardService->>Client: BoardEvent(event_type=BOARD_CREATED/BOARD_DELETED, board_id, board_type, ne_id)
    end
    
    Client-->>BoardService: (Stream关闭)
```

---

## 7. 更新端口占用状态 (UpdatePortOccupied)

```mermaid
sequenceDiagram
    participant Client as 客户端(TopologyService)
    participant BoardService as BoardService
    participant DB as 数据库

    Client->>BoardService: UpdatePortOccupied(board_id, port_id, occupied)
    
    BoardService->>DB: UPDATE ports SET occupied=? WHERE board_id=? AND port_id=?
    DB-->>BoardService: 更新成功
    
    BoardService-->>Client: {success=true}
```

---

## 8. 获取所有单盘 (ListBoards)

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant BoardService as BoardService
    participant DB as 数据库

    Client->>BoardService: ListBoards()
    
    BoardService->>DB: SELECT * FROM boards
    DB-->>BoardService: 所有单盘记录列表
    
    BoardService-->>Client: {boards=[{board_id, board_type, ne_id}, ...]}
```

---

## 9. 健康检查 (HealthCheck)

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant BoardService as BoardService

    Client->>BoardService: HealthCheck()
    
    BoardService-->>Client: {serving=true, version="1.0.0"}
```

---

## 功能列表

| 功能 | RPC方法 | 说明 |
|------|---------|------|
| 创建单盘 | `CreateBoard` | 创建新的设备单盘 |
| 删除单盘 | `DeleteBoard` | 删除指定单盘，级联删除关联连纤 |
| 获取单盘 | `GetBoard` | 查询单盘详情 |
| 批量获取单盘 | `BatchGetBoards` | 批量查询多个单盘 |
| 获取所有单盘 | `ListBoards` | 获取所有单盘列表 |
| 获取单盘连纤 | `GetBoardFibers` | 查询单盘关联的所有连纤 |
| 订阅单盘事件 | `SubscribeBoardEvents` | gRPC Stream实时推送单盘变更事件 |
| 更新端口占用 | `UpdatePortOccupied` | 更新端口占用状态 |
| 健康检查 | `HealthCheck` | 服务健康状态检查 |