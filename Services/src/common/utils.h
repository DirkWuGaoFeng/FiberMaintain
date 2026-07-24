#pragma once

#include <string>
#include <ctime>
#include <sstream>

std::string get_current_timestamp();
std::string format_time(time_t t);
bool parse_time(const std::string& str, time_t& out_t);