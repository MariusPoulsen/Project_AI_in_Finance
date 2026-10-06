CREATE TABLE analytics.research_versions (
    research_version VARCHAR PRIMARY KEY,
    stage VARCHAR NOT NULL,
    protocol_hash VARCHAR NOT NULL,
    manifest_path VARCHAR NOT NULL,
    checksum VARCHAR NOT NULL,
    run_id VARCHAR NOT NULL
);
