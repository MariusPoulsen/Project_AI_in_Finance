CREATE TABLE ops.active_primary_research (
    singleton BOOLEAN PRIMARY KEY CHECK (singleton),
    primary_version VARCHAR NOT NULL
);
