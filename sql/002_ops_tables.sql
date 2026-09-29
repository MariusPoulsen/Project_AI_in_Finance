CREATE TABLE ops.job_runs (
    run_id VARCHAR PRIMARY KEY,
    job VARCHAR NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status VARCHAR NOT NULL CHECK (status IN ('RUNNING', 'SUCCESS', 'FAILED')),
    config_hash VARCHAR NOT NULL,
    config_snapshot JSON NOT NULL,
    git_commit VARCHAR NOT NULL,
    dataset_version VARCHAR NOT NULL,
    record_count BIGINT NOT NULL DEFAULT 0 CHECK (record_count >= 0),
    error_type VARCHAR,
    CHECK ((status = 'RUNNING' AND finished_at IS NULL) OR
           (status <> 'RUNNING' AND finished_at IS NOT NULL))
);

CREATE TABLE ops.dataset_versions (
    dataset_version VARCHAR PRIMARY KEY,
    manifest_path VARCHAR NOT NULL,
    checksum VARCHAR NOT NULL,
    run_id VARCHAR NOT NULL REFERENCES ops.job_runs(run_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);

CREATE TABLE ops.artifact_registry (
    artifact_id VARCHAR PRIMARY KEY,
    kind VARCHAR NOT NULL,
    version VARCHAR NOT NULL,
    path VARCHAR NOT NULL UNIQUE,
    checksum VARCHAR NOT NULL,
    run_id VARCHAR NOT NULL REFERENCES ops.job_runs(run_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);

CREATE TABLE ops.source_health (
    source VARCHAR PRIMARY KEY,
    status VARCHAR NOT NULL CHECK (status IN ('OK', 'FAILED', 'UNKNOWN')),
    checked_at TIMESTAMPTZ NOT NULL,
    last_success_at TIMESTAMPTZ,
    run_id VARCHAR NOT NULL REFERENCES ops.job_runs(run_id),
    error_type VARCHAR
);
