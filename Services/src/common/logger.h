#pragma once

#include <string>
#include <sstream>
#include <iostream>
#include <mutex>
#include <ctime>

enum class LogLevel {
    TRACE,
    DEBUG,
    INFO,
    WARN,
    ERROR
};

class Logger {
public:
    static Logger& instance();
    
    void set_level(LogLevel level);
    void log(LogLevel level, const std::string& message);
    
    void trace(const char* message) { log(LogLevel::TRACE, message); }
    void debug(const char* message) { log(LogLevel::DEBUG, message); }
    void info(const char* message) { log(LogLevel::INFO, message); }
    void warn(const char* message) { log(LogLevel::WARN, message); }
    void error(const char* message) { log(LogLevel::ERROR, message); }
    
    template<typename T>
    void trace(const char* format, T v1) { log(LogLevel::TRACE, format_str(format, v1)); }
    template<typename T>
    void debug(const char* format, T v1) { log(LogLevel::DEBUG, format_str(format, v1)); }
    template<typename T>
    void info(const char* format, T v1) { log(LogLevel::INFO, format_str(format, v1)); }
    template<typename T>
    void warn(const char* format, T v1) { log(LogLevel::WARN, format_str(format, v1)); }
    template<typename T>
    void error(const char* format, T v1) { log(LogLevel::ERROR, format_str(format, v1)); }
    
    template<typename T, typename U>
    void trace(const char* format, T v1, U v2) { log(LogLevel::TRACE, format_str(format, v1, v2)); }
    template<typename T, typename U>
    void debug(const char* format, T v1, U v2) { log(LogLevel::DEBUG, format_str(format, v1, v2)); }
    template<typename T, typename U>
    void info(const char* format, T v1, U v2) { log(LogLevel::INFO, format_str(format, v1, v2)); }
    template<typename T, typename U>
    void warn(const char* format, T v1, U v2) { log(LogLevel::WARN, format_str(format, v1, v2)); }
    template<typename T, typename U>
    void error(const char* format, T v1, U v2) { log(LogLevel::ERROR, format_str(format, v1, v2)); }
    
    template<typename T, typename U, typename V>
    void trace(const char* format, T v1, U v2, V v3) { log(LogLevel::TRACE, format_str(format, v1, v2, v3)); }
    template<typename T, typename U, typename V>
    void debug(const char* format, T v1, U v2, V v3) { log(LogLevel::DEBUG, format_str(format, v1, v2, v3)); }
    template<typename T, typename U, typename V>
    void info(const char* format, T v1, U v2, V v3) { log(LogLevel::INFO, format_str(format, v1, v2, v3)); }
    template<typename T, typename U, typename V>
    void warn(const char* format, T v1, U v2, V v3) { log(LogLevel::WARN, format_str(format, v1, v2, v3)); }
    template<typename T, typename U, typename V>
    void error(const char* format, T v1, U v2, V v3) { log(LogLevel::ERROR, format_str(format, v1, v2, v3)); }
    
    template<typename T, typename U, typename V, typename W>
    void trace(const char* format, T v1, U v2, V v3, W v4) { log(LogLevel::TRACE, format_str(format, v1, v2, v3, v4)); }
    template<typename T, typename U, typename V, typename W>
    void debug(const char* format, T v1, U v2, V v3, W v4) { log(LogLevel::DEBUG, format_str(format, v1, v2, v3, v4)); }
    template<typename T, typename U, typename V, typename W>
    void info(const char* format, T v1, U v2, V v3, W v4) { log(LogLevel::INFO, format_str(format, v1, v2, v3, v4)); }
    template<typename T, typename U, typename V, typename W>
    void warn(const char* format, T v1, U v2, V v3, W v4) { log(LogLevel::WARN, format_str(format, v1, v2, v3, v4)); }
    template<typename T, typename U, typename V, typename W>
    void error(const char* format, T v1, U v2, V v3, W v4) { log(LogLevel::ERROR, format_str(format, v1, v2, v3, v4)); }
    
private:
    Logger();
    ~Logger();
    Logger(const Logger&) = delete;
    Logger& operator=(const Logger&) = delete;
    
    std::string get_timestamp();
    std::string level_to_string(LogLevel level);
    
    std::string format_str(const std::string& s) { return s; }
    
    template<typename T>
    std::string format_str(const std::string& format, T v1) {
        size_t pos = format.find("{}");
        if (pos == std::string::npos) return format;
        std::stringstream ss;
        ss << format.substr(0, pos) << v1 << format.substr(pos + 2);
        return ss.str();
    }
    
    template<typename T, typename U>
    std::string format_str(const std::string& format, T v1, U v2) {
        size_t pos = format.find("{}");
        if (pos == std::string::npos) return format;
        std::string s = format_str(format.substr(0, pos) + "{}" + format.substr(pos + 2), v1);
        return format_str(s, v2);
    }
    
    template<typename T, typename U, typename V>
    std::string format_str(const std::string& format, T v1, U v2, V v3) {
        std::string s = format_str(format, v1, v2);
        return format_str(s, v3);
    }
    
    template<typename T, typename U, typename V, typename W>
    std::string format_str(const std::string& format, T v1, U v2, V v3, W v4) {
        std::string s = format_str(format, v1, v2, v3);
        return format_str(s, v4);
    }
    
    LogLevel level_;
    std::mutex mutex_;
};
