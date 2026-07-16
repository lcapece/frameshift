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

from frameshift.exceptions import DataTypeError, ValidationError
from frameshift.identifiers import quote_identifier


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


# Compression encodings Redshift accepts in an ENCODE clause. Anything
# outside this set is rejected rather than interpolated into DDL.
VALID_ENCODINGS = frozenset(
    {
        "RAW",
        "AZ64",
        "BYTEDICT",
        "DELTA",
        "DELTA32K",
        "LZO",
        "MOSTLY8",
        "MOSTLY16",
        "MOSTLY32",
        "RUNLENGTH",
        "TEXT255",
        "TEXT32K",
        "ZSTD",
    }
)


def _validate_encoding(encode: str) -> str:
    """
    Validate a compression encoding against Redshift's documented set.

    Args:
        encode: The encoding name, in any case.

    Returns:
        The encoding, upper-cased.

    Raises:
        ValidationError: If the encoding is not recognized.
    """
    normalized = str(encode).strip().upper()
    if normalized not in VALID_ENCODINGS:
        raise ValidationError(
            f"Unknown compression encoding {encode!r}",
            field="encode",
            expected=", ".join(sorted(VALID_ENCODINGS)),
            received=str(encode),
        )
    return normalized


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
        """
        Generate the SQL column definition.

        Raises:
            ValidationError: If the column name is not a safe identifier.
        """
        parts = [quote_identifier(self.name, kind="column")]

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

        # Default value. Rendered as a typed literal rather than raw text so
        # that a caller-supplied default cannot inject DDL.
        if self.default is not None:
            parts.append(f"DEFAULT {python_to_sql_value(self.default, self.redshift_type)}")

        # Encoding
        if self.encode:
            parts.append(f"ENCODE {_validate_encoding(self.encode)}")

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
    nullable = bool(series.isna().any())

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
    """
    Calculate the appropriate VARCHAR length for a series.

    Redshift's VARCHAR(n) bounds n *bytes*, not characters, so length is
    measured over UTF-8 encoded values. Measuring characters undersizes any
    column holding non-ASCII text -- a single emoji is four bytes -- and the
    load then fails on data that inference claimed would fit.

    Args:
        series: The series to measure.
        max_length: The configured ceiling for VARCHAR length.

    Returns:
        A VARCHAR length in bytes, rounded up to a conventional boundary.
    """
    non_null = series.dropna()
    if non_null.empty:
        return 256  # Nothing to measure; a small default is fine.

    try:
        max_observed = max(
            len(str(value).encode("utf-8")) for value in non_null
        )
    except (TypeError, ValueError):
        return min(256, max_length)

    if max_observed == 0:
        return 16

    # 20% headroom for values not present in this particular DataFrame.
    buffered = int(max_observed * 1.2) + 1

    for boundary in (16, 32, 64, 128, 256, 512, 1024, 4096, 16384):
        if buffered <= boundary:
            return min(boundary, max_length)

    return min(buffered, max_length)


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


def _is_null(value: Any) -> bool:
    """
    Determine whether a value should be rendered as SQL NULL.

    ``pd.isna`` raises on list- and dict-like input rather than returning a
    scalar, so container types (which reach us via the SUPER path) are
    checked before it is called.
    """
    if value is None:
        return True

    if isinstance(value, (list, tuple, set, dict, np.ndarray)):
        # A container is a value in its own right; only None is null.
        return False

    try:
        result = pd.isna(value)
    except (TypeError, ValueError):
        return False

    # pd.isna returns an array for some inputs; treat those as non-null.
    return bool(result) if isinstance(result, (bool, np.bool_)) else False


