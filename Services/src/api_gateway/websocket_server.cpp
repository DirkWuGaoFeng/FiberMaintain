/**
 * @file websocket_server.cpp
 * @author FiberMaintain Team
 * @brief API Gateway WebSocket 事件推送服务（Boost.Beast 异步 I/O 模型）
 *
 * 所有 WebSocket I/O 在同一个 io_context 线程上运行：
 *   - async_accept → 新连接 → Session::run()
 *   - Session: async_read → on_read → process → async_read（循环）
 *   - enqueue() → post() → do_write → async_write → on_write（循环）
 *   - close() → post() → async_close
 *
 * 外部 gRPC 订阅线程通过 post() 投递消息到 io_context 线程。
 * 没有 per-session std::thread，彻底消除 self-join / terminate 崩溃。
 */

#include "websocket_server.h"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <sstream>

namespace beast = boost::beast;
namespace asio = boost::asio;
using tcp = asio::ip::tcp;

namespace {

constexpr int kSubscribeRetrySeconds = 3;
constexpr int kStatsIntervalSeconds = 10;
constexpr size_t kMaxOutQueueSize = 256;

std::string now_string() {
    std::time_t t = std::time(nullptr);
    struct tm tm_buf;
    localtime_r(&t, &tm_buf);
    char buf[32];
    strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", &tm_buf);
    return std::string(buf);
}

std::string alarm_level_string(fiber::common::AlarmLevel level) {
    switch (level) {
        case fiber::common::CRITICAL: return "CRITICAL";
        case fiber::common::MINOR:    return "MINOR";
        default:                      return "UNSPECIFIED";
    }
}

// FiberColor 枚举 → 字符串（与 REST 层颜色字段风格一致，供客户端直接展示）
std::string fiber_color_string(fiber::common::FiberColor color) {
    switch (color) {
        case fiber::common::GREEN:  return "GREEN";
        case fiber::common::RED:    return "RED";
        case fiber::common::YELLOW: return "YELLOW";
        default:                    return "UNSPECIFIED";
    }
}

std::string extract_command(const std::string& message) {
    for (const auto& key : {"\"action\"", "\"type\""}) {
        auto pos = message.find(key);
        if (pos == std::string::npos) continue;
        pos = message.find(':', pos + std::strlen(key));
        if (pos == std::string::npos) continue;
        auto q1 = message.find('"', pos + 1);
        if (q1 == std::string::npos) continue;
        auto q2 = message.find('"', q1 + 1);
        if (q2 == std::string::npos) continue;
        return message.substr(q1 + 1, q2 - q1 - 1);
    }
    return "";
}

}  // namespace

// =============================================================================
// Session（全异步，无 std::thread）
// =============================================================================

WebSocketServer::Session::Session(tcp::socket socket, WebSocketServer* server)
    : ws_(std::move(socket)), server_(server) {}

WebSocketServer::Session::~Session() = default;

void WebSocketServer::Session::run() {
    Logger::instance().debug("[WS] Session::run() - starting async accept");
    ws_.text(true);
    ws_.set_option(beast::websocket::stream_base::timeout::suggested(beast::role_type::server));

    auto self = shared_from_this();
    ws_.async_accept(
        [self](beast::error_code ec) {
            if (ec) {
                Logger::instance().warn("[WS] Handshake failed: {}", ec.message());
                return;
            }
            self->server_->add_session(self);
            Logger::instance().info("[WS] Client connected (total={})",
                                    self->server_->session_count());
            self->do_read();
        });
}

void WebSocketServer::Session::enqueue(const std::string& message) {
    // 可能从 gRPC 线程调用 → post 到 io_context 线程
    auto self = shared_from_this();
    asio::post(ws_.get_executor(),
        [self, msg = message]() {
            if (self->closed_) return;
            if (self->out_queue_.size() >= kMaxOutQueueSize) {
                self->out_queue_.pop_front();
            }
            self->out_queue_.push_back(msg);
            if (!self->writing_) {
                self->writing_ = true;
                self->do_write();
            }
        });
}

