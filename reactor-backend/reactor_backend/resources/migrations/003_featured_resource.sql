CREATE TABLE IF NOT EXISTS reactor_featured_resource (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 featured_id VARCHAR(64) NOT NULL,
 resource_path VARCHAR(1024) NOT NULL,
 path_digest CHAR(64) NOT NULL,
 UNIQUE KEY uk_featured_path(featured_id,path_digest)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