def escape_string_literal(value: str) -> str:
    """
    Render a string as a complete, quoted SQL string literal.

    The escaping matches Redshift's own ``QUOTE_LITERAL`` function, which
    "appropriately doubles any embedded single quotation marks and
    backslashes" and returns a plain ``'...'`` literal. Both characters are
    doubled because Redshift -- forked from PostgreSQL 8.0, before the 9.1
    change of ``standard_conforming_strings`` to ``on`` -- treats a
    backslash inside an ordinary literal as an escape character.

    That last point is the reason this function exists rather than a bare
    ``f"'{value}'"``. On Redshift a lone backslash escapes whatever follows
    it, so an unescaped ``\\'`` in a value would consume the closing quote
    and let the rest of the cell parse as SQL.

    Do not "modernize" this to leave backslashes alone: that is correct for
    current PostgreSQL and wrong for Redshift, and it would reopen the
    breakout described above. The property is covered from both server
    modes in ``tests/test_injection.py``.

    Args:
        value: The raw string to render.

    Returns:
        A complete SQL literal, including the surrounding single quotes.

    Raises:
        DataTypeError: If the string contains a NUL byte, which Redshift
            cannot store in a text column.

    See Also:
        https://docs.aws.amazon.com/redshift/latest/dg/r_QUOTE_LITERAL.html
    """
    if "\x00" in value:
        raise DataTypeError(
            "String contains a NUL byte (\\x00), which Redshift cannot store "
            "in a text column. Strip or replace it before loading, e.g. "
            "df[col] = df[col].str.replace('\\x00', '', regex=False)",
            value=value[:50],
        )

    escaped = value.replace("\\", "\\\\").replace("'", "''")
    return f"'{escaped}'"


def python_to_sql_value(value: Any, redshift_type: RedshiftType) -> str:
    """
    Convert a Python value to a SQL literal string.

    Args:
        value: The Python value to convert.
        redshift_type: The target Redshift type.

    Returns:
        SQL literal string representation.

    Raises:
        DataTypeError: If the value cannot be safely rendered as a literal
            of the requested type.
    """
    if _is_null(value):
        return "NULL"

    if redshift_type == RedshiftType.BOOLEAN:
        return "TRUE" if value else "FALSE"

    if redshift_type in (
        RedshiftType.SMALLINT,
        RedshiftType.INTEGER,
        RedshiftType.BIGINT,
    ):
        try:
            return str(int(value))
        except (TypeError, ValueError) as exc:
            raise DataTypeError(
                f"Cannot convert value to an integer literal: {exc}",
                dtype=redshift_type.value,
                value=value,
            ) from exc

    if redshift_type in (
        RedshiftType.REAL,
        RedshiftType.DOUBLE_PRECISION,
        RedshiftType.DECIMAL,
    ):
        try:
            float_val = float(value)
        except (TypeError, ValueError) as exc:
            raise DataTypeError(
                f"Cannot convert value to a numeric literal: {exc}",
                dtype=redshift_type.value,
                value=value,
            ) from exc

        if np.isinf(float_val):
            return "'Infinity'::FLOAT8" if float_val > 0 else "'-Infinity'::FLOAT8"
        if np.isnan(float_val):
            return "NULL"
        # repr() round-trips floats exactly; str() is lossy on some values.
        return repr(float_val)

    if redshift_type in (RedshiftType.TIMESTAMP, RedshiftType.TIMESTAMPTZ):
        if isinstance(value, pd.Timestamp):
            return f"'{value.isoformat()}'"
        return escape_string_literal(str(value))

    if redshift_type == RedshiftType.DATE:
        if isinstance(value, pd.Timestamp):
            return f"'{value.date()}'"
        return escape_string_literal(str(value))

    if redshift_type == RedshiftType.SUPER:
        import json

        try:
            json_str = json.dumps(value, default=str)
        except (TypeError, ValueError) as exc:
            raise DataTypeError(
                f"Cannot serialize value to JSON for a SUPER column: {exc}",
                dtype=redshift_type.value,
                value=value,
            ) from exc
        return f"JSON_PARSE({escape_string_literal(json_str)})"

    if redshift_type == RedshiftType.VARBYTE:
        if isinstance(value, bytes):
            return f"'{value.hex()}'::VARBYTE"
        if isinstance(value, str):
            return f"'{value.encode('utf-8').hex()}'::VARBYTE"
        raise DataTypeError(
            "VARBYTE columns require bytes or str values, got "
            f"{type(value).__name__}",
            dtype=redshift_type.value,
            value=value,
        )

    # String types.
    return escape_string_literal(str(value))