void WebSocketServer::Session::close() {
    // 线程安全：可从任意线程调用
    if (closed_.exchange(true)) return;

    auto self = shared_from_this();
    asio::post(ws_.get_executor(),
        [self]() {
            // 从会话列表移除（post 到 io_context 线程，避免锁竞争）
            self->server_->remove_session(self);
            beast::error_code ec;
            self->ws_.next_layer().close(ec);
        });
}

void WebSocketServer::Session::do_read() {
    if (closed_) return;
    buffer_.clear();
    auto self = shared_from_this();
    ws_.async_read(buffer_,
        [self](beast::error_code ec, std::size_t bytes) {
            self->on_read(ec, bytes);
        });
}

void WebSocketServer::Session::on_read(beast::error_code ec, std::size_t /*bytes*/) {
    if (closed_) return;

    if (ec) {
        if (ec == beast::websocket::error::closed
            || ec == boost::asio::error::operation_aborted
            || ec == boost::asio::error::eof) {
            Logger::instance().info("[WS] Client disconnected normally");
        } else {
            Logger::instance().info("[WS] Read error: {} ({})", ec.message(), ec.value());
        }
        close();
        return;
    }

    // 处理消息
    std::string message = beast::buffers_to_string(buffer_.data());
    process_message(message);

    // 继续读下一条
    do_read();
}

void WebSocketServer::Session::process_message(const std::string& msg) {
    const std::string cmd = extract_command(msg);
    if (cmd == "ping") {
        // 直接写 pong（在 io_context 线程上，安全）
        beast::error_code ec;
        ws_.write(asio::buffer("{\"type\": \"pong\"}"), ec);
        if (ec) {
            Logger::instance().info("[WS] Write pong error: {}", ec.message());
            close();
        }
    } else if (cmd == "subscribe" || cmd == "unsubscribe") {
        std::string ack = "{\"type\": \"ack\", \"action\": \"" + cmd + "\"}";
        beast::error_code ec;
        ws_.write(asio::buffer(ack), ec);
        if (ec) {
            Logger::instance().info("[WS] Write ack error: {}", ec.message());
            close();
        }
    } else {
        Logger::instance().debug("[WS] Client msg: {}", msg.substr(0, 120));
    }
}

void WebSocketServer::Session::do_write() {
    if (closed_ || out_queue_.empty()) {
        writing_ = false;
        return;
    }
    auto self = shared_from_this();
    ws_.async_write(asio::buffer(out_queue_.front()),
        [self](beast::error_code ec, std::size_t bytes) {
            self->on_write(ec, bytes);
        });
}

void WebSocketServer::Session::on_write(beast::error_code ec, std::size_t /*bytes*/) {
    if (ec) {
        Logger::instance().info("[WS] Write error: {}", ec.message());
        writing_ = false;
        close();
        return;
    }
    out_queue_.pop_front();
    do_write();
}

// =============================================================================
// WebSocketServer
// =============================================================================

WebSocketServer::WebSocketServer() = default;

WebSocketServer::~WebSocketServer() { stop(); }

bool WebSocketServer::init(int port) {
    port_ = port;

    auto creds = grpc::InsecureChannelCredentials();
    alarm_stub_ = fiber::alarm::AlarmService::NewStub(
        grpc::CreateChannel(Config::instance().get_string("alarm_service.addr", "localhost:50054"), creds));
    board_stub_ = fiber::board::BoardService::NewStub(
        grpc::CreateChannel(Config::instance().get_string("board_service.addr", "localhost:50051"), creds));
    topology_stub_ = fiber::topology::TopologyService::NewStub(
        grpc::CreateChannel(Config::instance().get_string("topology_service.addr", "localhost:50062"), creds));
    fiber_maint_stub_ = fiber::maint::FiberMaintService::NewStub(
        grpc::CreateChannel(Config::instance().get_string("fiber_maint_service.addr", "localhost:50055"), creds));

    try {
        acceptor_ = std::make_unique<tcp::acceptor>(
            ioc_, tcp::endpoint(asio::ip::make_address("0.0.0.0"), static_cast<unsigned short>(port_)));
    } catch (const std::exception& e) {
        Logger::instance().error("[WS] Failed to bind port {}: {}", port_, e.what());
        return false;
    }
    return true;
}

