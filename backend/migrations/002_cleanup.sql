-- 按工号清理离职学员：墓碑表阻止回写/重录，任务表逐副本记录处理结果。
CREATE TABLE IF NOT EXISTS `purged_learners` (
  `id` int NOT NULL AUTO_INCREMENT,
  `learner` varchar(60) NOT NULL,
  `requested_at` varchar(40) DEFAULT NULL,
  `requested_by` varchar(100) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `learner` (`learner`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `cleanups` (
  `id` int NOT NULL AUTO_INCREMENT,
  `learner` varchar(60) NOT NULL,
  `reason` text,
  `status` varchar(20) DEFAULT NULL,
  `copies` json DEFAULT NULL,
  `error` text,
  `requested_by` varchar(100) DEFAULT NULL,
  `requested_at` varchar(40) DEFAULT NULL,
  `completed_at` varchar(40) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_cleanups_learner` (`learner`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
