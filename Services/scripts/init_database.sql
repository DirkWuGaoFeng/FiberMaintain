CREATE DATABASE IF NOT EXISTS db_board DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS db_topology DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS db_performance DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS db_alarm DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS db_fiber_maint DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE db_board;

DROP TABLE IF EXISTS boards;
CREATE TABLE boards (
    board_id INT NOT NULL,
    board_type TINYINT NOT NULL,
    ne_id INT NOT NULL,
    port_id TINYINT NOT NULL,
    port_occupied BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (board_id, port_id),
    INDEX idx_ne_id (ne_id),
    INDEX idx_type (board_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

USE db_topology;

DROP TABLE IF EXISTS fiber_connections;
CREATE TABLE fiber_connections (
    fiber_id INT NOT NULL AUTO_INCREMENT,
    src_board_id INT NOT NULL,
    src_port_id TINYINT NOT NULL,
    src_ne_id INT NOT NULL,
    dst_board_id INT NOT NULL,
    dst_port_id TINYINT NOT NULL,
    dst_ne_id INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (fiber_id),
    INDEX idx_src_board (src_board_id),
    INDEX idx_dst_board (dst_board_id),
    INDEX idx_src_port (src_board_id, src_port_id),
    INDEX idx_dst_port (dst_board_id, dst_port_id),
    INDEX idx_ne (src_ne_id, dst_ne_id),
    UNIQUE KEY uk_src_port (src_board_id, src_port_id),
    UNIQUE KEY uk_dst_port (dst_board_id, dst_port_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

USE db_performance;

DROP TABLE IF EXISTS current_performance;
CREATE TABLE current_performance (
    board_id INT NOT NULL,
    port_id TINYINT NOT NULL,
    oop_value DECIMAL(10,4) NULL,
    iop_value DECIMAL(10,4) NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (board_id, port_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS history_performance;
CREATE TABLE history_performance (
    board_id INT NOT NULL,
    port_id TINYINT NOT NULL,
    recorded_at TIMESTAMP NOT NULL,
    oop_value DECIMAL(10,4) NULL,
    iop_value DECIMAL(10,4) NULL,
    PRIMARY KEY (board_id, port_id, recorded_at),
    INDEX idx_board_time (board_id, recorded_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

USE db_alarm;

DROP TABLE IF EXISTS current_alarms;
CREATE TABLE current_alarms (
    board_id INT NOT NULL,
    port_id TINYINT NOT NULL,
    alarm_level TINYINT NOT NULL,
    raised_at TIMESTAMP NOT NULL,
    PRIMARY KEY (board_id, port_id, alarm_level),
    INDEX idx_level (alarm_level),
    INDEX idx_board (board_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS history_alarms;
CREATE TABLE history_alarms (
    id BIGINT NOT NULL AUTO_INCREMENT,
    board_id INT NOT NULL,
    port_id TINYINT NOT NULL,
    alarm_level TINYINT NOT NULL,
    raised_at TIMESTAMP NOT NULL,
    cleared_at TIMESTAMP NOT NULL,
    PRIMARY KEY (id),
    INDEX idx_board_time (board_id, raised_at),
    INDEX idx_level (alarm_level)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

USE db_fiber_maint;

DROP TABLE IF EXISTS fiber_colors;
CREATE TABLE fiber_colors (
    fiber_id INT NOT NULL,
    color TINYINT NOT NULL DEFAULT 1,
    scene_type TINYINT NOT NULL DEFAULT 1,
    scenario_case TINYINT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (fiber_id),
    INDEX idx_color (color)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS fiber_color_changes;
CREATE TABLE fiber_color_changes (
    id BIGINT NOT NULL AUTO_INCREMENT,
    fiber_id INT NOT NULL,
    old_color TINYINT NOT NULL,
    new_color TINYINT NOT NULL,
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX idx_fiber (fiber_id),
    INDEX idx_time (changed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS fiber_stats_trend;
CREATE TABLE fiber_stats_trend (
    id BIGINT NOT NULL AUTO_INCREMENT,
    timestamp TIMESTAMP NOT NULL,
    red_count INT NOT NULL DEFAULT 0,
    yellow_count INT NOT NULL DEFAULT 0,
    total_colored INT NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    INDEX idx_time (timestamp),
    UNIQUE KEY uk_timestamp (timestamp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;