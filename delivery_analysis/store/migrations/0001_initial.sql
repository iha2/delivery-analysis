CREATE TABLE person (
    person_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    team TEXT
);

CREATE TABLE identity (
    source TEXT NOT NULL,
    account_id TEXT NOT NULL,
    person_id TEXT REFERENCES person(person_id),
    label TEXT,
    PRIMARY KEY (source, account_id)
);

CREATE TABLE repository (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    workspace TEXT,
    name TEXT,
    default_branch TEXT,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);

CREATE TABLE change_request (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    repository_id TEXT,
    number TEXT,
    author_account TEXT,
    branch TEXT,
    title TEXT,
    state TEXT,
    created_at TEXT,
    merged_at TEXT,
    closed_at TEXT,
    files_changed INTEGER,
    commit_count INTEGER,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);

CREATE TABLE change_event (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    change_request_id TEXT,
    type TEXT,
    actor_account TEXT,
    occurred_at TEXT,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);

CREATE TABLE vcs_commit (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    repository_id TEXT,
    sha TEXT,
    author_account TEXT,
    committed_at TEXT,
    change_request_id TEXT,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);

CREATE TABLE work_item (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    project TEXT,
    key TEXT,
    type TEXT,
    summary TEXT,
    assignee_account TEXT,
    reporter_account TEXT,
    status TEXT,
    status_category TEXT,
    created_at TEXT,
    started_at TEXT,
    resolved_at TEXT,
    story_points REAL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);

CREATE TABLE work_item_transition (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    work_item_id TEXT,
    from_status TEXT,
    to_status TEXT,
    actor_account TEXT,
    occurred_at TEXT,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);

CREATE TABLE document (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    space TEXT,
    title TEXT,
    author_account TEXT,
    created_at TEXT,
    modified_at TEXT,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);

CREATE TABLE document_version (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    document_id TEXT,
    version INTEGER,
    author_account TEXT,
    occurred_at TEXT,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);

CREATE TABLE link (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    from_kind TEXT,
    from_id TEXT,
    to_kind TEXT,
    to_id TEXT,
    kind TEXT,
    found_by TEXT,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);

CREATE TABLE property (
    record_kind TEXT NOT NULL,
    record_id TEXT NOT NULL,
    name TEXT NOT NULL,
    value TEXT,
    source_field_id TEXT,
    PRIMARY KEY (record_kind, record_id, name)
);

CREATE TABLE token_usage (
    person_id TEXT NOT NULL,
    day TEXT NOT NULL,
    model TEXT NOT NULL,
    purpose TEXT NOT NULL DEFAULT 'unclassified',
    cost_usd REAL NOT NULL,
    total_tokens INTEGER,
    source TEXT NOT NULL,
    PRIMARY KEY (person_id, day, model, purpose, source)
);

CREATE TABLE token_attribution (
    person_id TEXT NOT NULL,
    work_item TEXT NOT NULL,
    day TEXT NOT NULL,
    cost_usd REAL NOT NULL,
    method TEXT NOT NULL,
    confidence TEXT,
    PRIMARY KEY (person_id, work_item, day, method)
);

CREATE TABLE raw_payload (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    json TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (source, source_id, kind)
);

CREATE TABLE sync_state (
    connector TEXT NOT NULL,
    scope TEXT NOT NULL,
    cursor TEXT,
    last_run TEXT,
    status TEXT NOT NULL DEFAULT 'never',
    error TEXT,
    records INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (connector, scope)
);
