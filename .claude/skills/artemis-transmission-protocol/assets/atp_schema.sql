-- ATP tag registry schema

CREATE TABLE IF NOT EXISTS atp_tags (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tag_name TEXT NOT NULL UNIQUE,
  definition TEXT NOT NULL,
  category TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  added_by TEXT,
  source_context TEXT,
  examples TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS atp_tag_observations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tag_name TEXT NOT NULL,
  observed_in TEXT,
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(tag_name) REFERENCES atp_tags(tag_name)
);

CREATE TRIGGER IF NOT EXISTS atp_tags_updated_at
AFTER UPDATE ON atp_tags
FOR EACH ROW
BEGIN
  UPDATE atp_tags SET updated_at = CURRENT_TIMESTAMP WHERE id = OLD.id;
END;
