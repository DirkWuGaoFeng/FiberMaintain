#include "config.h"
#include "logger.h"
#include <fstream>
#include <sstream>
#include <algorithm>

Config::Config() {}

Config::~Config() {}

Config& Config::instance() {
    static Config instance;
    return instance;
}

bool Config::load(const std::string& filepath) {
    std::ifstream file(filepath);
    if (!file.is_open()) {
        Logger::instance().error("Cannot open config file: {}", filepath);
        return false;
    }
    
    std::lock_guard<std::mutex> lock(mutex_);
    configs_.clear();
    
    std::string line;
    while (std::getline(file, line)) {
        line.erase(std::remove_if(line.begin(), line.end(), [](int c) { return c == '\r'; }), line.end());
        
        if (line.empty() || line[0] == '#') {
            continue;
        }
        
        size_t pos = line.find('=');
        if (pos == std::string::npos) {
            continue;
        }
        
        std::string key = line.substr(0, pos);
        std::string value = line.substr(pos + 1);
        
        key.erase(key.find_last_not_of(" \t") + 1);
        key.erase(0, key.find_first_not_of(" \t"));
        value.erase(value.find_last_not_of(" \t") + 1);
        value.erase(0, value.find_first_not_of(" \t"));
        
        configs_[key] = value;
    }
    
    Logger::instance().info("Config loaded from: {}", filepath);
    return true;
}

std::string Config::get_string(const std::string& key, const std::string& default_val) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = configs_.find(key);
    if (it == configs_.end()) {
        const char* env_val = std::getenv(key.c_str());
        if (env_val != nullptr) {
            return std::string(env_val);
        }
        return default_val;
    }
    
    std::string value = it->second;
    
    if (value.size() > 2 && value[0] == '$' && value[1] == '{') {
        size_t end = value.find('}');
        if (end != std::string::npos) {
            std::string env_key = value.substr(2, end - 2);
            const char* env_val = std::getenv(env_key.c_str());
            if (env_val != nullptr) {
                return std::string(env_val);
            }
        }
    }
    
    return value;
}

int Config::get_int(const std::string& key, int default_val) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = configs_.find(key);
    if (it == configs_.end()) {
        return default_val;
    }
    try {
        return std::stoi(it->second);
    } catch (...) {
        return default_val;
    }
}

bool Config::get_bool(const std::string& key, bool default_val) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = configs_.find(key);
    if (it == configs_.end()) {
        return default_val;
    }
    std::string val = it->second;
    std::transform(val.begin(), val.end(), val.begin(), ::tolower);
    return val == "true" || val == "1" || val == "yes";
}