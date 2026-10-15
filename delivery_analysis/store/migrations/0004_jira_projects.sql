CREATE TABLE project_selection (
    source TEXT NOT NULL,
    project_key TEXT NOT NULL,
    project_id TEXT NOT NULL,
    name TEXT,
    story_points_field TEXT,
    excluded_types TEXT NOT NULL DEFAULT 'Epic,Initiative',
    added_at TEXT NOT NULL,
    PRIMARY KEY (source, project_key)
);

CREATE TABLE status_mapping (
    source TEXT NOT NULL,
    project_key TEXT NOT NULL,
    status_name TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('todo', 'in_progress', 'in_review', 'done', 'dropped')),
    PRIMARY KEY (source, project_key, status_name)
);
