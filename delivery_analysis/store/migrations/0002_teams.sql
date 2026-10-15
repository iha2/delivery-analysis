ALTER TABLE vcs_commit ADD COLUMN author_name TEXT;
ALTER TABLE vcs_commit ADD COLUMN author_email TEXT;

ALTER TABLE person ADD COLUMN excluded INTEGER NOT NULL DEFAULT 0;
ALTER TABLE person ADD COLUMN manual INTEGER NOT NULL DEFAULT 0;
ALTER TABLE identity ADD COLUMN manual INTEGER NOT NULL DEFAULT 0;

CREATE TABLE team (
    team_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    window_days INTEGER NOT NULL DEFAULT 90,
    created_at TEXT NOT NULL
);

CREATE TABLE team_repo (
    team_id TEXT NOT NULL REFERENCES team(team_id),
    repository_source TEXT NOT NULL,
    repository_id TEXT NOT NULL,
    PRIMARY KEY (team_id, repository_source, repository_id)
);

CREATE TABLE team_member (
    team_id TEXT NOT NULL REFERENCES team(team_id),
    person_id TEXT NOT NULL REFERENCES person(person_id),
    status TEXT NOT NULL CHECK (status IN ('active', 'inactive', 'excluded')),
    first_seen TEXT,
    last_commit TEXT,
    pinned INTEGER NOT NULL DEFAULT 0,
    manual INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (team_id, person_id)
);

CREATE TABLE possible_duplicate (
    person_a TEXT NOT NULL REFERENCES person(person_id),
    person_b TEXT NOT NULL REFERENCES person(person_id),
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'dismissed', 'merged')),
    PRIMARY KEY (person_a, person_b)
);
