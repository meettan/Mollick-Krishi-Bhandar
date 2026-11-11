-- Run this only if company_payments does not already exist.
-- One row represents one partial or full payment against one purchase invoice.
CREATE TABLE IF NOT EXISTS `company_payments` (
  `id` BIGINT(20) NOT NULL AUTO_INCREMENT,
  `payment_no` VARCHAR(40) NOT NULL,
  `purchase_id` INT(11) NOT NULL,
  `company_id` INT(11) NOT NULL,
  `payment_date` DATE NOT NULL,
  `paid_amount` DECIMAL(18,2) NOT NULL DEFAULT 0.00,
  `payment_mode` VARCHAR(40) NOT NULL,
  `reference_no` VARCHAR(150) DEFAULT NULL,
  `remarks` VARCHAR(500) DEFAULT NULL,
  `created_by` INT(11) DEFAULT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_payment_no` (`payment_no`),
  KEY `idx_purchase_id` (`purchase_id`),
  KEY `idx_company_id` (`company_id`),
  KEY `idx_payment_date` (`payment_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- If the table already exists and id is not auto-increment/primary key,
-- inspect existing indexes first, then apply the appropriate ALTER TABLE.
