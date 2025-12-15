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

---

## Examples

### Example 1: Simplest Usage (3 lines)

The most basic way to load a DataFrame into Redshift:

```python
import pandas as pd
from frameshift import FrameShift

# Your data
df = pd.DataFrame({'id': [1, 2, 3], 'name': ['Alice', 'Bob', 'Charlie']})

# Connect and load
fs = FrameShift(host='cluster.region.redshift.amazonaws.com', database='mydb', user='admin', password='secret')
fs.load(df, 'users')
```

That's it! Frameshift automatically:
- Creates the table if it doesn't exist
- Infers column types from pandas dtypes
- Chunks data to fit within Redshift limits

---

### Example 2: Basic Load with Connection Context Manager

Using context manager for automatic cleanup:

```python
import pandas as pd
from frameshift import FrameShift

df = pd.DataFrame({
    'product_id': [101, 102, 103],
    'product_name': ['Widget', 'Gadget', 'Gizmo'],
    'price': [19.99, 29.99, 39.99],
    'in_stock': [True, False, True]
})

with FrameShift(
    host='cluster.region.redshift.amazonaws.com',
    database='mydb',
    user='admin',
    password='secret',
    port=5439
) as fs:
    result = fs.load(df, 'products')
    print(f"Loaded {result.rows_loaded} rows")
```

---

### Example 3: Load with Result Inspection

Get detailed information about the load operation:

```python
import pandas as pd
from frameshift import FrameShift

df = pd.DataFrame({
    'order_id': range(1, 1001),
    'customer_id': [i % 100 for i in range(1, 1001)],
    'amount': [round(10 + i * 0.5, 2) for i in range(1, 1001)],
    'order_date': pd.date_range('2024-01-01', periods=1000)
})

fs = FrameShift(
    host='cluster.region.redshift.amazonaws.com',
    database='mydb',
    user='admin',
    password='secret'
)

result = fs.load(df, 'orders')

# Inspect the result
print(result.summary())
# Output:
# Load Result: SUCCESS
# ==================================================
# Table:            public.orders
# Rows Loaded:      1,000
# Rows Failed:      0
# Chunks Processed: 1
# Chunks Failed:    0
# Elapsed Time:     1.23 seconds
# Throughput:       813 rows/second
# Table Created:    Yes

# Access specific attributes
print(f"Success: {result.success}")
print(f"Rows loaded: {result.rows_loaded}")
print(f"Time taken: {result.elapsed_seconds:.2f}s")
print(f"Speed: {result.rows_per_second:.0f} rows/sec")
```

---

### Example 4: Specify Schema and Table Options

Control where and how the table is created:

```python
import pandas as pd
from frameshift import FrameShift

df = pd.DataFrame({
    'event_id': range(1, 101),
    'event_type': ['click', 'view', 'purchase'] * 33 + ['click'],
    'user_id': [i % 20 for i in range(1, 101)],
    'timestamp': pd.date_range('2024-01-01', periods=100, freq='h')
})

fs = FrameShift(
    host='cluster.region.redshift.amazonaws.com',
    database='analytics',
    user='admin',
    password='secret'
)

result = fs.load(
    df,
    table_name='user_events',
    schema_name='staging',           # Use 'staging' schema instead of 'public'
    if_exists='replace',             # Drop and recreate if exists ('append', 'replace', 'fail')
)

print(f"Table: {result.table_name}")  # Output: staging.user_events
```

---

### Example 5: Specify DISTKEY and SORTKEY

Optimize table design for query performance:

