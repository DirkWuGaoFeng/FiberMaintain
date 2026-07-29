/**
 * @file output_layer.cpp
 * @brief Phase 2 - 异步输出层实现
 */

#include "output_layer.h"
#include "common/common.h"
#include <chrono>
#include <fstream>

namespace fiber_maint {

OutputThread::OutputThread() = default;

OutputThread::~OutputThread() {
    shutdown();
}

void OutputThread::bind(
        SPSCQueue<ChangeRecord>* queue,
        std::shared_mutex* color_mutex,
        std::unordered_map<int32_t, ColorContext>* color_contexts) {
    queue_ = queue;
    color_mutex_ = color_mutex;
    color_contexts_ = color_contexts;
}

void OutputThread::set_push_callback(ColorPushCallback cb) {
    push_cb_ = std::move(cb);
}

void OutputThread::start(std::atomic<bool>* running) {
    running_ = running;
    thread_ = std::thread(&OutputThread::run, this);
}

void OutputThread::shutdown() {
    if (thread_.joinable()) {
        thread_.join();
    }
}

void OutputThread::enqueue(ChangeRecord record) {
    if (queue_) {
        queue_->push(std::move(record));
    }
}

void OutputThread::run() {
    constexpr size_t BATCH_SIZE = 256;
    std::vector<ChangeRecord> batch;
    batch.reserve(BATCH_SIZE);

    while (running_ && *running_) {
        batch.clear();
        size_t n = queue_->pop_batch(batch, BATCH_SIZE);

        if (n == 0) {
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
            continue;
        }

        // 同 fiber 去重（GREEN→RED→YELLOW 合并为 GREEN→YELLOW）
        for (auto& rec : batch) {
            dedup_buffer_[rec.fiber_id] = rec;
        }

        // 转出去重后的列表
        std::vector<ChangeRecord> deduped;
        deduped.reserve(dedup_buffer_.size());
        for (auto& [fid, rec] : dedup_buffer_) {
            deduped.push_back(std::move(rec));
        }
        dedup_buffer_.clear();

        // 更新 color_contexts_（写锁，<1ms）
        if (color_mutex_ && color_contexts_) {
            std::unique_lock<std::shared_mutex> lock(*color_mutex_);
            for (const auto& rec : deduped) {
                auto& ctx = (*color_contexts_)[rec.fiber_id];
                ctx.color = rec.new_color;
                ctx.scene_type = rec.scene_type;
                ctx.scenario_case = rec.scenario_case;
                ctx.last_update_ts = rec.timestamp_ms;
                Logger::instance().info("OutputLayer: updated color context for fiber {}{}",
                    rec.fiber_id, std::to_string(static_cast<int8_t>(rec.new_color)));
            }
        }

        // 批量写 DB
        if (!batch_write_db(deduped)) {
            // DB 失败 → WAL 兜底
            write_wal(deduped);
        }

        // 推送事件
        if (push_cb_) {
            for (const auto& rec : deduped) {
                push_cb_(rec);
            }
        }
    }

    // 关闭时刷写剩余
    batch.clear();
    while (queue_->pop_batch(batch, BATCH_SIZE) > 0) {
        if (!batch_write_db(batch)) {
            write_wal(batch);
        }
        batch.clear();
    }
}

bool OutputThread::batch_write_db(std::vector<ChangeRecord>& records) {
    constexpr int MAX_RETRIES = 3;
    constexpr int RETRY_DELAYS[] = {100, 200, 400}; // ms

    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) return false;

    for (int attempt = 0; attempt < MAX_RETRIES; ++attempt) {
        bool success = true;

        // 批量写入（简化：逐条 INSERT，实际可用 prepared batch）
        for (const auto& rec : records) {
            try {
                std::string sql = "INSERT INTO fiber_color_changes "
                    "(fiber_id, old_color, new_color, changed_at) VALUES ("
                    + std::to_string(rec.fiber_id) + ", "
                    + std::to_string(static_cast<int>(rec.old_color)) + ", "
                    + std::to_string(static_cast<int>(rec.new_color))
                    + ", NOW())";
                if (mysql_query(conn.get(), sql.c_str()) != 0) {
                    Logger::instance().error("OutputLayer: DB fiber_color_changes write failed: {}", mysql_error(conn.get()));
                    success = false;
                    break;
                }

                //只存有颜色连纤
                if (rec.new_color != FiberColor::GREEN)
                {
                    sql = "INSERT INTO fiber_colors "
                        "(fiber_id, color, scene_type, scenario_case, updated_at) VALUES ("
                        + std::to_string(rec.fiber_id) + ", "
                        + std::to_string(static_cast<int>(rec.new_color)) + ", "
                        + std::to_string(static_cast<int>(rec.scene_type)) + ", "
                        + std::to_string(static_cast<int>(rec.scenario_case))
                        + ", NOW())" + " ON DUPLICATE KEY UPDATE "
                        + "color         = VALUES(color), "
                        + "scene_type    = VALUES(scene_type), "
                        + "scenario_case = VALUES(scenario_case), "
                        + "updated_at    = VALUES(updated_at);";
                }
                else
                {
                    sql = "DELETE FROM fiber_colors WHERE fiber_id = "
                        + std::to_string(rec.fiber_id);
                }

                if (mysql_query(conn.get(), sql.c_str()) != 0) {
                    Logger::instance().error("OutputLayer: DB fiber_color write failed: {}", mysql_error(conn.get()));
                    success = false;
                    break;
                }

            } catch (...) {
                success = false;
                break;
            }
        }

        if (success) return true;

        // 重试等待
        if (attempt < MAX_RETRIES - 1) {
            std::this_thread::sleep_for(
                std::chrono::milliseconds(RETRY_DELAYS[attempt]));
        }
    }

    Logger::instance().error("OutputLayer: DB write failed after {} retries",
        MAX_RETRIES);
    return false;
}

void OutputThread::write_wal(const std::vector<ChangeRecord>& records) {
    try {
        std::ofstream wal("data/wal_color_changes.log",
                          std::ios::app);
        if (!wal.is_open()) return;

        for (const auto& rec : records) {
            wal << rec.timestamp_ms << ","
                << rec.fiber_id << ","
                << static_cast<int>(rec.old_color) << ","
                << static_cast<int>(rec.new_color) << ","
                << static_cast<int>(rec.scene_type) << ","
                << static_cast<int>(rec.scenario_case) << "\n";
        }
        wal.flush();
        Logger::instance().warn("OutputLayer: wrote {} records to WAL",
            records.size());
    } catch (const std::exception& e) {
        Logger::instance().error("OutputLayer: WAL write failed: {}", e.what());
    }
}

} // namespace fiber_maint
