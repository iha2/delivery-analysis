CREATE TABLE repo_selection (
    source TEXT NOT NULL,
    repository_id TEXT NOT NULL,
    workspace TEXT NOT NULL,
    slug TEXT NOT NULL,
    added_at TEXT NOT NULL,
    PRIMARY KEY (source, repository_id)
);
