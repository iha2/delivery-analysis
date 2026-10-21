-- When a Jira work item first reached a delivered status (Dev Done or later); NULL when it is not delivered.
ALTER TABLE work_item ADD COLUMN delivered_at TEXT;
CREATE INDEX idx_work_item_delivered_at ON work_item(delivered_at);