void WebSocketServer::start() {
    if (running_) return;
    running_ = true;

    // 异步 accept 链（在 io_context 线程上运行）
    do_accept();

    // io_context 线程：所有 WebSocket I/O 在此线程
    io_thread_ = std::thread([this]() {
        try { ioc_.run(); } catch (const std::exception& e) {
            Logger::instance().error("[WS] io_context exception: {}", e.what());
        }
    });

    // gRPC 订阅线程（保持不变）
    alarm_sub_thread_ = std::thread(&WebSocketServer::subscribe_alarm_events, this);
    board_sub_thread_ = std::thread(&WebSocketServer::subscribe_board_events, this);
    fiber_sub_thread_ = std::thread(&WebSocketServer::subscribe_fiber_events, this);
    color_sub_thread_ = std::thread(&WebSocketServer::subscribe_color_events, this);
    stats_thread_ = std::thread(&WebSocketServer::stats_loop, this);

    Logger::instance().info("API Gateway WebSocket server listening on port: {}", port_);
}

void WebSocketServer::stop() {
    if (!running_) return;
    running_ = false;

    // 关闭 acceptor → 取消 pending async_accept
    boost::system::error_code ec;
    if (acceptor_) acceptor_->close(ec);

    // 关闭所有 session（post 到 io_context 线程）
    {
        std::lock_guard<std::mutex> lock(sessions_mutex_);
        for (auto& s : sessions_) s->close();
        sessions_.clear();
    }

    // 给 io_context 时间处理取消回调
    std::this_thread::sleep_for(std::chrono::milliseconds(500));

    // 停止 io_context
    ioc_.stop();
    if (io_thread_.joinable()) io_thread_.join();

    // 等待 gRPC 线程退出（它们会在 running_=false 后自然退出）
    auto try_join = [](std::thread& t) {
        if (t.joinable()) t.join();
    };
    try_join(alarm_sub_thread_);
    try_join(board_sub_thread_);
    try_join(fiber_sub_thread_);
    try_join(color_sub_thread_);
    try_join(stats_thread_);
}

void WebSocketServer::do_accept() {
    acceptor_->async_accept(
        [this](beast::error_code ec, tcp::socket socket) {
            if (!running_) return;
            if (ec) {
                if (running_) Logger::instance().warn("[WS] Accept error: {}", ec.message());
                return;
            }
            // 创建新 Session，启动异步握手
            auto session = std::make_shared<Session>(std::move(socket), this);
            session->run();
            // 继续接受下一个连接
            do_accept();
        });
}

// ── 会话管理（sessions_ 只在 io_context 线程修改） ──

void WebSocketServer::add_session(const std::shared_ptr<Session>& session) {
    std::lock_guard<std::mutex> lock(sessions_mutex_);
    sessions_.push_back(session);
}

void WebSocketServer::remove_session(const std::shared_ptr<Session>& session) {
    std::lock_guard<std::mutex> lock(sessions_mutex_);
    sessions_.erase(std::remove(sessions_.begin(), sessions_.end(), session), sessions_.end());
}

int WebSocketServer::session_count() {
    std::lock_guard<std::mutex> lock(sessions_mutex_);
    return static_cast<int>(sessions_.size());
}

// ── 广播：post 到 io_context 线程后逐 session enqueue ──

