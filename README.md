# Frameshift

[![PyPI version](https://badge.fury.io/py/frameshift.svg)](https://badge.fury.io/py/frameshift)
[![Python Versions](https://img.shields.io/pypi/pyversions/frameshift.svg)](https://pypi.org/project/frameshift/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Load pandas DataFrames into Amazon Redshift without S3.**

Frameshift enables direct DataFrame-to-Redshift loading using efficient multi-row INSERT statements, bypassing the need for S3 staging. Perfect for ad-hoc data loading, development environments, and situations where S3 access is unavailable.

## Why Frameshift?

Amazon Redshift's recommended data loading method (COPY from S3) requires:
- S3 bucket access and credentials
- IAM role configuration
- Network connectivity to S3
- Additional infrastructure setup

**Frameshift solves this by:**
- Loading data directly via SQL INSERT statements
- Requiring only database credentials
- Working anywhere you can connect to Redshift
- Providing intelligent chunking to stay within Redshift's 16 MB statement limit

## Important: When to Use Frameshift

### Recommended Use Cases

- **Ad-hoc data loading** - One-time data imports and exploration
- **Development/testing** - Quick iteration without S3 setup
- **Data exploration** - Loading sample data for analysis
- **Environments without S3** - Air-gapped networks, restricted environments
- **Small to medium datasets** - Typically under 1 million rows

### NOT Recommended For

- **Production ETL pipelines** - Use COPY from S3 instead
- **Repetitive scheduled jobs** - COPY is 10-100x faster
- **Large datasets (>1M rows)** - Will be slow
- **High-frequency loading** - INSERT is not optimized for this
- **Performance-critical applications** - COPY parallelizes across nodes

> **Rule of thumb:** If you're loading data more than once or loading more than 1 million rows, invest the time to set up S3-based COPY.

## Installation

```bash
pip install frameshift
```

With optional dependencies:

```bash
# For Amazon's official Redshift connector
pip install frameshift[redshift-connector]

# For SQLAlchemy support
pip install frameshift[sqlalchemy]

# All optional dependencies
pip install frameshift[all]
```

## Quick Start

```python
import pandas as pd
from frameshift import FrameShift

# Create sample data
df = pd.DataFrame({
    'user_id': [1, 2, 3, 4, 5],
    'email': ['alice@example.com', 'bob@example.com', 'carol@example.com',
              'dave@example.com', 'eve@example.com'],
    'created_at': pd.date_range('2024-01-01', periods=5),
    'score': [85.5, 92.3, 78.1, 95.7, 88.2]
})

# Connect to Redshift
fs = FrameShift(
    host='your-cluster.region.redshift.amazonaws.com',
    database='mydb',
    user='admin',
    password='your-password',
    port=5439
)

# Load data
result = fs.load(df, 'users')
print(result.summary())
```

Output:
```
Load Result: SUCCESS
==================================================
Table:            public.users
Rows Loaded:      5
Rows Failed:      0
Chunks Processed: 1
Chunks Failed:    0
Elapsed Time:     0.34 seconds
Throughput:       15 rows/second
Table Created:    Yes
```

## Features

### Intelligent Schema Inference

Frameshift automatically infers optimal Redshift data types:

```python
# Get schema recommendations
schema = fs.infer_schema(df, 'users', auto_suggest_keys=True)
print(schema.to_create_table_sql())
```

Output:
```sql
CREATE TABLE IF NOT EXISTS "public"."users" (
  "user_id" BIGINT NOT NULL,
  "email" VARCHAR(256),
  "created_at" TIMESTAMP,
  "score" DOUBLE PRECISION
)
BACKUP YES
DISTSTYLE KEY DISTKEY ("user_id")
SORTKEY ("created_at");
```

### DISTKEY and SORTKEY Support

Optimize your table design:

```python
result = fs.load(
    df,
    'users',
    distkey='user_id',           # Distribution key
    sortkey=['created_at'],       # Sort key
    primary_key='user_id',        # Primary key constraint
)
```

### Distribution Skew Analysis

Predict data distribution before loading using MD5 hash simulation:

```python
# Analyze a column as potential DISTKEY
analysis = fs.analyze_distribution(df, 'user_id', slice_count=16)
print(analysis.summary())
```

Output:
```
Distribution Analysis for 'user_id'
==================================================
Total Rows:      1000
Unique Values:   1000 (100.0% cardinality)
NULL Count:      0

Simulated Slices: 16
Min/Max/Avg:     58 / 71 / 62
Skew Ratio:      1.14x (1.0 = perfect)
CV:              6.89%

Good DISTKEY:    Yes

Recommendation:
'user_id' is a GOOD candidate for DISTKEY. Good cardinality (100.0%).
Good distribution (skew ratio: 1.14x).
```

Compare multiple columns:

```python
comparison = fs.compare_distkeys(df, ['user_id', 'region', 'status'])
print(comparison)
```

### Unique Key Validation

Validate constraints before loading:

```python
# Check if columns form a unique key
validation = fs.validate_unique_key(df, ['user_id', 'event_date'])

if not validation.is_unique:
    print(f"Found {validation.duplicate_count} duplicate keys!")
    print(validation.sample_duplicates)
```

Find natural keys in your data:

```python
natural_keys = fs.find_natural_keys(df, max_columns=3)
for columns, unique_count in natural_keys:
    print(f"{columns}: {unique_count} unique combinations")
```

### Dry Run Mode

Preview SQL without executing:

```python
# Generate SQL statements
statements = fs.generate_sql(df, 'users', include_create=True)
for stmt in statements:
    print(stmt)
    print('---')
```

### Progress Tracking

Monitor large loads:

```python
def progress(rows_done, total_rows, chunk_num):
    pct = rows_done / total_rows * 100
    print(f"Chunk {chunk_num}: {rows_done}/{total_rows} ({pct:.1f}%)")

result = fs.load(df, 'users', progress_callback=progress)
```

### Configuration Options

```python
from frameshift import FrameShift, FrameShiftConfig

# Custom configuration
config = FrameShiftConfig(
    max_statement_bytes=10 * 1024 * 1024,  # 10 MB per INSERT
    batch_size=5000,                        # Initial rows per chunk
    use_transactions=True,                  # Wrap in transaction
    commit_every=10,                        # Commit every 10 chunks
    on_error='skip',                        # 'abort', 'skip', or 'log'
    dry_run=False,                          # Generate SQL only
)

fs = FrameShift(
    host='...',
    config=config,
)

# Pre-built configurations
config = FrameShiftConfig.for_data_api()      # 100 KB limit
config = FrameShiftConfig.for_large_datasets() # Optimized for big loads
config = FrameShiftConfig.for_small_datasets() # Quick feedback
```

## Connection Methods

### Direct Connection (psycopg2)

```python
fs = FrameShift(
    host='your-cluster.region.redshift.amazonaws.com',
    database='mydb',
    user='admin',
    password='secret',
    port=5439
)
```

### Amazon Redshift Connector

```python
fs = FrameShift(
    host='your-cluster.region.redshift.amazonaws.com',
    database='mydb',
    user='admin',
    password='secret',
    driver='redshift-connector'
)
```

### Existing Connection

```python
import psycopg2

conn = psycopg2.connect(
    host='...',
    dbname='mydb',
    user='admin',
    password='secret'
)

fs = FrameShift(connection=conn)
```

### SQLAlchemy

```python
fs = FrameShift(
    connection_string='redshift+psycopg2://user:pass@host:5439/db'
)
```

## API Reference

### FrameShift

| Method | Description |
|--------|-------------|
| `load(df, table_name, ...)` | Load DataFrame to Redshift |
| `infer_schema(df, table_name, ...)` | Infer optimal table schema |
| `analyze_distribution(df, column, ...)` | Analyze DISTKEY candidate |
| `compare_distkeys(df, columns, ...)` | Compare multiple DISTKEY candidates |
| `validate_unique_key(df, columns)` | Validate unique constraint |
| `find_natural_keys(df, ...)` | Find potential natural keys |
| `generate_sql(df, table_name, ...)` | Generate SQL without executing |
| `estimate_load(df, ...)` | Estimate loading statistics |
| `get_recommendations(df, table_name)` | Get comprehensive recommendations |

### Load Options

| Parameter | Type | Description |
|-----------|------|-------------|
| `df` | DataFrame | Data to load |
| `table_name` | str | Target table name |
| `schema_name` | str | Schema (default: 'public') |
| `if_exists` | str | 'append', 'replace', or 'fail' |
| `distkey` | str | Distribution key column |
| `sortkey` | str/list | Sort key column(s) |
| `primary_key` | str/list | Primary key column(s) |
| `unique_key` | str/list | Unique constraint column(s) |
| `validate_unique` | bool | Validate unique key before load |

## Performance Considerations

### Redshift Limits

- **Maximum SQL statement size:** 16 MB
- **Data API limit:** 100 KB
- **Frameshift default:** 15 MB (conservative)

### Performance Tips

1. **Batch appropriately:** Larger batches = fewer round trips
2. **Use transactions:** Groups inserts for atomicity
3. **Choose good DISTKEY:** Use `analyze_distribution()` first
4. **Consider SORTKEY:** Date columns work well
5. **Validate data:** Use `validate_unique_key()` before loading

### When to Use COPY Instead

| Scenario | Use Frameshift | Use COPY |
|----------|---------------|----------|
| < 10K rows, one-time | Yes | Overkill |
| 10K-100K rows | Maybe | Preferred |
| > 100K rows | No | Required |
| Scheduled jobs | No | Required |
| Production ETL | No | Required |

## Examples

See the [examples](./examples/) directory for:

- Basic loading
- Schema inference
- Distribution analysis
- Unique key validation
- Large dataset handling
- Error handling

## Contributing

Contributions are welcome! Please read our [Contributing Guide](CONTRIBUTING.md) first.

```bash
# Clone the repo
git clone https://github.com/lcapece/frameshift.git
cd frameshift

# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run linting
ruff check src tests
black --check src tests
mypy src
```

## License

MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgments

- Inspired by the need for simpler Redshift data loading
- Built with [pandas](https://pandas.pydata.org/), [psycopg2](https://www.psycopg.org/)
- Distribution analysis uses MD5 hashing to simulate Redshift's distribution
