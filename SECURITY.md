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
| 0.3.x   | Yes       |
| < 0.3   | No        |

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
lexer. That model is written from AWS's documentation, and it is checked
against both interpretations of a backslash precisely so that a wrong
assumption about the server shows up as a failure rather than as a silent
hole. But it is still a model. The escaping is not exercised against a live
Redshift cluster in CI.

The same caveat applies more strongly to transaction handling. The
savepoint, rollback, and `commit_every` behavior is tested against a fake
connection that records statements -- not against psycopg2 or
redshift-connector talking to a real server. The failure paths in
particular are the least verified part of the library.

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

### 0.3.0

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
