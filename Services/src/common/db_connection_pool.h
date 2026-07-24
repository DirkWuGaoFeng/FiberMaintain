#pragma once

#include <mysql/mysql.h>
#include <queue>
#include <mutex>
#include <condition_variable>
#include <string>
#include <memory>

class DBConnectionPool {
public:
    static DBConnectionPool& instance();
    
    bool init(const std::string& host, int port, const std::string& user,
              const std::string& password, const std::string& database,
              int pool_size = 10);
    
    std::shared_ptr<MYSQL> get_connection();
    void release_connection(std::shared_ptr<MYSQL> conn);
    void shutdown();
    
private:
    DBConnectionPool();
    ~DBConnectionPool();
    DBConnectionPool(const DBConnectionPool&) = delete;
    DBConnectionPool& operator=(const DBConnectionPool&) = delete;
    
    MYSQL* create_connection();
    
    std::queue<MYSQL*> pool_;
    std::mutex mutex_;
    std::condition_variable cv_;
    
    std::string host_;
    int port_;
    std::string user_;
    std::string password_;
    std::string database_;
    int pool_size_;
    bool running_;
};