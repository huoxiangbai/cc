-- Additive P0 A2 admin authentication. Execute only on an explicitly authorized copy.
CREATE TABLE IF NOT EXISTS ai_agent_admin_session (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 token_digest CHAR(64) NOT NULL,
 admin_user_id BIGINT NOT NULL,
 expires_at DATETIME NOT NULL,
 revoked_at DATETIME NULL,
 create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE KEY uk_admin_session_token (token_digest),
 KEY idx_admin_session_user (admin_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
