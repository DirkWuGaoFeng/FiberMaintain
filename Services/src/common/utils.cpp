#include "utils.h"

std::string get_current_timestamp() {
    time_t now = time(nullptr);
    struct tm tm_info;
    localtime_r(&now, &tm_info);
    
    char buffer[32];
    strftime(buffer, sizeof(buffer), "%Y-%m-%d %H:%M:%S", &tm_info);
    return buffer;
}

std::string format_time(time_t t) {
    struct tm tm_info;
    localtime_r(&t, &tm_info);
    
    char buffer[32];
    strftime(buffer, sizeof(buffer), "%Y-%m-%d %H:%M:%S", &tm_info);
    return buffer;
}

bool parse_time(const std::string& str, time_t& out_t) {
    struct tm tm_info = {0};
    
    if (strptime(str.c_str(), "%Y-%m-%d %H:%M:%S", &tm_info) == nullptr) {
        return false;
    }
    
    out_t = mktime(&tm_info);
    return true;
}