#include "db_connection_pool.h"
#include "logger.h"

DBConnectionPool::DBConnectionPool() : pool_size_(10), running_(false) {
    mysql_library_init(0, nullptr, nullptr);
}

DBConnectionPool::~DBConnectionPool() {
    shutdown();
    mysql_library_end();
}

DBConnectionPool& DBConnectionPool::instance() {
    static DBConnectionPool instance;
    return instance;
}

bool DBConnectionPool::init(const std::string& host, int port, const std::string& user,
                            const std::string& password, const std::string& database,
                            int pool_size) {
    host_ = host;
    port_ = port;
    user_ = user;
    password_ = password;
    database_ = database;
    pool_size_ = pool_size;
    running_ = true;
    
    for (int i = 0; i < pool_size_; ++i) {
        MYSQL* conn = create_connection();
        if (conn) {
            pool_.push(conn);
        }
    }
    
    Logger::instance().info("DB connection pool initialized, size: {}", pool_.size());
    return !pool_.empty();
}

MYSQL* DBConnectionPool::create_connection() {
    MYSQL* conn = mysql_init(nullptr);
    if (!conn) {
        Logger::instance().error("mysql_init failed");
        return nullptr;
    }
    
    mysql_options(conn, MYSQL_SET_CHARSET_NAME, "utf8mb4");
    
    if (!mysql_real_connect(conn, host_.c_str(), user_.c_str(), password_.c_str(),
                            database_.c_str(), port_, nullptr, 0)) {
        Logger::instance().error("mysql_real_connect failed: {}", mysql_error(conn));
        mysql_close(conn);
        return nullptr;
    }
    
    return conn;
}

std::shared_ptr<MYSQL> DBConnectionPool::get_connection() {
    std::unique_lock<std::mutex> lock(mutex_);
    cv_.wait(lock, [this]() { return !pool_.empty() || !running_; });
    
    if (!running_) {
        return nullptr;
    }
    
    MYSQL* conn = pool_.front();
    pool_.pop();
    
    if (mysql_ping(conn) != 0) {
        Logger::instance().warn("Connection lost, reconnecting...");
        mysql_close(conn);
        conn = create_connection();
        if (!conn) {
            cv_.notify_all();
            return nullptr;
        }
    }
    
    return std::shared_ptr<MYSQL>(conn, [this](MYSQL* c) {
        this->release_connection(std::shared_ptr<MYSQL>(c, [](MYSQL*) {}));
    });
}

void DBConnectionPool::release_connection(std::shared_ptr<MYSQL> conn) {
    if (!conn) return;
    
    std::lock_guard<std::mutex> lock(mutex_);
    if (running_) {
        pool_.push(conn.get());
        conn.reset();
        cv_.notify_one();
    }
}

void DBConnectionPool::shutdown() {
    std::lock_guard<std::mutex> lock(mutex_);
    running_ = false;
    cv_.notify_all();
    
    while (!pool_.empty()) {
        MYSQL* conn = pool_.front();
        pool_.pop();
        mysql_close(conn);
    }
    
    Logger::instance().info("DB connection pool shutdown");
}