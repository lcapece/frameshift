# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-07-16

A hardening and correctness release. **Upgrading is recommended for all
users**: 0.2.0 and earlier could be induced to execute attacker-supplied
SQL through a DataFrame's column names, and silently corrupted several
kinds of data.

This is a minor version rather than a patch because the changes below break
existing installs, even though most of them are bug fixes. Read "Breaking
changes" before upgrading.

### Breaking changes

- **`psycopg2` is no longer installed by default.** `pip install frameshift`
  previously pulled in `psycopg2-binary`, so `FrameShift(host=...)` worked
  out of the box; it now raises `RedshiftConnectionError` until a driver is
  present. Install `frameshift[psycopg2]` to restore the previous behavior,
  or pass your own connection.

  The default was wrong for this library: it forced a driver on everyone
  using redshift-connector, SQLAlchemy, or an existing connection, and in
  the locked-down environments Frameshift exists for, the driver is rarely
  the caller's choice.
- **Python 3.10 or later is required.** 0.2.0 declared 3.9 support but used
  3.10-only syntax and could not import there, so this breaks no working
  install.
- **Object columns now infer as `SUPER` or `VARBYTE`** where they
  previously became `VARCHAR`. This is a bug fix -- the inspection code
  existed but was unreachable -- but it changes the DDL generated for dict,
  list, and bytes columns. If you depend on the old behavior, pass an
  explicit `column_spec`.
- **Columns of `1`/`0` integers no longer infer as `BOOLEAN`.**
- **`batch_size` is now a hard cap** on rows per INSERT. It was previously
  advisory, so loads may issue more, smaller statements than before.

### Security

See [SECURITY.md](SECURITY.md) for the full model.

- **Fixed SQL injection through identifiers.** Table, schema, and column
  names -- and `distkey`, `sortkey`, `primary_key`, `unique_key` -- were
  interpolated into double quotes with no validation or escaping. A name
  containing `"` escaped its quoting and could append arbitrary SQL. This
  was reachable by anyone able to influence column names, including code
  that builds a DataFrame from user input or an uploaded file. Identifiers
  are now validated against Redshift's standard identifier rules and
  rejected if unsafe.
- **Fixed SQL injection through `DEFAULT` and `ENCODE`.** Both
  interpolated caller input directly into DDL. Defaults are now rendered as
  typed literals; encodings are checked against Redshift's documented set.
  `TableSchema.backup` is validated.
- **NUL bytes are rejected** rather than passed to a server that cannot
  store them.
- **Added `tests/test_injection.py`**, which verifies escaping by parsing
  generated SQL the way the server would, under both interpretations of a
  backslash. The previous tests checked quotes and backslashes separately,
  which is why the above survived.

### Fixed

- **Object columns were never inspected.** `_infer_object_type` was
  unreachable -- `object` maps to `VARCHAR` in the dtype table, which was
  consulted first -- so every dict, list, and bytes column silently loaded
  as text instead of `SUPER` or `VARBYTE`. Loading a `SUPER` column also
  raised `ValueError`, because `pd.isna()` does not return a scalar for
  list-like input. See "Breaking changes": this alters generated DDL.
- **String booleans loaded inverted.** Rendering tested `if value`, and
  every non-empty string is truthy, so `"false"` became `TRUE`.
- **`VARCHAR` lengths are measured in UTF-8 bytes**, which is what Redshift
  limits. Measuring characters undersized any column holding non-ASCII text,
  so inference produced a column the data did not fit in.
- **Failed loads now roll back.** A failure previously left an aborted
  transaction open on a connection that Frameshift reuses -- and that the
  caller may own -- breaking every later statement on it. The cursor is
  always closed.
- **`on_error="skip"` and `"log"` now work.** A failed statement poisons the
  transaction, so the first bad chunk used to make every subsequent chunk
  fail: N errors for one root cause, nothing loaded. Chunks now run inside
  savepoints when failures are tolerated.
- **`dry_run` no longer touches the connection**, and reports
  `created_table` correctly.
- **`generate_sql()` no longer mutates shared config.** It swapped
  `self.config` in place, corrupting concurrent loads on the same instance
  and leaking `dry_run=True` if it raised.
- **SQLAlchemy credentials are percent-encoded.** A password containing
  `@`, `/`, or `:` was parsed as URL structure.
- `estimate_load()` accounts for the INSERT prefix; `estimate_chunks()` no
  longer overcounts by one when rows divide evenly.
- `find_natural_keys()` honours `max_columns` above 3.
- `if_exists` is validated; an unrecognized value silently appended.
- `NaN` renders as `NULL` rather than the literal `nan`; float literals
  round-trip exactly; `Infinity` carries an explicit cast.
- `__version__` is read from package metadata instead of drifting.

### Changed

- Rewrote the README around the actual use case, with explicit guidance on
  where INSERT-based loading stops being reasonable, and an honest
  comparison against `COPY`, `awswrangler`, and `pandas.to_sql`.
- Added `SECURITY.md`.
- Examples run without a database and are executed in CI. Most previously
  constructed a `MagicMock` and called it a demonstration.
- CI tests Python 3.10-3.13. It previously tested 3.9, which cannot run
  this package, and could not have been passing: `mypy` reported 23 errors
  and `black` wanted to reformat 15 files.

## [0.2.0] - 2026-05-07

### Added

- Concise README and examples centered on the supported loader flow

### Changed

- Simplified the load path to a single-threaded flow
- Reduced the configuration surface to the loader options in use
- Rewrote the README and examples in a concise, neutral style

## [0.1.0] - 2024-12-15

### Added

- Initial release of Frameshift
- Core `FrameShift` class for DataFrame-to-Redshift loading
- `FrameShiftConfig` for customizable loading options
- `SchemaInferer` for automatic Redshift schema inference
- `TableSchema` for programmatic table definition
- `DataFrameChunker` for intelligent data chunking within 16 MB limit
- `SQLGenerator` for multi-row INSERT statement generation
- `DistributionAnalyzer` for DISTKEY candidate analysis using MD5 hashing
- `UniqueKeyValidator` for unique constraint validation
- Support for DISTKEY and SORTKEY specification
- Support for primary key and unique constraints
- Automatic type conversion from pandas to Redshift types
- Dry run mode for SQL preview
- Progress callback support for large loads
- Multiple connection methods (psycopg2, redshift-connector, SQLAlchemy)
- Comprehensive test suite
- Example scripts for common use cases
- Full documentation with use case guidance

### Features

- **Schema Inference**: Automatically infers optimal Redshift data types from pandas DataFrames
- **Distribution Analysis**: Predicts data skew using MD5 hash simulation to help choose DISTKEY
- **Unique Key Validation**: Validates unique constraints before loading to prevent errors
- **Intelligent Chunking**: Automatically splits data into chunks that fit within Redshift's 16 MB statement limit
- **Multiple Connection Options**: Supports psycopg2, amazon-redshift-connector, and SQLAlchemy
- **Dry Run Mode**: Generate SQL statements without executing for review and testing

### Documentation

- Comprehensive README with usage examples
- Clear guidance on when to use Frameshift vs COPY from S3
- API reference documentation
- Example scripts covering:
  - Basic usage
  - Schema inference
  - Distribution analysis
  - Unique key validation

[Unreleased]: https://github.com/lcapece/frameshift/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/lcapece/frameshift/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/lcapece/frameshift/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/lcapece/frameshift/releases/tag/v0.1.0
