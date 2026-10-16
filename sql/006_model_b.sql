CREATE TABLE analytics.model_b_versions (
    model_version VARCHAR PRIMARY KEY,
    dataset_version VARCHAR NOT NULL REFERENCES analytics.event_dataset_versions(dataset_version),
    event_feature_version VARCHAR NOT NULL,
    model_a_version VARCHAR NOT NULL REFERENCES analytics.model_versions(model_version),
    manifest_path VARCHAR NOT NULL,
    checksum VARCHAR NOT NULL,
    run_id VARCHAR NOT NULL
);
CREATE TABLE ops.active_model_b (
    singleton BOOLEAN PRIMARY KEY CHECK(singleton),
    model_version VARCHAR NOT NULL
);
CREATE TABLE analytics.model_b_predictions (
    model_version VARCHAR NOT NULL REFERENCES analytics.model_b_versions(model_version),
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
