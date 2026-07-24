#pragma once

#include <string>
#include <unordered_map>
#include <mutex>

class Config {
public:
    static Config& instance();
    
    bool load(const std::string& filepath);
    std::string get_string(const std::string& key, const std::string& default_val = "");
    int get_int(const std::string& key, int default_val = 0);
    bool get_bool(const std::string& key, bool default_val = false);
    
private:
    Config();
    ~Config();
    Config(const Config&) = delete;
    Config& operator=(const Config&) = delete;
    
    std::unordered_map<std::string, std::string> configs_;
    std::mutex mutex_;
};