CREATE TABLE claude_usage_day (
    source TEXT NOT NULL,
    day TEXT NOT NULL,
    actor_type TEXT NOT NULL CHECK (actor_type IN ('email', 'claude_api_key')),
    actor TEXT NOT NULL,
    model TEXT NOT NULL,
    cost_usd REAL NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (source, day, actor_type, actor, model)
);

CREATE TABLE claude_activity_day (
    source TEXT NOT NULL,
    day TEXT NOT NULL,
    actor_type TEXT NOT NULL CHECK (actor_type IN ('email', 'claude_api_key')),
    actor TEXT NOT NULL,
    sessions INTEGER NOT NULL DEFAULT 0,
    lines_added INTEGER NOT NULL DEFAULT 0,
    lines_removed INTEGER NOT NULL DEFAULT 0,
    commits INTEGER NOT NULL DEFAULT 0,
    pull_requests INTEGER NOT NULL DEFAULT 0,
    edits_accepted INTEGER NOT NULL DEFAULT 0,
    edits_rejected INTEGER NOT NULL DEFAULT 0,
    tool_actions TEXT NOT NULL DEFAULT '{}',
    customer_types TEXT NOT NULL DEFAULT '',
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (source, day, actor_type, actor)
);

-- Nothing on main, ui or jira writes these two tables, so they are empty and safe to recreate.
DROP TABLE token_usage;
CREATE TABLE token_usage (
    person_id TEXT NOT NULL REFERENCES person(person_id),
    day TEXT NOT NULL,
    model TEXT NOT NULL,
    purpose TEXT NOT NULL CHECK (purpose IN ('ask', 'generate', 'unclassified')),
    cost_usd REAL NOT NULL,
    total_tokens INTEGER,
    source TEXT NOT NULL,
    purpose_method TEXT NOT NULL,
    purpose_confidence TEXT NOT NULL,
    PRIMARY KEY (person_id, day, model, purpose, source)
);

DROP TABLE token_attribution;
CREATE TABLE token_attribution (
    person_id TEXT NOT NULL REFERENCES person(person_id),
    day TEXT NOT NULL,
    work_item_source TEXT NOT NULL,
    work_item_id TEXT NOT NULL,
    cost_usd REAL NOT NULL,
    weight REAL,
    evidence REAL,
    method TEXT NOT NULL,
    confidence TEXT CHECK (confidence IN ('high', 'medium', 'low')),
    reason TEXT,
    inputs TEXT NOT NULL,
    algo_version TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (person_id, day, work_item_source, work_item_id)
);

CREATE TABLE ticket_credit (
    work_item_source TEXT NOT NULL,
    work_item_id TEXT NOT NULL,
    person_id TEXT NOT NULL REFERENCES person(person_id),
    share REAL NOT NULL,
    evidence REAL NOT NULL,
    method TEXT NOT NULL,
    PRIMARY KEY (work_item_source, work_item_id, person_id)
);
