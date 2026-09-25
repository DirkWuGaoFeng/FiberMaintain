#pragma once
/**
 * @file websocket_server.h
 * @author FiberMaintain Team
 * @brief API Gateway WebSocket 事件推送服务（Boost.Beast 异步模型）
 *
 * 设计要点：
 * - 所有 WebSocket I/O 在同一个 io_context 线程上运行（async_read / async_write）
 * - 外部推送通过 post() 投递到 io_context 线程，彻底避免并发问题
 * - 不再使用 per-session std::thread，消除 self-join / terminate 风险
 */

#include <grpcpp/grpcpp.h>
#include "alarm.grpc.pb.h"
#include "board.grpc.pb.h"
#include "topology.grpc.pb.h"
#include "fiber_maint.grpc.pb.h"
#include "common/common.h"

#include <atomic>
#include <deque>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include <boost/asio.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/websocket.hpp>

class WebSocketServer {
public:
    WebSocketServer();
    ~WebSocketServer();

    bool init(int port);
    void start();
    void stop();

    int session_count();

private:
    /// 异步 WebSocket 会话：所有 I/O 在 io_context 线程上执行
    class Session : public std::enable_shared_from_this<Session> {
    public:
        explicit Session(boost::asio::ip::tcp::socket socket, WebSocketServer* server);
        ~Session();

        Session(const Session&) = delete;
        Session& operator=(const Session&) = delete;

        void run();                    // 启动会话（accept + 开始读）
        void enqueue(const std::string& message);  // 线程安全：post 到 io_context
        void close();                  // 线程安全：发起异步关闭

    private:
        void do_read();
        void on_read(boost::system::error_code ec, std::size_t bytes);
        void process_message(const std::string& msg);
        void do_write();
        void on_write(boost::system::error_code ec, std::size_t bytes);

        boost::beast::websocket::stream<boost::asio::ip::tcp::socket> ws_;
        WebSocketServer* server_;

        boost::beast::flat_buffer buffer_;
        std::deque<std::string> out_queue_;  // 仅 io_context 线程访问
        bool writing_ = false;               // 仅 io_context 线程访问
        std::atomic<bool> closed_{false};    // 可从任意线程设置
    };

    void do_accept();

    void subscribe_alarm_events();
    void subscribe_board_events();
    void subscribe_fiber_events();
    void subscribe_color_events();
    void stats_loop();

    void broadcast(const std::string& message);
    void add_session(const std::shared_ptr<Session>& session);
    void remove_session(const std::shared_ptr<Session>& session);

    int port_ = 8081;
    std::atomic<bool> running_{false};

    std::shared_ptr<fiber::alarm::AlarmService::Stub> alarm_stub_;
    std::shared_ptr<fiber::board::BoardService::Stub> board_stub_;
    std::shared_ptr<fiber::topology::TopologyService::Stub> topology_stub_;
    std::shared_ptr<fiber::maint::FiberMaintService::Stub> fiber_maint_stub_;

    boost::asio::io_context ioc_;
    std::unique_ptr<boost::asio::ip::tcp::acceptor> acceptor_;
    std::thread io_thread_;      // 运行 ioc_.run()

    std::thread alarm_sub_thread_;
    std::thread board_sub_thread_;
    std::thread fiber_sub_thread_;
    std::thread color_sub_thread_;
    std::thread stats_thread_;

    std::mutex sessions_mutex_;  // 仅用于 session_count() 跨线程读取
    std::vector<std::shared_ptr<Session>> sessions_;
};
