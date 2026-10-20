-- Code-weighted impact: fetched review comments and commit file changes, the code graph, and derived impact values.
CREATE TABLE review_comment (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    change_request_id TEXT NOT NULL,
    actor_account TEXT,
    created_at TEXT,
    path TEXT,
    line INTEGER,
    parent_id TEXT,
    resolved INTEGER NOT NULL DEFAULT 0,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);
CREATE INDEX review_comment_pr ON review_comment (change_request_id);

CREATE TABLE commit_file (
    repository_id TEXT NOT NULL,
    sha TEXT NOT NULL,
    path TEXT NOT NULL,
    lines_added INTEGER NOT NULL DEFAULT 0,
    lines_removed INTEGER NOT NULL DEFAULT 0,
    hunks TEXT NOT NULL DEFAULT '[]',
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (repository_id, sha, path)
);

CREATE TABLE code_file (
    repository_id TEXT NOT NULL,
    path TEXT NOT NULL,
    language TEXT,
    fan_in INTEGER NOT NULL DEFAULT 0,
    is_root INTEGER NOT NULL DEFAULT 0,
    weight REAL NOT NULL,
    snapshot_sha TEXT NOT NULL,
    built_at TEXT NOT NULL,
    PRIMARY KEY (repository_id, path)
);

CREATE TABLE pr_value (
    pr_id TEXT NOT NULL PRIMARY KEY,
    issue_id TEXT NOT NULL,
    scope REAL,
    value REAL NOT NULL,
    has_files INTEGER NOT NULL DEFAULT 0,
    built_at TEXT NOT NULL
);

CREATE TABLE comment_fix (
    comment_id TEXT NOT NULL PRIMARY KEY,
    pr_id TEXT NOT NULL,
    reviewer_key TEXT,
    owner_key TEXT,
    path TEXT,
    rel_weight REAL NOT NULL,
    reviewer_credit REAL NOT NULL,
    owner_penalty REAL NOT NULL,
    fix_sha TEXT
);

CREATE TABLE impact_share (
    issue_id TEXT NOT NULL,
    actor_key TEXT NOT NULL,
    resolved_at TEXT NOT NULL,
    delivery REAL NOT NULL DEFAULT 0,
    participation REAL NOT NULL DEFAULT 0,
    penalty REAL NOT NULL DEFAULT 0,
    scope_factor REAL NOT NULL DEFAULT 1,
    value REAL NOT NULL DEFAULT 0,
    built_at TEXT NOT NULL,
    PRIMARY KEY (issue_id, actor_key)
);
CREATE INDEX impact_share_resolved ON impact_share (resolved_at);
