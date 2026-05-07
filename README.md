# Frameshift

Frameshift loads pandas DataFrames into Amazon Redshift with multi-row `INSERT` statements.

It is intended for small to medium loads where S3 staging is not available.

## Install

```bash
pip install frameshift
```

## Basic usage

```python
import pandas as pd
from frameshift import FrameShift

df = pd.DataFrame({
    "id": [1, 2, 3],
    "name": ["Alice", "Bob", "Charlie"],
})

with FrameShift(
    host="cluster.region.redshift.amazonaws.com",
    database="mydb",
    user="admin",
    password="secret",
) as fs:
    result = fs.load(df, "users")
    print(result.summary())
```

## Loading options

```python
fs.load(df, "users", if_exists="append")
fs.load(df, "users", if_exists="replace")
fs.load(df, "users", distkey="id", sortkey="created_at")
```

## Configuration

```python
from frameshift import FrameShift, FrameShiftConfig

config = FrameShiftConfig(
    batch_size=1000,
    commit_every=10,
    dry_run=True,
)

fs = FrameShift(host="...", database="...", user="...", password="...", config=config)
```

## Schema and validation helpers

```python
schema = fs.infer_schema(df, "users")
analysis = fs.analyze_distribution(df, "id")
validation = fs.validate_unique_key(df, "id")
recommendations = fs.get_recommendations(df, "users")
```

## Notes

- Frameshift uses direct `INSERT` statements.
- It does not replace Redshift `COPY` for large or recurring loads.
- Use `dry_run=True` to preview generated SQL.
- Use `progress_callback` on `load()` if you want progress updates.

## License

MIT
