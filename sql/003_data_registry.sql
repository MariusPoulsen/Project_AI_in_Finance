CREATE TABLE ops.ingestion_runs (
    run_id VARCHAR NOT NULL REFERENCES ops.job_runs(run_id),
    source_snapshot_id VARCHAR NOT NULL,
    dataset_id VARCHAR NOT NULL,
    source_provider VARCHAR NOT NULL,
    source_url VARCHAR NOT NULL,
    parameters JSON NOT NULL,
    library_version VARCHAR NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL,
    raw_file_path VARCHAR NOT NULL,
    checksum VARCHAR NOT NULL,
    bytes BIGINT NOT NULL,
    row_count BIGINT,
    http_status INTEGER,
    result_status VARCHAR NOT NULL,
    data_snapshot_id VARCHAR NOT NULL,
    PRIMARY KEY (run_id, raw_file_path)
);

CREATE TABLE ops.data_quality_results (
    run_id VARCHAR NOT NULL REFERENCES ops.job_runs(run_id),
    data_snapshot_id VARCHAR NOT NULL,
    dataset VARCHAR NOT NULL,
    check_name VARCHAR NOT NULL,
    severity VARCHAR NOT NULL CHECK (severity IN ('INFO', 'WARN', 'FAIL')),
    affected_rows BIGINT NOT NULL,
    message VARCHAR NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);

CREATE TABLE ops.active_data_snapshot (
    singleton BOOLEAN PRIMARY KEY CHECK(singleton),
    data_snapshot_id VARCHAR NOT NULL,
    manifest_path VARCHAR NOT NULL,
    activated_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);