void WebSocketServer::broadcast(const std::string& message) {
    asio::post(ioc_, [this, msg = message]() {
        // 在 io_context 线程中：安全访问 sessions_
        std::vector<std::shared_ptr<Session>> snapshot;
        {
            std::lock_guard<std::mutex> lock(sessions_mutex_);
            snapshot = sessions_;
        }
        for (auto& s : snapshot) {
            s->enqueue(msg);
        }
    });
}

// =============================================================================
// gRPC 订阅线程（保持不变，broadcast 内部已线程安全）
// =============================================================================

void WebSocketServer::subscribe_alarm_events() {
    try {
        while (running_) {
            fiber::alarm::SubscribeAlarmEventsRequest req;
            grpc::ClientContext ctx;
            std::unique_ptr<grpc::ClientReader<fiber::alarm::AlarmEvent>> reader(
                alarm_stub_->SubscribeAlarmEvents(&ctx, req));

            fiber::alarm::AlarmEvent event;
            while (running_ && reader->Read(&event)) {
                int fiber_id = 0;
                {
                    fiber::topology::GetFibersByPortRequest pr;
                    pr.set_board_id(event.board_id());
                    pr.set_port_id(event.port_id());
                    grpc::ClientContext tc;
                    fiber::topology::GetFibersByPortResponse resp;
                    if (topology_stub_->GetFibersByPort(&tc, pr, &resp).ok() && resp.fibers_size() > 0)
                        fiber_id = resp.fibers(0).fiber_id();
                }
                std::ostringstream json;
                json << "{\"type\": \"alarm\""
                     << ", \"event\": \"" << (event.event_type() == fiber::common::ALARM_CLEARED ? "ALARM_CLEARED" : "ALARM_RAISED") << "\""
                     << ", \"board_id\": " << event.board_id()
                     << ", \"port_id\": " << event.port_id()
                     << ", \"fiber_id\": " << fiber_id
                     << ", \"alarm_level\": \"" << alarm_level_string(event.alarm_level()) << "\""
                     << ", \"timestamp\": \"" << (event.timestamp().empty() ? now_string() : event.timestamp()) << "\"}";
                broadcast(json.str());
            }
            if (!running_) break;
            Logger::instance().warn("[WS] Alarm stream lost, retrying in {}s", kSubscribeRetrySeconds);
            for (int i = 0; i < kSubscribeRetrySeconds && running_; ++i)
                std::this_thread::sleep_for(std::chrono::seconds(1));
        }
    } catch (const std::exception& e) {
        Logger::instance().error("[WS] Alarm sub thread fatal: {}", e.what());
    }
}

void WebSocketServer::subscribe_board_events() {
    try {
        while (running_) {
            fiber::board::SubscribeBoardEventsRequest req;
            grpc::ClientContext ctx;
            std::unique_ptr<grpc::ClientReader<fiber::board::BoardEvent>> reader(
                board_stub_->SubscribeBoardEvents(&ctx, req));
            fiber::board::BoardEvent event;
            while (running_ && reader->Read(&event)) {
                Logger::instance().debug("Board event: type={}, board={}", event.event_type(), event.board_id());
            }
            if (!running_) break;
            for (int i = 0; i < kSubscribeRetrySeconds && running_; ++i)
                std::this_thread::sleep_for(std::chrono::seconds(1));
        }
    } catch (const std::exception& e) {
        Logger::instance().error("[WS] Board sub thread fatal: {}", e.what());
    }
}

