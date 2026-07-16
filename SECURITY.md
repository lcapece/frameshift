# Security Policy

## Reporting a vulnerability

Please report security issues privately via
[GitHub's private vulnerability reporting](https://github.com/lcapece/frameshift/security/advisories/new),
not as a public issue.

Include a description, a minimal reproduction if you have one, and the
Frameshift version. You can expect an acknowledgement within a few days.
This is a small volunteer project, so please allow reasonable time for a
fix before public disclosure.

## Supported versions

| Version | Supported |
| ------- | --------- |
| 1.1.x   | Yes       |
| < 1.1   | No        |

## The security model, and why it matters here

**Frameshift builds SQL as text.** That is not an implementation detail --
it is the entire point of the library. Redshift's `COPY` command needs a
staging file in S3, and Frameshift exists for people who cannot use one.
What it does instead is render your DataFrame into `INSERT` statements.

This means the library is responsible for escaping, and it means you should
know what it does and does not guarantee.

### What Frameshift guarantees

**Values are escaped as SQL literals.** Every value passes through
`python_to_sql_value`, which escapes strings exactly as Redshift's own
[`QUOTE_LITERAL`](https://docs.aws.amazon.com/redshift/latest/dg/r_QUOTE_LITERAL.html)
function does: single quotes and backslashes are both doubled. Backslashes
matter because Redshift, forked from PostgreSQL 8.0, treats a backslash
inside an ordinary string literal as an escape character -- so a value
containing `\'` would otherwise consume its own closing quote and let the
rest of the cell parse as SQL.

`tests/test_injection.py` verifies this by parsing the generated SQL the way
the server would, under both interpretations of a backslash, for a corpus of
breakout payloads. Assertions are on containment, not on string shape.

**Identifiers are validated, not just quoted.** Table, schema, and column
names -- along with `distkey`, `sortkey`, and key constraints -- cannot be
parameterized by any driver; there is no placeholder syntax for them. They
are checked against an allowlist matching Redshift's standard identifier
rules (leading letter or underscore; letters, digits, underscores, or dollar
signs thereafter; 127 bytes maximum) and rejected otherwise. A name
containing a double quote is rejected rather than escaped.

**`DEFAULT` and `ENCODE` are not raw SQL.** A column default is rendered as
a typed literal; a compression encoding is checked against Redshift's
documented set.

**NUL bytes are rejected** rather than passed to a server that cannot store
them.

### What Frameshift does not protect you from

**Untrusted table or column names are still your decision.** Validation
rejects the dangerous cases, but if you pass a table name straight from an
HTTP request, you are letting a caller choose which table gets written. That
is an authorization question, and no amount of quoting answers it.

**Credentials are yours to manage.** Frameshift takes a host, user, and
password, or a connection you built. It does not read environment variables,
touch a credentials file, or log connection parameters -- but it also does
not encrypt anything or manage rotation.

**Generated SQL contains your data in plaintext.** `dry_run=True` and
`generate_sql()` return statements with every value inlined. If you log
them, print them, or paste them into a ticket, you have copied your data
there too. Statements can also be large -- up to the configured statement
size, which defaults to 15 MB.

**Errors may quote your data.** A failed chunk's error message can include
the server's response, which may contain a value from the offending row.

### What the tests do and do not prove

`tests/test_injection.py` parses generated SQL with a model of Redshift's
lexer, written from AWS's documentation and checked against both
interpretations of a backslash so that a wrong assumption shows up as a
failure rather than a silent hole.

That model has been checked against a real cluster. Every payload in
`BREAKOUT_SEQUENCES` -- backslash-quote combinations, quote breakouts, union
attempts, unicode, embedded newlines -- was rendered by
`python_to_sql_value` and executed against Redshift Serverless
(`PostgreSQL 8.0.2 / Redshift 1.0.300094`). All of them round-tripped
byte-for-byte as data, and a table named as the drop target of the payloads
was still standing afterwards.

That run also settled the question the escaping turns on. Redshift has no
`standard_conforming_strings` parameter (`SHOW` errors with "unrecognized
configuration parameter"), and `select 'a\b'` returns a two-character string
whose second character is a backspace -- so a backslash in an ordinary
literal *is* an escape character, and doubling it is required. This is why
the escaping must not be "modernized" to current PostgreSQL semantics.

**Not yet verified against a live cluster:** the transaction machinery.
Savepoints, rollback, and `commit_every` are tested against a fake
connection that records statements, not against psycopg2 or
redshift-connector driving a real server. The live testing was done through
the Redshift Data API, which does not exercise that code path. Server-side
rejection of bad data has been confirmed to leave the table clean, but
Frameshift's own rollback handling has not.

If you run Frameshift against a real cluster and see it behave differently
from what is described here, that is a bug worth reporting, and the report
is genuinely useful.

### If you are hardening a deployment

- Grant the Redshift user only what it needs. Frameshift issues
  `CREATE TABLE`, `DROP TABLE` (with `if_exists="replace"`), and `INSERT`.
  It never needs superuser.
- Load into a dedicated schema rather than `public`.
- Treat `generate_sql()` output as sensitive.
- Prefer passing your own connection so that TLS settings, timeouts, and
  credential handling stay under your control.

## Version history of security-relevant changes

### 1.1.0

Hardening release. Several issues in 0.2.0 were fixed:

- **Identifier injection.** Table, schema, and column names were
  interpolated into double quotes with no validation or escaping, so a name
  containing `"` escaped its quoting entirely and could append arbitrary
  SQL. Identifiers are now validated against an allowlist. This was
  reachable by anyone who could influence a DataFrame's column names --
  including code that builds columns from user input or from a parsed file.
- **`DEFAULT` and `ENCODE` injection.** Both interpolated caller input
  directly into DDL.
- **NUL bytes** were passed through to the server.
- **Crash on JSON columns.** `pd.isna()` raises rather than returning a
  scalar for lists and dicts, so a SUPER column raised `ValueError` instead
  of loading.

No CVE was assigned for these. If you are running 0.2.0 or earlier, upgrade.
