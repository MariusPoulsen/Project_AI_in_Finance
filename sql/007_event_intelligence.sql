CREATE TABLE analytics.event_intelligence_versions (
    event_feature_version VARCHAR PRIMARY KEY,
    dataset_version VARCHAR NOT NULL REFERENCES analytics.event_dataset_versions(dataset_version),
    manifest_path VARCHAR NOT NULL,
    checksum VARCHAR NOT NULL,
    run_id VARCHAR NOT NULL
);
CREATE TABLE ops.active_event_intelligence (
    singleton BOOLEAN PRIMARY KEY CHECK (singleton),
    event_feature_version VARCHAR NOT NULL
);
CREATE TABLE analytics.event_extractions (
    event_feature_version VARCHAR NOT NULL REFERENCES analytics.event_intelligence_versions(event_feature_version),
    event_id VARCHAR NOT NULL,
    extraction_id VARCHAR NOT NULL,
    event_type VARCHAR NOT NULL,
    affected_leg VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    evidence_hash VARCHAR NOT NULL,
    details JSON NOT NULL,
    PRIMARY KEY (event_feature_version, event_id)
);
CREATE TABLE analytics.model_b_event_features (
    event_feature_version VARCHAR NOT NULL REFERENCES analytics.event_intelligence_versions(event_feature_version),
    event_id VARCHAR NOT NULL,
    event_available_at TIMESTAMPTZ NOT NULL,
    evidence_available DOUBLE NOT NULL,
    details JSON NOT NULL,
    PRIMARY KEY (event_feature_version, event_id)
);
CREATE TABLE analytics.evidence_packs (
    event_feature_version VARCHAR NOT NULL REFERENCES analytics.event_intelligence_versions(event_feature_version),
    event_id VARCHAR NOT NULL,
    evidence_hash VARCHAR NOT NULL,
    coverage_status VARCHAR NOT NULL,
    pack_path VARCHAR NOT NULL,
    details JSON NOT NULL,
    PRIMARY KEY (event_feature_version, event_id)
);
