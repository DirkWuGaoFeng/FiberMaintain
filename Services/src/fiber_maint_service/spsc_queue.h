#pragma once

/**
 * @file spsc_queue.h
 * @brief Phase 2 - SPSC 无锁环形队列
 *
 * Single-Producer Single-Consumer lock-free ring buffer。
 * event_process_thread_（生产者）→ output_thread_（消费者）。
 *
 * 模板参数：
 *   T        — 元素类型（如 ChangeRecord）
 *   Capacity — 环形缓冲区容量（必须为 2 的幂，默认 4096）
 */

#include <atomic>
#include <cstddef>
#include <vector>
#include <type_traits>

namespace fiber_maint {

template <typename T, size_t Capacity = 4096>
class SPSCQueue {
    static_assert((Capacity & (Capacity - 1)) == 0,
                  "Capacity must be a power of 2");
    static_assert(std::is_nothrow_move_constructible<T>::value ||
                  std::is_copy_constructible<T>::value,
                  "T must be move-constructible or copy-constructible");

public:
    SPSCQueue() : buffer_(Capacity) {}

    /// 生产者调用（event_process_thread_）
    /// @return true 成功入队，false 队列满
    bool push(const T& item) {
        size_t w = write_idx_.load(std::memory_order_relaxed);
        size_t next_w = (w + 1) & (Capacity - 1);

        if (next_w == read_idx_.load(std::memory_order_acquire)) {
            return false; // 满
        }

        buffer_[w] = item;
        write_idx_.store(next_w, std::memory_order_release);
        return true;
    }

    bool push(T&& item) {
        size_t w = write_idx_.load(std::memory_order_relaxed);
        size_t next_w = (w + 1) & (Capacity - 1);

        if (next_w == read_idx_.load(std::memory_order_acquire)) {
            return false;
        }

        buffer_[w] = std::move(item);
        write_idx_.store(next_w, std::memory_order_release);
        return true;
    }

    /// 消费者调用（output_thread_）— 批量出队
    /// @param out     输出向量（追加）
    /// @param max_count 最大出队数量
    /// @return 实际出队数量
    size_t pop_batch(std::vector<T>& out, size_t max_count) {
        size_t r = read_idx_.load(std::memory_order_relaxed);
        size_t w = write_idx_.load(std::memory_order_acquire);

        size_t count = 0;
        while (r != w && count < max_count) {
            out.push_back(std::move(buffer_[r]));
            r = (r + 1) & (Capacity - 1);
            ++count;
        }

        read_idx_.store(r, std::memory_order_release);
        return count;
    }

    /// 单个出队
    bool pop(T& item) {
        size_t r = read_idx_.load(std::memory_order_relaxed);
        if (r == write_idx_.load(std::memory_order_acquire)) {
            return false; // 空
        }
        item = std::move(buffer_[r]);
        read_idx_.store((r + 1) & (Capacity - 1),
                        std::memory_order_release);
        return true;
    }

    bool empty() const {
        return read_idx_.load(std::memory_order_acquire) ==
               write_idx_.load(std::memory_order_acquire);
    }

    size_t size() const {
        size_t r = read_idx_.load(std::memory_order_acquire);
        size_t w = write_idx_.load(std::memory_order_acquire);
        return (w - r + Capacity) & (Capacity - 1);
    }

private:
    std::vector<T>        buffer_;
    alignas(64) std::atomic<size_t> read_idx_{0};
    alignas(64) std::atomic<size_t> write_idx_{0};
};

} // namespace fiber_maint