```python
import pandas as pd
from frameshift import FrameShift

df = pd.DataFrame({
    'user_id': range(1, 10001),
    'session_id': [f'sess_{i}' for i in range(1, 10001)],
    'page_url': [f'/page/{i % 100}' for i in range(1, 10001)],
    'event_time': pd.date_range('2024-01-01', periods=10000, freq='min'),
    'duration_seconds': [i % 300 for i in range(1, 10001)]
})

fs = FrameShift(
    host='cluster.region.redshift.amazonaws.com',
    database='mydb',
    user='admin',
    password='secret'
)

result = fs.load(
    df,
    table_name='page_views',
    distkey='user_id',               # Distribute data by user_id for JOIN optimization
    sortkey='event_time',            # Sort by time for range queries
)

# The created table will have:
# DISTSTYLE KEY DISTKEY ("user_id")
# SORTKEY ("event_time")
```

---

### Example 6: Compound SORTKEY

Use multiple columns as sort key:

```python
import pandas as pd
from frameshift import FrameShift

df = pd.DataFrame({
    'tenant_id': [1, 1, 1, 2, 2, 2] * 100,
    'user_id': list(range(1, 601)),
    'action': ['login', 'view', 'logout'] * 200,
    'created_at': pd.date_range('2024-01-01', periods=600, freq='h')
})

fs = FrameShift(
    host='cluster.region.redshift.amazonaws.com',
    database='mydb',
    user='admin',
    password='secret'
)

result = fs.load(
    df,
    table_name='audit_log',
    distkey='tenant_id',
    sortkey=['tenant_id', 'created_at'],  # Compound sort key
)

# Creates: SORTKEY ("tenant_id", "created_at")
# Optimizes queries like: WHERE tenant_id = 1 AND created_at > '2024-01-01'
```

---

### Example 7: Primary Key and Unique Constraints

Define table constraints:

```python
import pandas as pd
from frameshift import FrameShift

df = pd.DataFrame({
    'user_id': range(1, 101),
    'email': [f'user{i}@example.com' for i in range(1, 101)],
    'username': [f'user_{i}' for i in range(1, 101)],
    'created_at': pd.date_range('2024-01-01', periods=100)
})

fs = FrameShift(
    host='cluster.region.redshift.amazonaws.com',
    database='mydb',
    user='admin',
    password='secret'
)

result = fs.load(
    df,
    table_name='users',
    distkey='user_id',
    sortkey='created_at',
    primary_key='user_id',           # PRIMARY KEY constraint
    unique_key='email',              # UNIQUE constraint on email
)

# Note: Redshift enforces uniqueness at query time, not insert time
# Use validate_unique=True to check before loading
```

---

### Example 8: Validate Unique Key Before Loading

Prevent duplicate key errors:

```python
import pandas as pd
from frameshift import FrameShift

# Data with potential duplicates
df = pd.DataFrame({
    'order_id': [1, 2, 3, 2, 4],     # Note: order_id 2 appears twice!
    'product': ['A', 'B', 'C', 'B', 'D'],
    'quantity': [1, 2, 1, 2, 3]
})

fs = FrameShift(
    host='cluster.region.redshift.amazonaws.com',
    database='mydb',
    user='admin',
    password='secret'
)

# Option 1: Validate separately
validation = fs.validate_unique_key(df, 'order_id')
print(f"Is unique: {validation.is_unique}")           # False
print(f"Duplicates: {validation.duplicate_count}")    # 1
print(validation.sample_duplicates)                   # Shows the duplicate rows

# Option 2: Validate during load (raises ValidationError if duplicates found)
try:
    result = fs.load(
        df,
        table_name='orders',
        unique_key='order_id',
        validate_unique=True,        # Validate before inserting
    )
except Exception as e:
    print(f"Validation failed: {e}")
    # Handle duplicates before loading
    df_clean = df.drop_duplicates(subset='order_id', keep='first')
    result = fs.load(df_clean, 'orders')
```

---

### Example 9: Analyze Distribution Before Choosing DISTKEY

Use MD5 hash simulation to predict data skew:

```python
import pandas as pd
import numpy as np
from frameshift import FrameShift

np.random.seed(42)
df = pd.DataFrame({
    'user_id': range(1, 10001),                                    # High cardinality
    'region': np.random.choice(['US', 'EU', 'APAC'], 10000),       # Low cardinality
    'status': np.random.choice(['active', 'inactive'], 10000, p=[0.9, 0.1]),  # Very skewed
})

fs = FrameShift(
    host='cluster.region.redshift.amazonaws.com',
    database='mydb',
    user='admin',
    password='secret'
)

# Analyze single column
print("=== Analyzing user_id ===")
analysis = fs.analyze_distribution(df, 'user_id', slice_count=16)
print(f"Unique values: {analysis.unique_values}")
print(f"Cardinality: {analysis.cardinality_ratio:.1%}")
print(f"Skew ratio: {analysis.skew_ratio:.2f}x")
print(f"Good DISTKEY: {analysis.is_good_distkey()}")
print()

print("=== Analyzing region ===")
analysis = fs.analyze_distribution(df, 'region', slice_count=16)
print(f"Unique values: {analysis.unique_values}")
print(f"Skew ratio: {analysis.skew_ratio:.2f}x")
print(f"Good DISTKEY: {analysis.is_good_distkey()}")
print()

# Compare multiple columns at once
print("=== Comparison ===")
comparison = fs.compare_distkeys(df, ['user_id', 'region', 'status'])
print(comparison.to_string(index=False))

# Output shows user_id is the best choice (lowest skew, highest cardinality)
```

---

### Example 10: Get Full Schema Recommendations

Let Frameshift analyze your data and suggest optimal schema:

```python
import pandas as pd
from frameshift import FrameShift

df = pd.DataFrame({
    'transaction_id': range(1, 1001),
    'customer_id': [i % 100 for i in range(1, 1001)],
    'product_category': ['Electronics', 'Books', 'Clothing', 'Food'] * 250,
    'amount': [round(10 + i * 0.1, 2) for i in range(1, 1001)],
    'transaction_date': pd.date_range('2024-01-01', periods=1000),
    'is_returned': [i % 20 == 0 for i in range(1, 1001)]
})

fs = FrameShift(
    host='cluster.region.redshift.amazonaws.com',
    database='mydb',
    user='admin',
    password='secret'
)

# Get comprehensive recommendations
recommendations = fs.get_recommendations(df, 'transactions')

print(f"Table: {recommendations['table_name']}")
print(f"Rows: {recommendations['row_count']:,}")
print(f"Est. Size: {recommendations['estimated_size_mb']:.2f} MB")
print()

print("DISTKEY Recommendation:")
print(f"  Column: {recommendations['distkey']['column']}")
print(f"  Reason: {recommendations['distkey']['reason']}")
print()

print("SORTKEY Recommendation:")
print(f"  Columns: {recommendations['sortkey']['columns']}")
print(f"  Reason: {recommendations['sortkey']['reason']}")
print()

print("Column Analysis:")
for col in recommendations['columns']:
    print(f"  {col['name']}: {col['redshift_type']} (nulls: {col['null_count']}, unique: {col['unique_count']})")
print()

print("Generated CREATE TABLE:")
print(recommendations['sql'])
```

---

### Example 11: Preview SQL Without Executing (Dry Run)

Generate SQL statements without running them:

```python
import pandas as pd
from frameshift import FrameShift, FrameShiftConfig

df = pd.DataFrame({
    'id': [1, 2, 3],
    'name': ['Alice', 'Bob', 'Charlie'],
    'score': [85.5, 92.3, 78.1]
})

# Method 1: Use generate_sql()
fs = FrameShift(
    host='cluster.region.redshift.amazonaws.com',
    database='mydb',
    user='admin',
    password='secret'
)

statements = fs.generate_sql(
    df,
    table_name='students',
    distkey='id',
    include_create=True
)

for i, stmt in enumerate(statements, 1):
    print(f"--- Statement {i} ---")
    print(stmt)
    print()

# Method 2: Use dry_run config
config = FrameShiftConfig(dry_run=True)
fs_dry = FrameShift(
    host='cluster.region.redshift.amazonaws.com',
    database='mydb',
    user='admin',
    password='secret',
    config=config
)

result = fs_dry.load(df, 'students')
print("SQL that would be executed:")
for stmt in result.sql_statements:
    print(stmt)
```

