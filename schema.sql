-- Khumaira AI Database Schema Migration
-- Run this SQL against your database to add the new columns and tables.

-- 1. Add timestamp to chat_history (if not exists)
ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

-- 2. Add label column to conversation_control
ALTER TABLE conversation_control ADD COLUMN IF NOT EXISTS label VARCHAR(50) DEFAULT NULL;

-- 3. Audit log table
CREATE TABLE IF NOT EXISTS audit_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    table_name VARCHAR(50) NOT NULL,
    action VARCHAR(20) NOT NULL,
    chat_id VARCHAR(50),
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4. Auto-reply rules table
CREATE TABLE IF NOT EXISTS auto_reply_rules (
    id INT AUTO_INCREMENT PRIMARY KEY,
    keyword VARCHAR(255) NOT NULL,
    response TEXT NOT NULL,
    is_active TINYINT(1) DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5. Message templates table
CREATE TABLE IF NOT EXISTS message_templates (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 6. Broadcast log table
CREATE TABLE IF NOT EXISTS broadcast_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    message TEXT NOT NULL,
    recipients_count INT DEFAULT 0,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 7. AI settings table
CREATE TABLE IF NOT EXISTS ai_settings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    provider VARCHAR(50) NOT NULL DEFAULT 'gemini',
    model_name VARCHAR(100) DEFAULT NULL,
    api_key VARCHAR(255) DEFAULT NULL,
    system_prompt TEXT DEFAULT NULL,
    is_active TINYINT(1) DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Insert default gemini setting if not exists
INSERT IGNORE INTO ai_settings (provider, model_name, is_active) VALUES ('gemini', 'gemini-1.5-flash', 0);
