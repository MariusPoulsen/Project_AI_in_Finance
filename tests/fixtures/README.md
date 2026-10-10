# Offline fixtures

These small synthetic inputs test storage, relationships, model fitting and
evidence handling without credentials, network access or downloaded weights.
They are not historical research data or accepted study results. Directory and
fixture identities remain fixed for reproducible tests.

The root market rows and document exercise CSV → Arrow → Parquet → DuckDB,
immutable document storage, artifact manifests and run registrations. Component
fixtures extend this with controlled histories and mocked extraction outputs.
See the [test configuration](../../pyproject.toml) and
[reference runbooks](../../docs/archive/README.md) for their usage.