---

### Example 12: Infer and Customize Schema

Fine-tune the inferred schema before loading:

```python
import pandas as pd
from frameshift import FrameShift
from frameshift.types import ColumnSpec, RedshiftType

df = pd.DataFrame({
    'id': [1, 2, 3],
    'description': ['Short', 'A bit longer description', 'Very ' * 100],
    'price': [19.99, 29.99, 39.99],
    'created_at': pd.date_range('2024-01-01', periods=3)
})

fs = FrameShift(
    host='cluster.region.redshift.amazonaws.com',
    database='mydb',
    user='admin',
    password='secret'
)

# Get inferred schema
schema = fs.infer_schema(df, 'products', auto_suggest_keys=True)

print("Inferred columns:")
for col in schema.columns:
    print(f"  {col.name}: {col.redshift_type.value}")

# Customize specific columns
custom_columns = [
    ColumnSpec('id', RedshiftType.INTEGER, nullable=False),
    ColumnSpec('description', RedshiftType.VARCHAR, length=4096),  # Override length
    ColumnSpec('price', RedshiftType.DECIMAL, precision=10, scale=2),  # Use DECIMAL
    ColumnSpec('created_at', RedshiftType.TIMESTAMP),
]

result = fs.load(
    df,
    table_name='products',
    column_specs=custom_columns,     # Use custom column definitions
    distkey='id',
)
```

---

### Example 13: Find Natural Keys in Your Data

Discover which columns can serve as unique identifiers:

```python
import pandas as pd
from frameshift import FrameShift

df = pd.DataFrame({
    'order_id': [1, 2, 3, 4, 5],
    'customer_id': [101, 102, 101, 103, 102],
    'product_id': ['A', 'B', 'C', 'A', 'D'],
    'order_date': ['2024-01-01', '2024-01-01', '2024-01-02', '2024-01-02', '2024-01-03'],
    'quantity': [1, 2, 1, 3, 1]
})

fs = FrameShift(
    host='cluster.region.redshift.amazonaws.com',
    database='mydb',
    user='admin',
    password='secret'
)

# Find columns or combinations that are unique
natural_keys = fs.find_natural_keys(df, max_columns=3)

print("Potential natural keys:")
for columns, unique_count in natural_keys:
    cols_str = " + ".join(columns)
    print(f"  {cols_str}: {unique_count} unique combinations")

# Output:
# Potential natural keys:
#   order_id: 5 unique combinations
#   customer_id + product_id: 5 unique combinations (if order_id wasn't unique)
```

---

### Example 14: Load with Progress Tracking

Monitor progress for large loads:

```python
import pandas as pd
from frameshift import FrameShift, FrameShiftConfig

# Create larger dataset
df = pd.DataFrame({
    'id': range(100000),
    'value': [f'value_{i}' for i in range(100000)],
    'score': [i * 0.01 for i in range(100000)]
})

def progress_callback(rows_done, total_rows, chunk_num):
    pct = rows_done / total_rows * 100
    bar_len = 40
    filled = int(bar_len * rows_done / total_rows)
    bar = '=' * filled + '-' * (bar_len - filled)
    print(f"\rChunk {chunk_num:3d} [{bar}] {pct:5.1f}% ({rows_done:,}/{total_rows:,})", end='')

config = FrameShiftConfig(
    batch_size=5000,           # Rows per chunk estimate
    commit_every=5,            # Commit every 5 chunks
)

fs = FrameShift(
    host='cluster.region.redshift.amazonaws.com',
    database='mydb',
    user='admin',
    password='secret',
    config=config
)

result = fs.load(
    df,
    table_name='large_table',
    progress_callback=progress_callback
)

print()  # New line after progress bar
print(result.summary())
```

