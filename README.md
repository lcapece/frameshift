# Frameshift — load a pandas DataFrame into Redshift without S3

**You have a DataFrame. You need it in Amazon Redshift. You cannot use S3.**

Maybe nobody will give you a bucket. Maybe your VPC has never heard of S3
and has no plans to. Maybe the ticket asking for either has been "in
triage" since March. Whatever the reason, `COPY` — the answer in every
tutorial, every AWS doc, and every Stack Overflow reply you have read in
the last twenty minutes — is not available to you.

Frameshift is the fire escape. It uses the Redshift connection you already
have and asks for nothing else.

```bash
pip install "frameshift[psycopg2]"
```

```python
from frameshift import FrameShift

with FrameShift(host="...", database="...", user="...", password="...") as fs:
    fs.load(df, "my_table")     # creates the table if it isn't there
```

That's it. That's the library.

## This is a bad idea and you should probably use COPY

Let's get this out of the way, because you will hear it from someone
eventually and it may as well be from the README:

**Frameshift is roughly 10-20x slower than `COPY`.** There. Said it. Right
under the install instructions, where you can't miss it.

**Loading Redshift with `INSERT` is the wrong way to load Redshift.** AWS
says so. Every consultant says so. Your colleague who has Opinions about
data warehouses will absolutely say so. They are all correct. Redshift wants
to slurp files out of S3 in parallel across every slice it owns. Frameshift
politely hands the leader node one statement at a time and waits.

(We tried being clever. Sixteen parallel threads, mimicking Redshift's own
MD5 hash distribution. The leader node serializes everything anyway. It was
a lovely afternoon and it accomplished nothing.)

**Do not build a production pipeline on this.** If you catch yourself
scheduling it nightly, that is not a Frameshift feature, that is a cry for
help. Go file the S3 ticket. This library is for getting out of a bind: the
one-off load, the lookup table, the test fixture, the notebook that has to
be done before the meeting, the locked-down environment where the "right"
answer is somebody else's department.

**It's quick and dirty, and it intends to stay that way.** The one promise
it makes is that quick and dirty will still be *correct*: your quotes are
escaped, your types are sane, your statements fit inside Redshift's limits,
and if something explodes it rolls back instead of leaving you with a table
that's 60% loaded and 100% your problem.

If you can reach S3, close this tab and use `COPY`. Sincerely. We'll be here
if it doesn't work out.

## Is this you?

If any of these is your afternoon, you're in the right place:

- **"I don't have S3 write access."** You can query Redshift all day, but
  a bucket? That's a different team, a different ticket, and a different
  quarter.
- **"My VPC can't reach S3."** No endpoint, no NAT gateway, no dice. `COPY`
  can't fetch a file it can't get to.
- **"We're air-gapped."** Or in GovCloud, or behind a proxy that treats
  `s3.amazonaws.com` as a personal insult.
- **"Nobody will give me the S3 credentials."** They exist. Somewhere.
  Someone has them. It is not you.
- **"I'm stuck on the Redshift Data API."** With its 100 KB statement
  ceiling. (`FrameShiftConfig.for_data_api()` handles the arithmetic.)
- **"It's a Lambda / notebook / CI job."** Staging a file and cleaning it
  up is more work than the actual load.
- **"It's 200 rows, once."** Standing up an S3 pipeline for 200 rows is
  like renting a freight elevator to move a houseplant.

