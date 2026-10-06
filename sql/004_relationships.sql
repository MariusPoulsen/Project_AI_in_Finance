CREATE TABLE analytics.relationship_versions (
    relationship_version VARCHAR PRIMARY KEY,
    data_snapshot_id VARCHAR NOT NULL,
    config_hash VARCHAR NOT NULL,
    synthetic BOOLEAN NOT NULL,
    manifest_path VARCHAR NOT NULL,
    checksum VARCHAR NOT NULL,
    run_id VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);

CREATE TABLE ops.active_relationship_version (
    singleton BOOLEAN PRIMARY KEY CHECK(singleton),
    relationship_version VARCHAR NOT NULL
);

CREATE TABLE analytics.relationship_snapshots (
    relationship_version VARCHAR NOT NULL REFERENCES analytics.relationship_versions(relationship_version),
    relationship_snapshot_id VARCHAR NOT NULL,
    pair_id VARCHAR NOT NULL,
    estimation_date DATE NOT NULL,
    effective_start DATE NOT NULL,
    effective_end DATE,
    data_snapshot_id VARCHAR NOT NULL,
    config_hash VARCHAR NOT NULL,
    pair_status VARCHAR NOT NULL CHECK(pair_status IN ('ACTIVE','WATCH','RETIRED')),
    n_obs INTEGER NOT NULL,
    alpha DOUBLE,
    beta DOUBLE,
    spread_mean DOUBLE,
    spread_std DOUBLE,
    diagnostics JSON NOT NULL,
    PRIMARY KEY(relationship_version,relationship_snapshot_id)
);

CREATE TABLE analytics.pair_state_daily (
    relationship_version VARCHAR NOT NULL,
    pair_id VARCHAR NOT NULL,
    trading_date DATE NOT NULL,
    relationship_snapshot_id VARCHAR NOT NULL,
    alpha DOUBLE NOT NULL,
    beta DOUBLE NOT NULL,
    spread DOUBLE NOT NULL,
    z_score DOUBLE NOT NULL,
    abs_z DOUBLE NOT NULL,
    spread_velocity_1d DOUBLE,
    z_velocity_1d DOUBLE,
    pair_status VARCHAR NOT NULL,
    data_available_at TIMESTAMPTZ NOT NULL,
    data_snapshot_id VARCHAR NOT NULL,
    details JSON NOT NULL,
    PRIMARY KEY(relationship_version,pair_id,trading_date),
    FOREIGN KEY(relationship_version,relationship_snapshot_id)
      REFERENCES analytics.relationship_snapshots(relationship_version,relationship_snapshot_id)
);

CREATE TABLE analytics.divergence_crossings (
    relationship_version VARCHAR NOT NULL,
    crossing_id VARCHAR NOT NULL,
    pair_id VARCHAR NOT NULL,
    trading_date DATE NOT NULL,
    event_timestamp TIMESTAMPTZ NOT NULL,
    relationship_snapshot_id VARCHAR NOT NULL,
    direction INTEGER NOT NULL CHECK(direction IN (-1,1)),
    z_score DOUBLE NOT NULL,
    baseline1_eligible BOOLEAN NOT NULL,
    data_snapshot_id VARCHAR NOT NULL,
    details JSON NOT NULL,
    PRIMARY KEY(relationship_version,crossing_id),
    FOREIGN KEY(relationship_version,relationship_snapshot_id)
      REFERENCES analytics.relationship_snapshots(relationship_version,relationship_snapshot_id)
);