---

### Example 15: Handle Different Data Types

Load DataFrames with various pandas dtypes:

```python
import pandas as pd
import numpy as np
from frameshift import FrameShift

df = pd.DataFrame({
    # Integer types
    'int_col': pd.array([1, 2, 3, None, 5], dtype='Int64'),      # Nullable integer
    'small_int': pd.array([1, 2, 3, 4, 5], dtype='Int16'),

    # Float types
    'float_col': [1.1, 2.2, np.nan, 4.4, 5.5],                   # With NaN
    'float32': np.array([1.1, 2.2, 3.3, 4.4, 5.5], dtype='float32'),

    # String types
    'string_col': ['hello', 'world', None, 'foo', 'bar'],
    'long_string': ['x' * 1000, 'y' * 2000, 'z' * 100, 'a', 'b'],

    # Boolean
    'bool_col': [True, False, True, None, False],

    # DateTime
    'datetime_col': pd.date_range('2024-01-01', periods=5),
    'datetime_tz': pd.date_range('2024-01-01', periods=5, tz='UTC'),

    # Categorical
    'category_col': pd.Categorical(['A', 'B', 'A', 'C', 'B']),
})

fs = FrameShift(
    host='cluster.region.redshift.amazonaws.com',
    database='mydb',
    user='admin',
    password='secret'
)

# Check what types will be inferred
schema = fs.infer_schema(df, 'mixed_types')
print("Type mapping:")
for col in schema.columns:
    pandas_type = str(df[col.name].dtype)
    rs_type = col.redshift_type.value
    length = f"({col.length})" if col.length else ""
    print(f"  {col.name}: {pandas_type} -> {rs_type}{length}")

# Load the data
result = fs.load(df, 'mixed_types')
print(f"\nLoaded {result.rows_loaded} rows")
```

---

### Example 16: Error Handling and Recovery

Handle errors gracefully:

```python
import pandas as pd
from frameshift import FrameShift, FrameShiftConfig
from frameshift.exceptions import (
    FrameShiftError,
    ConnectionError,
    ValidationError,
    InsertError,
    ChunkingError
)

df = pd.DataFrame({
    'id': [1, 2, 3],
    'name': ['Alice', 'Bob', 'Charlie']
})

try:
    fs = FrameShift(
        host='cluster.region.redshift.amazonaws.com',
        database='mydb',
        user='admin',
        password='secret'
    )

    result = fs.load(df, 'users', validate_unique=True, unique_key='id')

    if result.success:
        print(f"Success! Loaded {result.rows_loaded} rows")
    else:
        print(f"Partial failure: {result.rows_loaded} loaded, {result.rows_failed} failed")
        for error in result.errors:
            print(f"  Error: {error}")

except ConnectionError as e:
    print(f"Connection failed: {e}")
    print(f"  Host: {e.details.get('host')}")

except ValidationError as e:
    print(f"Validation failed: {e}")
    print(f"  Field: {e.details.get('field')}")

except InsertError as e:
    print(f"Insert failed: {e}")
    print(f"  Table: {e.details.get('table')}")
    print(f"  Rows inserted before error: {e.details.get('rows_inserted')}")

except ChunkingError as e:
    print(f"Chunking failed: {e}")
    print(f"  Problematic row: {e.details.get('row_index')}")

except FrameShiftError as e:
    # Catch any Frameshift error
    print(f"Frameshift error: {e}")

finally:
    fs.close()
```

---

### Example 17: Skip Errors and Continue Loading

Continue loading even if some chunks fail:

```python
import pandas as pd
from frameshift import FrameShift, FrameShiftConfig

df = pd.DataFrame({
    'id': range(10000),
    'value': [f'value_{i}' for i in range(10000)]
})

config = FrameShiftConfig(
    on_error='skip',           # Options: 'abort', 'skip', 'log'
    batch_size=1000,
)

fs = FrameShift(
    host='cluster.region.redshift.amazonaws.com',
    database='mydb',
    user='admin',
    password='secret',
    config=config
)

result = fs.load(df, 'data_table')

print(f"Chunks processed: {result.chunks_processed}")
print(f"Chunks failed: {result.chunks_failed}")
print(f"Rows loaded: {result.rows_loaded}")
print(f"Rows failed: {result.rows_failed}")

if result.errors:
    print("\nErrors encountered:")
    for err in result.errors:
        print(f"  - {err}")
```

---

### Example 18: Use Different Connection Methods

Multiple ways to connect to Redshift:

```python
import pandas as pd
from frameshift import FrameShift

df = pd.DataFrame({'id': [1, 2, 3], 'name': ['A', 'B', 'C']})

# Method 1: Direct connection with psycopg2 (default)
fs1 = FrameShift(
    host='cluster.region.redshift.amazonaws.com',
    database='mydb',
    user='admin',
    password='secret',
    port=5439
)

# Method 2: Using Amazon's redshift-connector
fs2 = FrameShift(
    host='cluster.region.redshift.amazonaws.com',
    database='mydb',
    user='admin',
    password='secret',
    driver='redshift-connector'
)

# Method 3: Using existing connection
import psycopg2
conn = psycopg2.connect(
    host='cluster.region.redshift.amazonaws.com',
    dbname='mydb',
    user='admin',
    password='secret',
    port=5439
)
fs3 = FrameShift(connection=conn)

# Method 4: Using SQLAlchemy connection string
fs4 = FrameShift(
    connection_string='redshift+psycopg2://admin:secret@cluster.region.redshift.amazonaws.com:5439/mydb'
)

# All methods work the same way
for fs in [fs1, fs2, fs3, fs4]:
    result = fs.load(df, 'test_table', if_exists='replace')
    fs.close()
```

---

### Example 19: Estimate Load Before Executing

Check estimated load statistics before committing:

```python
import pandas as pd
from frameshift import FrameShift

# Large dataset
df = pd.DataFrame({
    'id': range(500000),
    'data': [f'row_data_{i}' * 10 for i in range(500000)],
    'value': [i * 0.001 for i in range(500000)]
})

fs = FrameShift(
    host='cluster.region.redshift.amazonaws.com',
    database='mydb',
    user='admin',
    password='secret'
)

# Get estimates without loading
estimates = fs.estimate_load(df, 'large_table')

print("Load Estimates:")
print(f"  Total rows: {estimates['total_rows']:,}")
print(f"  Estimated chunks: {estimates['estimated_chunks']}")
print(f"  Avg row size: {estimates['avg_row_size_bytes']:,} bytes")
print(f"  Total size: {estimates['estimated_total_size_bytes'] / 1024 / 1024:.2f} MB")
print(f"  Max rows per chunk: {estimates['max_rows_per_chunk']:,}")

if estimates['recommendations']:
    print("\nRecommendations:")
    for rec in estimates['recommendations']:
        print(f"  - {rec}")

# Decide whether to proceed
if estimates['estimated_chunks'] > 100:
    print("\nWarning: Large number of chunks. Consider using COPY from S3.")
else:
    result = fs.load(df, 'large_table')
    print(f"\nLoaded successfully: {result.rows_loaded:,} rows")
```

---

### Example 20: Complete Production-Ready Example

A comprehensive example combining multiple features:

