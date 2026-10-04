-- Additive migration. Run explicitly on an authorized database, never at startup.
CREATE TABLE IF NOT EXISTS reactor_private_resource_owner (
  resource_kind VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  resource_key VARCHAR(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  visitor_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  parent_key VARCHAR(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY(resource_kind,resource_key),
  KEY owner_kind(visitor_id,resource_kind)
) ENGINE=InnoDB;