void WebSocketServer::subscribe_fiber_events() {
    try {
        while (running_) {
            fiber::topology::SubscribeFiberEventsRequest req;
            grpc::ClientContext ctx;
            std::unique_ptr<grpc::ClientReader<fiber::topology::FiberEvent>> reader(
                topology_stub_->SubscribeFiberEvents(&ctx, req));
            fiber::topology::FiberEvent event;
            while (running_ && reader->Read(&event)) {
                const bool deleted = (event.event_type() == fiber::common::FIBER_DELETED);
                std::ostringstream json;
                json << "{\"type\": \"fiber_color\""
                     << ", \"event\": \"" << (deleted ? "FIBER_DELETED" : "FIBER_CREATED") << "\""
                     << ", \"fiber_id\": " << event.fiber_id()
                     << ", \"new_color\": \"" << (deleted ? "RED" : "GREEN") << "\""
                     << ", \"timestamp\": \"" << (event.timestamp().empty() ? now_string() : event.timestamp()) << "\"}";
                broadcast(json.str());
            }
            if (!running_) break;
            Logger::instance().warn("[WS] Fiber stream lost, retrying in {}s", kSubscribeRetrySeconds);
            for (int i = 0; i < kSubscribeRetrySeconds && running_; ++i)
                std::this_thread::sleep_for(std::chrono::seconds(1));
        }
    } catch (const std::exception& e) {
        Logger::instance().error("[WS] Fiber sub thread fatal: {}", e.what());
    }
}

// 订阅 fiber_maint 的颜色变化流，转发为 WS "fiber_color_change" 消息。
// 设计意图：光纤颜色重算是系统核心实时事件，但现有 fiber_color 消息仅覆盖
// 创建/删除场景，颜色迁移（如 GREEN→RED）需要独立事件类型供监控端增量更新。
void WebSocketServer::subscribe_color_events() {
    try {
        while (running_) {
            fiber::maint::SubscribeFiberColorEventsRequest req;
            grpc::ClientContext ctx;
            std::unique_ptr<grpc::ClientReader<fiber::maint::FiberColorEvent>> reader(
                fiber_maint_stub_->SubscribeFiberColorEvents(&ctx, req));
            fiber::maint::FiberColorEvent event;
            while (running_ && reader->Read(&event)) {
                std::ostringstream json;
                json << "{\"type\": \"fiber_color_change\""
                     << ", \"fiber_id\": " << event.fiber_id()
                     << ", \"old_color\": \"" << fiber_color_string(event.old_color()) << "\""
                     << ", \"new_color\": \"" << fiber_color_string(event.new_color()) << "\""
                     << ", \"scene_type\": " << event.scene_type()
                     << ", \"scenario_case\": " << event.scenario_case()
                     << ", \"timestamp\": \"" << (event.timestamp().empty() ? now_string() : event.timestamp()) << "\"}";
                broadcast(json.str());
            }
            if (!running_) break;
            Logger::instance().warn("[WS] Color stream lost, retrying in {}s", kSubscribeRetrySeconds);
            for (int i = 0; i < kSubscribeRetrySeconds && running_; ++i)
                std::this_thread::sleep_for(std::chrono::seconds(1));
        }
    } catch (const std::exception& e) {
        Logger::instance().error("[WS] Color sub thread fatal: {}", e.what());
    }
}

void WebSocketServer::stats_loop() {
    try {
        while (running_) {
            fiber::maint::GetFiberStatsRealtimeRequest req;
            grpc::ClientContext ctx;
            ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
            fiber::maint::GetFiberStatsRealtimeResponse resp;
            if (fiber_maint_stub_->GetFiberStatsRealtime(&ctx, req, &resp).ok()) {
                std::ostringstream json;
                json << "{\"type\": \"fiber_stats\", \"data\": {"
                     << "\"total_fibers\": " << resp.total_fibers()
                     << ", \"red_count\": " << resp.red_count()
                     << ", \"yellow_count\": " << resp.yellow_count()
                     << ", \"green_count\": " << resp.green_count()
                     << ", \"active_alarms\": " << resp.active_alarms()
                     << "}, \"timestamp\": \"" << now_string() << "\"}";
                broadcast(json.str());
            }
            for (int i = 0; i < kStatsIntervalSeconds && running_; ++i)
                std::this_thread::sleep_for(std::chrono::seconds(1));
        }
    } catch (const std::exception& e) {
        Logger::instance().error("[WS] Stats loop fatal: {}", e.what());
    }
}
