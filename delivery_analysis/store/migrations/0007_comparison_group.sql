-- The people a team's medians are measured against, when the user picks them. No rows means the whole active team.
CREATE TABLE comparison_member (
    team_id TEXT NOT NULL REFERENCES team(team_id),
    person_id TEXT NOT NULL REFERENCES person(person_id),
    PRIMARY KEY (team_id, person_id)
);
