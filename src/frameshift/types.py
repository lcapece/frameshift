"""
Type definitions and Redshift data type mapping for Frameshift.

This module handles the conversion between pandas/numpy dtypes
and Redshift SQL data types.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd


class RedshiftType(Enum):
    """Enumeration of Redshift data types."""

    # Numeric types
    SMALLINT = "SMALLINT"
    INTEGER = "INTEGER"
    BIGINT = "BIGINT"
    DECIMAL = "DECIMAL"
    REAL = "REAL"
    DOUBLE_PRECISION = "DOUBLE PRECISION"

    # Character types
    CHAR = "CHAR"
    VARCHAR = "VARCHAR"
    TEXT = "VARCHAR(MAX)"  # Redshift uses VARCHAR(MAX) for text

    # Boolean
    BOOLEAN = "BOOLEAN"

    # Date/Time types
    DATE = "DATE"
    TIMESTAMP = "TIMESTAMP"
    TIMESTAMPTZ = "TIMESTAMPTZ"
    TIME = "TIME"
    TIMETZ = "TIMETZ"

    # Binary
    VARBYTE = "VARBYTE"

    # Special types
    SUPER = "SUPER"  # For JSON/semi-structured data


@dataclass
class ColumnSpec:
    """
    Specification for a Redshift column.

    Attributes:
        name: Column name.
        redshift_type: Redshift data type.
        nullable: Whether the column allows NULL values.
        length: Length for VARCHAR/CHAR types.
        precision: Precision for DECIMAL type.
        scale: Scale for DECIMAL type.
        is_distkey: Whether this column is the distribution key.
        is_sortkey: Whether this column is part of the sort key.
        sortkey_position: Position in compound sort key (1-indexed).
        is_unique: Whether this column has a unique constraint.
        default: Default value for the column.
        encode: Compression encoding (e.g., 'lzo', 'zstd', 'raw').
    """

    name: str
    redshift_type: RedshiftType
    nullable: bool = True
    length: int | None = None
    precision: int | None = None
    scale: int | None = None
    is_distkey: bool = False
    is_sortkey: bool = False
    sortkey_position: int | None = None
    is_unique: bool = False
    default: Any = None
    encode: str | None = None

    def to_sql(self) -> str:
        """Generate SQL column definition."""
        parts = [f'"{self.name}"']

        # Type with length/precision
        if self.redshift_type in (RedshiftType.VARCHAR, RedshiftType.CHAR):
            length = self.length or 256
            parts.append(f"{self.redshift_type.value}({length})")
        elif self.redshift_type == RedshiftType.DECIMAL:
            precision = self.precision or 18
            scale = self.scale or 0
            parts.append(f"{self.redshift_type.value}({precision},{scale})")
        elif self.redshift_type == RedshiftType.VARBYTE:
            length = self.length or 64000
            parts.append(f"{self.redshift_type.value}({length})")
        else:
            parts.append(self.redshift_type.value)

        # Nullability
        if not self.nullable:
            parts.append("NOT NULL")

        # Default value
        if self.default is not None:
            parts.append(f"DEFAULT {self.default}")

        # Encoding
        if self.encode:
            parts.append(f"ENCODE {self.encode}")

        return " ".join(parts)


# Mapping from pandas/numpy dtypes to Redshift types
DTYPE_MAPPING: dict[str, RedshiftType] = {
    # Integer types
    "int8": RedshiftType.SMALLINT,
    "int16": RedshiftType.SMALLINT,
    "int32": RedshiftType.INTEGER,
    "int64": RedshiftType.BIGINT,
    "uint8": RedshiftType.SMALLINT,
    "uint16": RedshiftType.INTEGER,
    "uint32": RedshiftType.BIGINT,
    "uint64": RedshiftType.BIGINT,  # May overflow, but best we can do
    "Int8": RedshiftType.SMALLINT,
    "Int16": RedshiftType.SMALLINT,
    "Int32": RedshiftType.INTEGER,
    "Int64": RedshiftType.BIGINT,
    "UInt8": RedshiftType.SMALLINT,
    "UInt16": RedshiftType.INTEGER,
    "UInt32": RedshiftType.BIGINT,
    "UInt64": RedshiftType.BIGINT,
    # Float types
    "float16": RedshiftType.REAL,
    "float32": RedshiftType.REAL,
    "float64": RedshiftType.DOUBLE_PRECISION,
    "Float32": RedshiftType.REAL,
    "Float64": RedshiftType.DOUBLE_PRECISION,
    # Boolean
    "bool": RedshiftType.BOOLEAN,
    "boolean": RedshiftType.BOOLEAN,
    # String types
    "object": RedshiftType.VARCHAR,
    "string": RedshiftType.VARCHAR,
    "str": RedshiftType.VARCHAR,
    # Date/time types
    "datetime64[ns]": RedshiftType.TIMESTAMP,
    "datetime64[ns, UTC]": RedshiftType.TIMESTAMPTZ,
    "timedelta64[ns]": RedshiftType.BIGINT,  # Store as nanoseconds
    "date": RedshiftType.DATE,
    # Category (treat as varchar)
    "category": RedshiftType.VARCHAR,
}


def infer_redshift_type(
    series: pd.Series,
    varchar_max_length: int = 65535,
) -> ColumnSpec:
    """
    Infer the optimal Redshift column type from a pandas Series.

    Args:
        series: The pandas Series to analyze.
        varchar_max_length: Maximum length for VARCHAR columns.

    Returns:
        ColumnSpec with inferred type and properties.
    """
    dtype_str = str(series.dtype)
    col_name = str(series.name) if series.name is not None else "column"
    nullable = series.isna().any()

    # Check for timezone-aware datetime
    if hasattr(series.dtype, "tz") and series.dtype.tz is not None:
        return ColumnSpec(
            name=col_name,
            redshift_type=RedshiftType.TIMESTAMPTZ,
            nullable=nullable,
        )

    # Handle datetime types
    if pd.api.types.is_datetime64_any_dtype(series):
        return ColumnSpec(
            name=col_name,
            redshift_type=RedshiftType.TIMESTAMP,
            nullable=nullable,
        )

    # Check mapping
    if dtype_str in DTYPE_MAPPING:
        redshift_type = DTYPE_MAPPING[dtype_str]

        # For VARCHAR, calculate actual max length needed
        if redshift_type == RedshiftType.VARCHAR:
            max_len = _calculate_varchar_length(series, varchar_max_length)
            return ColumnSpec(
                name=col_name,
                redshift_type=redshift_type,
                nullable=nullable,
                length=max_len,
            )

        return ColumnSpec(
            name=col_name,
            redshift_type=redshift_type,
            nullable=nullable,
        )

    # Handle object dtype with more inspection
    if dtype_str == "object":
        return _infer_object_type(series, col_name, nullable, varchar_max_length)

    # Default to VARCHAR for unknown types
    return ColumnSpec(
        name=col_name,
        redshift_type=RedshiftType.VARCHAR,
        nullable=nullable,
        length=varchar_max_length,
    )


def _calculate_varchar_length(series: pd.Series, max_length: int) -> int:
    """Calculate the appropriate VARCHAR length for a series."""
    if series.dropna().empty:
        return 256  # Default for empty series

    # Get max string length
    try:
        str_series = series.dropna().astype(str)
        max_observed = str_series.str.len().max()

        # Add 20% buffer, round up to next power of 2 or nice number
        buffered = int(max_observed * 1.2)

        # Round to nice boundaries
        if buffered <= 16:
            return 16
        elif buffered <= 32:
            return 32
        elif buffered <= 64:
            return 64
        elif buffered <= 128:
            return 128
        elif buffered <= 256:
            return 256
        elif buffered <= 512:
            return 512
        elif buffered <= 1024:
            return 1024
        elif buffered <= 4096:
            return 4096
        elif buffered <= 16384:
            return 16384
        else:
            return min(buffered, max_length)
    except Exception:
        return 256


def _infer_object_type(
    series: pd.Series,
    col_name: str,
    nullable: bool,
    varchar_max_length: int,
) -> ColumnSpec:
    """Infer type for object dtype columns."""
    non_null = series.dropna()

    if non_null.empty:
        return ColumnSpec(
            name=col_name,
            redshift_type=RedshiftType.VARCHAR,
            nullable=True,
            length=256,
        )

    # Sample values to determine type
    sample = non_null.head(1000)
    first_val = sample.iloc[0]

    # Check for boolean-like
    unique_vals = set(sample.unique())
    if unique_vals <= {True, False, "true", "false", "True", "False", 1, 0, "1", "0"}:
        return ColumnSpec(
            name=col_name,
            redshift_type=RedshiftType.BOOLEAN,
            nullable=nullable,
        )

    # Check for date objects
    if isinstance(first_val, (pd.Timestamp,)):
        return ColumnSpec(
            name=col_name,
            redshift_type=RedshiftType.TIMESTAMP,
            nullable=nullable,
        )

    # Check for dict/list (JSON-like) - use SUPER
    if isinstance(first_val, (dict, list)):
        return ColumnSpec(
            name=col_name,
            redshift_type=RedshiftType.SUPER,
            nullable=nullable,
        )

    # Check for bytes
    if isinstance(first_val, bytes):
        max_len = max(len(x) for x in sample if isinstance(x, bytes))
        return ColumnSpec(
            name=col_name,
            redshift_type=RedshiftType.VARBYTE,
            nullable=nullable,
            length=min(max_len * 2, 64000),
        )

    # Default: VARCHAR with calculated length
    max_len = _calculate_varchar_length(series, varchar_max_length)
    return ColumnSpec(
        name=col_name,
        redshift_type=RedshiftType.VARCHAR,
        nullable=nullable,
        length=max_len,
    )


def python_to_sql_value(value: Any, redshift_type: RedshiftType) -> str:
    """
    Convert a Python value to SQL literal string.

    Args:
        value: The Python value to convert.
        redshift_type: The target Redshift type.

    Returns:
        SQL literal string representation.
    """
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "NULL"

    if pd.isna(value):
        return "NULL"

    if redshift_type == RedshiftType.BOOLEAN:
        return "TRUE" if value else "FALSE"

    if redshift_type in (
        RedshiftType.SMALLINT,
        RedshiftType.INTEGER,
        RedshiftType.BIGINT,
    ):
        return str(int(value))

    if redshift_type in (
        RedshiftType.REAL,
        RedshiftType.DOUBLE_PRECISION,
        RedshiftType.DECIMAL,
    ):
        if np.isinf(value):
            return "'Infinity'" if value > 0 else "'-Infinity'"
        return str(value)

    if redshift_type in (RedshiftType.TIMESTAMP, RedshiftType.TIMESTAMPTZ):
        if isinstance(value, pd.Timestamp):
            return f"'{value.isoformat()}'"
        return f"'{value}'"

    if redshift_type == RedshiftType.DATE:
        if isinstance(value, pd.Timestamp):
            return f"'{value.date()}'"
        return f"'{value}'"

    if redshift_type == RedshiftType.SUPER:
        import json

        json_str = json.dumps(value)
        escaped = json_str.replace("'", "''")
        return f"JSON_PARSE('{escaped}')"

    if redshift_type == RedshiftType.VARBYTE:
        if isinstance(value, bytes):
            return f"'{value.hex()}'::VARBYTE"
        return f"'{value}'::VARBYTE"

    # String types - escape single quotes
    str_val = str(value)
    escaped = str_val.replace("'", "''")
    # Also escape backslashes for Redshift
    escaped = escaped.replace("\\", "\\\\")
    return f"'{escaped}'"
