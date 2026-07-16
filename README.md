# Frameshift

Load pandas DataFrames into Amazon Redshift when you cannot use S3.

```bash
pip install "frameshift[psycopg2]"
```

## Read this before you use it

**If you can write to S3, use `COPY` instead.** It is not close. `COPY`
loads in parallel across every slice in your cluster; Frameshift sends
`INSERT` statements down a single connection, and the leader node parses
every one of them. For a large table the difference is minutes against
hours.

Frameshift is not a faster loader, a smarter loader, or a `COPY`
replacement. It exists for the case where `COPY` is not on the table at all:

- **No S3 write access.** Your role can read from Redshift but nobody will
  grant you a bucket, and the ticket to get one has been open for a month.
- **No network path to S3.** A locked-down VPC with no S3 endpoint and no
  NAT gateway. `COPY` cannot fetch what it cannot reach.
- **The Redshift Data API**, whose 100 KB statement limit rules out the
  large `COPY` payloads and needs careful statement sizing.
  (`FrameShiftConfig.for_data_api()`.)
- **Somewhere ephemeral** -- a Lambda, a notebook, a CI job -- where
  staging a file and cleaning it up costs more than the load is worth.
- **Modest data.** A few thousand rows of reference data, a lookup table, a
  test fixture. `COPY`'s setup cost exceeds the whole job.

If none of those describe you, use `COPY`, or
[`awswrangler`](https://github.com/aws/aws-sdk-pandas), which wraps it well.

### Where the line falls

These are orders of magnitude, not benchmarks. Your columns, your cluster,
and your network all matter more than the row count.

| Rows | Verdict |
| --- | --- |
| Up to ~10k | Frameshift is fine. You will not notice. |
| ~10k–100k | Works, and you will feel it. Acceptable if S3 is genuinely unavailable. |
| ~100k–1M | Painful. Only if you have no other option. |
| Over ~1M | Find a way to use `COPY`. Really. |

`estimate_load()` will tell you what you are in for before you commit.

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

The table is created if it does not exist, with types inferred from the
DataFrame.

### Bring your own connection

Frameshift does not require a driver, and in the environments it is written
for the driver is often not your choice. Pass whatever you already have:

```python
fs = FrameShift(connection=my_existing_connection)
```

Any DB-API connection works. Frameshift will not close a connection it did
not open.

Or install one:

```bash
pip install "frameshift[psycopg2]"             # psycopg2
pip install "frameshift[redshift-connector]"   # Amazon's driver
pip install "frameshift[sqlalchemy]"           # SQLAlchemy
```

## Loading

```python
fs.load(df, "users", if_exists="append")    # default
fs.load(df, "users", if_exists="replace")   # DROP, then CREATE
fs.load(df, "users", if_exists="fail")      # raise if the table exists

fs.load(df, "events", distkey="user_id", sortkey="created_at")
fs.load(df, "events", primary_key="id", unique_key="id", validate_unique=True)
```

`validate_unique=True` checks the DataFrame before sending anything, which
is worth doing: Redshift does not enforce uniqueness constraints, so a
duplicate you do not catch here is a duplicate you find in a report later.

## Configuration

```python
from frameshift import FrameShift, FrameShiftConfig

config = FrameShiftConfig(
    batch_size=1000,        # rows per INSERT (a hard cap)
    commit_every=10,        # commit every N chunks; 0 = one transaction
    on_error="abort",       # "abort" | "skip" | "log"
    dry_run=False,          # render SQL without executing it
)

fs = FrameShift(host="...", database="...", user="...", password="...", config=config)
```

Presets: `FrameShiftConfig.for_data_api()`,
`for_small_datasets()`, `for_large_datasets()`.

### Errors and transactions

By default (`on_error="abort"`) a load is one transaction: it either lands
or it does not, and a failure rolls back.

With `on_error="skip"` or `"log"`, each chunk runs inside a savepoint, so a
bad chunk is rolled back on its own and the rest of the load continues.
Check `result.success` and `result.errors` -- a partial load reports
`success=False` and tells you which rows were lost.

## Seeing the SQL before you run it

```python
statements = fs.generate_sql(df, "users")
for sql in statements:
    print(sql)
```

Or set `dry_run=True` in the config, which makes `load()` render statements
without touching the database. Useful for review, for handing SQL to a DBA
who will run it for you, and for understanding what the library actually
does.

Note that generated SQL contains your data inline. Treat it accordingly.

## Schema and analysis helpers

Frameshift infers a schema from the DataFrame, and can explain its choices:

```python
schema = fs.infer_schema(df, "users")
print(schema.to_create_table_sql())

recommendations = fs.get_recommendations(df, "users")
estimates = fs.estimate_load(df, "users")
```

### Distribution analysis

Choosing a `DISTKEY` badly is the classic Redshift mistake: the data lands
unevenly across slices and every query pays for it. This simulates
Redshift's hash distribution locally, so you can see the skew before you
create the table:

```python
analysis = fs.analyze_distribution(df, "user_id")
print(analysis.summary())

comparison = fs.compare_distkeys(df, ["user_id", "account_id", "region"])
```

### Key discovery

```python
validation = fs.validate_unique_key(df, ["order_id", "line_number"])
candidates = fs.find_natural_keys(df, max_columns=3)
```

## Type mapping

| pandas | Redshift |
| --- | --- |
| `int8`, `int16` | `SMALLINT` |
| `int32` | `INTEGER` |
| `int64` | `BIGINT` |
| `float32` | `REAL` |
| `float64` | `DOUBLE PRECISION` |
| `bool` | `BOOLEAN` |
| `object` (text) | `VARCHAR(n)`, sized from the data |
| `object` (dict/list) | `SUPER` |
| `object` (bytes) | `VARBYTE` |
| `datetime64[ns]` | `TIMESTAMP` |
| `datetime64[ns, tz]` | `TIMESTAMPTZ` |

`VARCHAR` lengths are measured in UTF-8 bytes, which is what Redshift
limits -- not characters. A column of emoji needs four times the length its
character count suggests.

Columns of `1`/`0` integers are **not** inferred as `BOOLEAN`. They are far
more often counts, ids, or enums, and the coercion would be irreversible.
Pass an explicit `column_spec` if you want that.

Override inference per column:

```python
from frameshift import ColumnSpec, RedshiftType

fs.load(df, "users", column_specs=[
    ColumnSpec(name="id", redshift_type=RedshiftType.BIGINT, nullable=False),
    ColumnSpec(name="notes", redshift_type=RedshiftType.VARCHAR, length=4096),
])
```

## Security

Frameshift generates SQL as text, so escaping is its responsibility. Values
are escaped to match Redshift's own `QUOTE_LITERAL`; identifiers are
validated against an allowlist rather than merely quoted. The guarantees,
the limits, and how to report a problem are in [SECURITY.md](SECURITY.md).

If you are passing table names from untrusted input, read that file first.

## Alternatives

| Tool | Use it when |
| --- | --- |
| Redshift `COPY` | You can reach S3. This is the right answer. |
| [`awswrangler`](https://github.com/aws/aws-sdk-pandas) | You can reach S3 and want a good Python wrapper around `COPY`. |
| `pandas.to_sql` | You need something generic and do not care about `DISTKEY`/`SORTKEY` or statement sizing. |
| **Frameshift** | You cannot reach S3, and still want Redshift-aware DDL and correctly sized statements. |

## Requirements

Python 3.10+, pandas 1.5+. A driver is optional -- see above.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). If you are touching SQL generation,
`tests/test_injection.py` is the file that matters; read its header first.

## License

MIT