```python
import pandas as pd
import logging
from frameshift import FrameShift, FrameShiftConfig
from frameshift.exceptions import FrameShiftError

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_sales_data(df: pd.DataFrame, fs: FrameShift) -> bool:
    """
    Load sales data with full validation and optimization.

    Returns True if successful, False otherwise.
    """
    table_name = 'sales_transactions'

    # Step 1: Validate unique key
    logger.info("Validating unique key...")
    validation = fs.validate_unique_key(df, ['transaction_id'])
    if not validation.is_unique:
        logger.error(f"Found {validation.duplicate_count} duplicate transaction IDs")
        logger.error(f"Sample duplicates:\n{validation.sample_duplicates}")
        return False
    logger.info("Unique key validation passed")

    # Step 2: Analyze distribution for DISTKEY
    logger.info("Analyzing distribution...")
    comparison = fs.compare_distkeys(df, ['customer_id', 'product_id', 'store_id'])
    best_distkey = comparison.iloc[0]['column']
    logger.info(f"Best DISTKEY candidate: {best_distkey}")

    # Step 3: Get estimates
    estimates = fs.estimate_load(df)
    logger.info(f"Estimated chunks: {estimates['estimated_chunks']}")
    logger.info(f"Estimated size: {estimates['estimated_total_size_bytes'] / 1024 / 1024:.2f} MB")

    # Step 4: Preview schema
    schema = fs.infer_schema(
        df, table_name,
        distkey=best_distkey,
        sortkey='transaction_date',
        auto_suggest_keys=False
    )
    logger.info(f"CREATE TABLE SQL:\n{schema.to_create_table_sql()}")

    # Step 5: Load with progress tracking
    def progress(done, total, chunk):
        if chunk % 10 == 0:  # Log every 10 chunks
            logger.info(f"Progress: {done:,}/{total:,} rows ({done/total*100:.1f}%)")

    logger.info("Starting load...")
    result = fs.load(
        df,
        table_name=table_name,
        schema_name='analytics',
        distkey=best_distkey,
        sortkey='transaction_date',
        primary_key='transaction_id',
        if_exists='replace',
        progress_callback=progress
    )

    # Step 6: Report results
    if result.success:
        logger.info(f"SUCCESS: Loaded {result.rows_loaded:,} rows in {result.elapsed_seconds:.2f}s")
        logger.info(f"Throughput: {result.rows_per_second:,.0f} rows/sec")
        return True
    else:
        logger.error(f"FAILED: {result.rows_failed:,} rows failed")
        for error in result.errors:
            logger.error(f"  Error: {error}")
        return False


def main():
    # Create sample sales data
    df = pd.DataFrame({
        'transaction_id': range(1, 50001),
        'customer_id': [i % 1000 for i in range(1, 50001)],
        'product_id': [f'PROD-{i % 500:04d}' for i in range(1, 50001)],
        'store_id': [i % 50 for i in range(1, 50001)],
        'quantity': [1 + i % 10 for i in range(1, 50001)],
        'unit_price': [round(9.99 + (i % 100) * 0.5, 2) for i in range(1, 50001)],
        'transaction_date': pd.date_range('2024-01-01', periods=50000, freq='min'),
        'payment_method': ['credit', 'debit', 'cash'] * 16666 + ['credit', 'debit'],
    })

    # Calculate total
    df['total_amount'] = df['quantity'] * df['unit_price']

    # Configure Frameshift
    config = FrameShiftConfig(
        batch_size=5000,
        commit_every=10,
        on_error='abort',
        verbosity=1,
    )

    try:
        with FrameShift(
            host='cluster.region.redshift.amazonaws.com',
            database='analytics_db',
            user='etl_user',
            password='secure_password',
            config=config
        ) as fs:
            success = load_sales_data(df, fs)

            if success:
                print("\n" + "=" * 50)
                print("Data loaded successfully!")
                print("=" * 50)
            else:
                print("\n" + "=" * 50)
                print("Data load failed. Check logs for details.")
                print("=" * 50)

    except FrameShiftError as e:
        logger.error(f"Frameshift error: {e}")
        raise


if __name__ == '__main__':
    main()
```

---

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

---

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
| `progress_callback` | callable | Progress tracking function |

---

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

---

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