If none of those are you: `COPY`, or
[`awswrangler`](https://github.com/aws/aws-sdk-pandas), which wraps it
nicely. No hard feelings.

### Where the wheels come off

Orders of magnitude, not benchmarks. Your columns, your cluster, and your
network all matter more than the row count.

| Rows | Verdict |
| --- | --- |
| Up to ~10k | Fine. You won't even notice. |
| ~10k–100k | Works. You'll notice. Acceptable if S3 truly isn't an option. |
| ~100k–1M | Now you're just hurting yourself. |
| Over ~1M | Go get S3 access. We both know it's time. |

`estimate_load()` will tell you which row you're on before you commit to
finding out the hard way.

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
```

That is the whole API for most uses. Types are inferred from the DataFrame
and the table is created if it does not exist.

If you happen to know your table wants a sort or distribution key, they are
one keyword each — but if you are here to get unblocked, skip them:

```python
fs.load(df, "events", sortkey="created_at", distkey="user_id")
```

`validate_unique=True` is the one extra worth knowing about, because
Redshift does not enforce uniqueness constraints — a duplicate you do not
catch here is a duplicate you find in a report next quarter:

```python
fs.load(df, "events", unique_key="event_id", validate_unique=True)
```

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

### When things go wrong

By default (`on_error="abort"`) the load is one transaction: all of it
lands or none of it does. A failure rolls back and leaves your connection
usable, which sounds like the bare minimum until you meet the libraries that
don't.

With `on_error="skip"` or `"log"`, each chunk gets its own savepoint, so one
bad chunk rolls back alone and the rest carries on. Check `result.success`
and `result.errors` afterwards — a partial load says `success=False` and
tells you exactly which rows didn't make it, rather than letting you find
out from a dashboard in three weeks.

## Seeing the SQL before you run it

```python
for sql in fs.generate_sql(df, "users"):
    print(sql)
```

Or set `dry_run=True`, which makes `load()` render everything without
touching the database. Good for reviewing what you're about to do, for
emailing the SQL to the DBA who has the permissions you don't, and for
satisfying yourself that this library isn't doing anything clever behind
your back. (It isn't. That's the point.)

One caveat: generated SQL has your data inlined in it. Don't paste it into
a public ticket.

## How much will this hurt?

```python
estimates = fs.estimate_load(df, "users")
```

Tells you the row count, how many `INSERT` statements it will take, and
warns you when you have wandered past what this approach is good for. Worth
thirty seconds before a load you are unsure about.

<details>
<summary><b>Optional: schema inspection and DISTKEY analysis</b></summary>

Skip this if you are here to get unblocked — it exists for the case where
the table you are creating in a hurry is one you will keep.

```python
schema = fs.infer_schema(df, "users")
print(schema.to_create_table_sql())     # see the DDL before it runs

recommendations = fs.get_recommendations(df, "users")
```

Choosing a `DISTKEY` badly is the classic Redshift mistake: the data lands
unevenly across slices and every query afterwards pays for it. Frameshift
simulates Redshift's hash distribution locally, so you can see the skew
without creating anything:

```python
analysis = fs.analyze_distribution(df, "user_id")
print(analysis.summary())

comparison = fs.compare_distkeys(df, ["user_id", "account_id", "region"])
```

And if you do not know what your key is:

```python
validation = fs.validate_unique_key(df, ["order_id", "line_number"])
candidates = fs.find_natural_keys(df, max_columns=3)
```

</details>

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

`VARCHAR` lengths are measured in UTF-8 bytes, because that is what Redshift
actually limits — not characters. One emoji is four bytes. Frameshift counts
correctly so your column doesn't reject the very data it was sized for.

Columns of `1`/`0` integers are **not** inferred as `BOOLEAN`, no matter how
much they look like one. They're usually counts, ids, or an enum somebody
was clever about, and guessing wrong here is not reversible. Pass an explicit
`column_spec` if you really do mean boolean.

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
| Redshift `COPY` | You can reach S3. This is the right answer and you know it. |
| [`awswrangler`](https://github.com/aws/aws-sdk-pandas) | You can reach S3 and would like a nice Python wrapper around the right answer. |
| `pandas.to_sql` | You want something generic and have no feelings about `DISTKEY` or statement sizing. |
| **Frameshift** | S3 is not happening, and you'd still like the table to come out sensible. |

## Questions you are probably typing into Google right now

**How do I load a DataFrame into Redshift without S3?**
This library, and you have found it, so that's one problem solved. `COPY`
needs a file staged in S3; Frameshift generates `INSERT` statements instead
and needs nothing but a database connection. It is slower. See the table
above for how much slower and when to stop.

**What if my IAM role has no S3 write access?**
Then `COPY` is out and you're in the right place. Frameshift never touches
S3 and wants no IAM permissions at all — just the Redshift privileges to
`CREATE TABLE` and `INSERT`.

**Can I use this from a VPC with no S3 endpoint?**
Yes. This is one of the reasons it exists. `COPY` can't fetch a file it has
no route to. Frameshift only talks to Redshift, which you can evidently
already reach, or you'd have a much larger problem than this README.

**Why is `pandas.to_sql` so slow against Redshift?**
Because it sends one `INSERT` per row, and every single one is a round trip
the leader node has to think about. Frameshift packs as many rows as will
fit into each statement, up to Redshift's 16 MB limit — orders of magnitude
fewer round trips. Still not `COPY`. Nothing is `COPY` except `COPY`.

**Does this work with the Redshift Data API?**
Yes. `FrameShiftConfig.for_data_api()` sizes everything under its 100 KB
statement ceiling so you don't have to think about it.

**Is it safe against SQL injection?**
Values are escaped to match Redshift's own `QUOTE_LITERAL`, and identifiers
are validated against an allowlist rather than just wrapped in quotes and
hoped over. [SECURITY.md](SECURITY.md) has the guarantees and — more
importantly — their limits. Read it before you pass a table name that came
from a user.

**Can I use this in production?**
You *can*. Sharp objects are also legal. See the second section of this
README, which was written specifically for the person asking this.

## Requirements

Python 3.10+, pandas 1.5+. A driver is optional -- see above.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). If you are touching SQL generation,
`tests/test_injection.py` is the file that matters; read its header first.

## License

MIT
