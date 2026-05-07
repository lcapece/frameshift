# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/lcapece/frameshift/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/lcapece/frameshift/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/lcapece/frameshift/releases/tag/v0.1.0
