# Frameshift

**Load pandas DataFrames directly into Amazon Redshift — no S3 required.**

Look, we all know COPY from S3 is the *right* way to load data into Redshift. It's fast, it's highly parallel, it's what Amazon designed. But sometimes life doesn't cooperate:

- Your VPC has no S3 access (yep. thanks security team)
- You're behind an air-gapped network 
- Someone forgot to give you the S3 credentials 
- You just need to load 50K rows ONE TIME and don't want to spin up an entire S3 pipeline

Enter Frameshift: the "I just need to get this data into Redshift (and I'm in no hurry)" solution.

## The Honest Truth

**Frameshift is 10-20x slower than COPY.** There, we said it.

Even tried being clever with 16 parallel threads, mimicking Redshift's MD5 hash distribution pattern. Turns out Redshift's leader node just laughs at your multi-threading ambitions and processes everything sequentially anyway. We settled on 4 threads which helps *somewhat*, but don't expect miracles.

**TEST RESULTS (8 RPU Redshift Serverless**

| Method | Time (250K rows) | Rows/sec |
|--------|------------------|----------|
| Frameshift | ~120-200s | 1,200-2,000 |
| COPY from S3 | ~10s | 25,000+ |

Yeah. It's slow AF. But when you can't use S3, you can't use S3.

## Installation

```bash
pip install frameshift
```

## Quick Start

```python
import pandas as pd
from frameshift import FrameShift

df = pd.DataFrame({
    'id': [1, 2, 3],
    'name': ['Alice Cooper', 'Bob Rock', 'Chuck Biscuits'],
    'royalties': [1000000, 75000000, 5550]
})

with FrameShift(
    host='cluster.region.redshift.amazonaws.com',
    database='mydb',
    user='admin',
    password='secret'
) as fs:
    result = fs.load(df, 'users')
    print(f"Loaded {result.rows_loaded} rows")
```

That's it. Frameshift handles:
- Creating the table if it doesn't exist (because you're lazy)
- Inferring column types from pandas (magical!)
- Chunking data to maximally fit Redshift's 16MB Multi-Row-Insert statement limit (boring but necessary)
- Running 4 parallel connections (marginally faster than 1, we tried harder)

## Options You Might Actually Use

### Replace vs Append

```python
# Nuke and pave (drop table, recreate)
fs.load(df, 'users', if_exists='replace')

# Just add more data (default)
fs.load(df, 'users', if_exists='append')
```

### Distribution Keys (if you care about performance)

```python
fs.load(
    df,
    'events',
    distkey='user_id',      # JOINs go brrr
    sortkey='event_time',   # Range queries go zoom
)
```

### Progress Tracking (for the impatient)

```python
def progress(done, total, chunk):
    print(f"{done}/{total} rows ({100*done/total:.0f}%)")

fs.load(df, 'large_table', progress_callback=progress)
```

## Advanced Configs (You Probably Don't Need This)

```python
from frameshift import FrameShift, FrameShiftConfig

config = FrameShiftConfig(
    parallel_threads=4,     # Even 4 is pushing it - 2 threads is prob the practical max
    batch_size=5000,        # Optional: force rows-per-INSERT (default: auto-calculated)
)

fs = FrameShift(host=..., config=config)
```

Chunk sizing is automatic by default - Frameshift samples ~100 rows to estimate average row size, then calculates the optimal rows-per-INSERT to stay safely under 16MB. Use `batch_size` only if you want to override this.

## More Advanced Use Cases

For those who read documentation all the way through, here's more stuff you can do.

### Check for Duplicates Before Loading



```python
# Validate before you regret
validation = fs.validate_unique_key(df, 'order_id')
if not validation.is_unique:
    print(f"Uh oh: {validation.duplicate_count} duplicates found")
    print(validation.sample_duplicates)  # Show the offenders

# Or just let load() yell at you
fs.load(df, 'orders', unique_key='order_id', validate_unique=True)
```

### Analyze Your DISTKEY Before You Commit

Will your data be evenly distributed, or will one slice get 90% of the rows? Find out before Redshift performance tanks:

```python
# Check a single column
analysis = fs.analyze_distribution(df, 'customer_id', slice_count=16)
print(f"Skew ratio: {analysis.skew_ratio:.2f}x")  # 1.0 = perfect, 10.0 = yikes
print(f"Good DISTKEY? {analysis.is_good_distkey()}")

# Compare candidates (because you're indecisive)
comparison = fs.compare_distkeys(df, ['user_id', 'region', 'status'])
print(comparison)  # Shows which column has the best distribution
```

### Find Natural Keys (Let the Computer Do the Work you Dont Feel Like Doing)

Don't know which columns are unique? Let Frameshift figure it out:

```python
natural_keys = fs.find_natural_keys(df, max_columns=3)
for columns, unique_count in natural_keys:
    print(f"{' + '.join(columns)}: {unique_count} unique")
# Output might show: order_id: 5000 unique
#                    customer_id + order_date: 5000 unique
```

### Preview SQL Without Running It (Trust Issues?)

```python
# Method 1: generate_sql() for the paranoid
statements = fs.generate_sql(df, 'users', include_create=True)
for stmt in statements:
    print(stmt)  # Review before committing

# Method 2: dry_run config for the extra paranoid
config = FrameShiftConfig(dry_run=True)
fs = FrameShift(host=..., config=config)
result = fs.load(df, 'users')
print(result.sql_statements)  # See what WOULD have happened
```

### Get Schema Recommendations (Lazy Mode)

Let Frameshift analyze your data and tell you what to do:

```python
recs = fs.get_recommendations(df, 'transactions')
print(f"Best DISTKEY: {recs['distkey']['column']}")
print(f"Best SORTKEY: {recs['sortkey']['columns']}")
print(recs['sql'])  # Full CREATE TABLE statement
```

### Estimate Before Loading ("Measure Once, Load Twice"....wait, is that right?)

```python
estimates = fs.estimate_load(df)
print(f"Estimated chunks: {estimates['estimated_chunks']}")
print(f"Estimated size: {estimates['estimated_total_size_bytes'] / 1024 / 1024:.1f} MB")

if estimates['estimated_chunks'] > 100:
    print("This is gonna take a while. Coffee time.")
```

### Custom Column Types (Control Freak Edition!)

Override the inferred types when Frameshift guesses wrong:

```python
from frameshift.types import ColumnSpec, RedshiftType

custom_columns = [
    ColumnSpec('id', RedshiftType.INTEGER, nullable=False),
    ColumnSpec('description', RedshiftType.VARCHAR, length=4096),
    ColumnSpec('price', RedshiftType.DECIMAL, precision=10, scale=2),
]

fs.load(df, 'products', column_specs=custom_columns)
```

### Error Handling (Things Will Go Wrong)

```python
from frameshift import FrameShiftConfig

# Skip bad chunks and keep going (YOLO mode)
config = FrameShiftConfig(on_error='skip')

# Or log errors but continue (slightly responsible YOLO)
config = FrameShiftConfig(on_error='log')

# Or abort immediately (default, for the risk-averse)
config = FrameShiftConfig(on_error='abort')
```

### Multiple Connection Methods

```python
# Direct params (most common)
fs = FrameShift(host='...', database='...', user='...', password='...')

# Reuse existing connection (for the efficiency-minded)
import psycopg2
conn = psycopg2.connect(...)
fs = FrameShift(connection=conn)

# SQLAlchemy connection string (for the SQLAlchemy fans)
fs = FrameShift(connection_string='redshift+psycopg2://user:pass@host:5439/db')

# Use Amazon's official driver (for compliance checkboxes)
fs = FrameShift(host='...', driver='redshift-connector')
```

## When NOT to Use Frameshift

Seriously, if you have S3 access:
- **Production ETL** — Use COPY
- **More than 100K rows** — Use COPY
- **Scheduled jobs** — Use COPY
- **Anything important** — Use COPY

Motto: Frameshift is for when you *can't* use COPY. Not when you *don't want to* use COPY.

## License

MIT  (I may not have gotten accepted by these guys, but hey, happy to use their license!)
