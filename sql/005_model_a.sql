CREATE TABLE analytics.event_dataset_versions (
    dataset_version VARCHAR PRIMARY KEY,
    data_snapshot_id VARCHAR NOT NULL,
    relationship_version VARCHAR NOT NULL REFERENCES analytics.relationship_versions(relationship_version),
    config_hash VARCHAR NOT NULL,
    manifest_path VARCHAR NOT NULL,
    checksum VARCHAR NOT NULL,
    run_id VARCHAR NOT NULL
);
CREATE TABLE ops.active_event_dataset (
    singleton BOOLEAN PRIMARY KEY CHECK(singleton),
    dataset_version VARCHAR NOT NULL
);
CREATE TABLE analytics.divergence_events (
    dataset_version VARCHAR NOT NULL REFERENCES analytics.event_dataset_versions(dataset_version),
    event_id VARCHAR NOT NULL,
    pair_id VARCHAR NOT NULL,
    event_timestamp TIMESTAMPTZ NOT NULL,
    relationship_version VARCHAR NOT NULL,
    relationship_snapshot_id VARCHAR NOT NULL,
    entry_z DOUBLE NOT NULL,
    baseline1_eligible BOOLEAN NOT NULL,
    partition VARCHAR NOT NULL,
    feature_complete BOOLEAN NOT NULL,
    model_ready BOOLEAN NOT NULL,
    details JSON NOT NULL,
    PRIMARY KEY(dataset_version,event_id),
    FOREIGN KEY(relationship_version,relationship_snapshot_id)
      REFERENCES analytics.relationship_snapshots(relationship_version,relationship_snapshot_id)
);
CREATE TABLE analytics.event_features (
    dataset_version VARCHAR NOT NULL,
    event_id VARCHAR NOT NULL,
    feature_schema_version VARCHAR NOT NULL,
    feature_cutoff_timestamp TIMESTAMPTZ NOT NULL,
    feature_complete BOOLEAN NOT NULL,
    details JSON NOT NULL,
    PRIMARY KEY(dataset_version,event_id),
    FOREIGN KEY(dataset_version,event_id) REFERENCES analytics.divergence_events(dataset_version,event_id)
);
CREATE TABLE analytics.event_targets (
    dataset_version VARCHAR NOT NULL,
    event_id VARCHAR NOT NULL,
    y_revert_success INTEGER CHECK(y_revert_success IN (0,1)),
    outcome_type VARCHAR NOT NULL,
    label_eligible BOOLEAN NOT NULL,
    details JSON NOT NULL,
    PRIMARY KEY(dataset_version,event_id),
    FOREIGN KEY(dataset_version,event_id) REFERENCES analytics.divergence_events(dataset_version,event_id)
);
CREATE TABLE analytics.event_partitions (
    dataset_version VARCHAR NOT NULL,
    event_id VARCHAR NOT NULL,
    partition VARCHAR NOT NULL,
    supervised_eligible BOOLEAN NOT NULL,
    exclusion_reason VARCHAR,
    details JSON NOT NULL,
    PRIMARY KEY(dataset_version,event_id),
    FOREIGN KEY(dataset_version,event_id) REFERENCES analytics.divergence_events(dataset_version,event_id)
);
CREATE TABLE analytics.model_versions (
    model_version VARCHAR PRIMARY KEY,
    dataset_version VARCHAR NOT NULL REFERENCES analytics.event_dataset_versions(dataset_version),
    manifest_path VARCHAR NOT NULL,
    checksum VARCHAR NOT NULL,
    run_id VARCHAR NOT NULL
);
CREATE TABLE ops.active_model_a (
    singleton BOOLEAN PRIMARY KEY CHECK(singleton),
    model_version VARCHAR NOT NULL
);
CREATE TABLE analytics.model_predictions (
    model_version VARCHAR NOT NULL REFERENCES analytics.model_versions(model_version),
    dataset_version VARCHAR NOT NULL,
    event_id VARCHAR NOT NULL,
    pair_id VARCHAR NOT NULL,
    event_timestamp TIMESTAMPTZ NOT NULL,
    raw_probability DOUBLE NOT NULL CHECK(raw_probability BETWEEN 0 AND 1),
    calibrated_probability DOUBLE NOT NULL CHECK(calibrated_probability BETWEEN 0 AND 1),
    details JSON NOT NULL,
    PRIMARY KEY(model_version,event_id),
    FOREIGN KEY(dataset_version,event_id) REFERENCES analytics.divergence_events(dataset_version,event_id)
);
