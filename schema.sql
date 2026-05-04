CREATE TABLE `Organization` (
  `id` INT PRIMARY KEY,
  `name` VARCHAR(100) NOT NULL
);

CREATE TABLE `User` (
  `id` INT PRIMARY KEY,
  `org_id` INT NOT NULL,
  `name` VARCHAR(100) NOT NULL,
  `email` VARCHAR(120) NOT NULL,
  `password_hash` VARCHAR(255) NOT NULL,
  `otp` VARCHAR(6),
  `is_verified` BOOLEAN,
  `role` VARCHAR(20) NOT NULL
);

CREATE TABLE `Bot` (
  `id` INT PRIMARY KEY,
  `org_id` INT NOT NULL,
  `created_by` INT NOT NULL,
  `bot_name` VARCHAR(100) NOT NULL,
  `store_id` VARCHAR(255),
  `visibility` VARCHAR(10) NOT NULL,
  `access_key` VARCHAR(4),
  `allowed_domains` VARCHAR(255),
  `bot_type` VARCHAR(50) NOT NULL,
  `theme_color` VARCHAR(20) NOT NULL,
  `system_prompt` TEXT
);

CREATE TABLE `Document` (
  `id` INT PRIMARY KEY,
  `bot_id` INT NOT NULL,
  `filename` VARCHAR(255) NOT NULL
);

CREATE TABLE `Scrape` (
  `id` INT PRIMARY KEY,
  `bot_id` INT NOT NULL,
  `url` VARCHAR(2048) NOT NULL,
  `status` VARCHAR(20) NOT NULL,
  `logs` TEXT,
  `error_message` TEXT,
  `created_at` TIMESTAMP,
  `completed_at` TIMESTAMP
);

CREATE TABLE `Bot_UI` (
  `id` INT PRIMARY KEY,
  `bot_id` INT NOT NULL,
  `theme_color` VARCHAR(20) NOT NULL,
  `theme_mode` VARCHAR(10) NOT NULL,
  `glass_opacity` INT,
  `glass_blur` INT,
  `avatar_path` VARCHAR(255),
  `google_sheet_id` VARCHAR(255),
  `is_sheets_enabled` BOOLEAN
);

ALTER TABLE `User` ADD FOREIGN KEY (`org_id`) REFERENCES `Organization` (`id`);
ALTER TABLE `Bot` ADD FOREIGN KEY (`org_id`) REFERENCES `Organization` (`id`);
ALTER TABLE `Bot` ADD FOREIGN KEY (`created_by`) REFERENCES `User` (`id`);
ALTER TABLE `Document` ADD FOREIGN KEY (`bot_id`) REFERENCES `Bot` (`id`);
ALTER TABLE `Scrape` ADD FOREIGN KEY (`bot_id`) REFERENCES `Bot` (`id`);
ALTER TABLE `Bot_UI` ADD FOREIGN KEY (`bot_id`) REFERENCES `Bot` (`id`);