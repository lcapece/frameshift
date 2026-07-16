"""Tests for type inference and conversion."""

import numpy as np
import pandas as pd
import pytest

from frameshift.exceptions import DataTypeError, ValidationError
from frameshift.types import (
    ColumnSpec,
    RedshiftType,
    infer_redshift_type,
    python_to_sql_value,
)


class TestColumnSpec:
    """Tests for ColumnSpec."""

    def test_basic_varchar(self):
        spec = ColumnSpec(
            name="test_col",
            redshift_type=RedshiftType.VARCHAR,
            length=256,
        )
        sql = spec.to_sql()
        assert '"test_col"' in sql
        assert "VARCHAR(256)" in sql

    def test_decimal_with_precision(self):
        spec = ColumnSpec(
            name="amount",
            redshift_type=RedshiftType.DECIMAL,
            precision=18,
            scale=2,
        )
        sql = spec.to_sql()
        assert "DECIMAL(18,2)" in sql

    def test_not_null(self):
        spec = ColumnSpec(
            name="id",
            redshift_type=RedshiftType.INTEGER,
            nullable=False,
        )
        sql = spec.to_sql()
        assert "NOT NULL" in sql

    def test_with_encoding(self):
        spec = ColumnSpec(
            name="data",
            redshift_type=RedshiftType.VARCHAR,
            length=1000,
            encode="zstd",
        )
        sql = spec.to_sql()
        # Encodings are normalized to upper case and validated against
        # Redshift's documented set.
        assert "ENCODE ZSTD" in sql

    def test_unknown_encoding_rejected(self):
        spec = ColumnSpec(
            name="data",
            redshift_type=RedshiftType.VARCHAR,
            length=1000,
            encode="raw; DROP TABLE users",
        )
        with pytest.raises(ValidationError):
            spec.to_sql()


class TestInferRedshiftType:
    """Tests for type inference."""

    def test_integer_types(self):
        # int64
        series = pd.Series([1, 2, 3], dtype="int64")
        spec = infer_redshift_type(series)
        assert spec.redshift_type == RedshiftType.BIGINT

        # int32
        series = pd.Series([1, 2, 3], dtype="int32")
        spec = infer_redshift_type(series)
        assert spec.redshift_type == RedshiftType.INTEGER

    def test_float_types(self):
        series = pd.Series([1.1, 2.2, 3.3], dtype="float64")
        spec = infer_redshift_type(series)
        assert spec.redshift_type == RedshiftType.DOUBLE_PRECISION

    def test_string_type(self):
        series = pd.Series(["hello", "world", "test"])
        spec = infer_redshift_type(series)
        assert spec.redshift_type == RedshiftType.VARCHAR
        assert spec.length is not None

    def test_boolean_type(self):
        series = pd.Series([True, False, True])
        spec = infer_redshift_type(series)
        assert spec.redshift_type == RedshiftType.BOOLEAN

    def test_object_column_of_bools_is_boolean(self):
        series = pd.Series([True, False, True], dtype="object")
        assert infer_redshift_type(series).redshift_type == RedshiftType.BOOLEAN

    def test_string_booleans_are_boolean(self):
        series = pd.Series(["true", "false", "true"], dtype="object")
        assert infer_redshift_type(series).redshift_type == RedshiftType.BOOLEAN

    def test_integer_flags_are_not_inferred_as_boolean(self):
        """
        A column of 1/0 integers is usually a count, id, or enum -- not a
        boolean. Inferring BOOLEAN would coerce the data irreversibly, so
        only genuine bools and boolean strings qualify.
        """
        series = pd.Series([1, 0, 1, 0], dtype="object")
        assert infer_redshift_type(series).redshift_type != RedshiftType.BOOLEAN

        typed = pd.Series([1, 0, 1, 0], dtype="int64")
        assert infer_redshift_type(typed).redshift_type == RedshiftType.BIGINT

    def test_datetime_type(self):
        series = pd.Series(pd.date_range("2024-01-01", periods=3))
        spec = infer_redshift_type(series)
        assert spec.redshift_type == RedshiftType.TIMESTAMP

    def test_nullable_detection(self):
        series = pd.Series([1, None, 3])
        spec = infer_redshift_type(series)
        assert spec.nullable is True

        series = pd.Series([1, 2, 3])
        spec = infer_redshift_type(series)
        assert spec.nullable is False

    def test_varchar_length_calculation(self):
        # Short strings
        series = pd.Series(["a", "bb", "ccc"])
        spec = infer_redshift_type(series)
        assert spec.length <= 16

        # Longer strings
        series = pd.Series(["a" * 100, "b" * 200])
        spec = infer_redshift_type(series)
        assert spec.length >= 200


class TestPythonToSqlValue:
    """Tests for value conversion."""

    def test_null_values(self):
        assert python_to_sql_value(None, RedshiftType.VARCHAR) == "NULL"
        assert python_to_sql_value(np.nan, RedshiftType.DOUBLE_PRECISION) == "NULL"
        assert python_to_sql_value(pd.NA, RedshiftType.INTEGER) == "NULL"

    def test_boolean_values(self):
        assert python_to_sql_value(True, RedshiftType.BOOLEAN) == "TRUE"
        assert python_to_sql_value(False, RedshiftType.BOOLEAN) == "FALSE"

    def test_string_booleans_are_interpreted_not_truthy(self):
        """
        Every non-empty string is truthy, so testing `if value` would render
        "false" as TRUE and silently invert the column.
        """
        assert python_to_sql_value("false", RedshiftType.BOOLEAN) == "FALSE"
        assert python_to_sql_value("False", RedshiftType.BOOLEAN) == "FALSE"
        assert python_to_sql_value("f", RedshiftType.BOOLEAN) == "FALSE"
        assert python_to_sql_value("no", RedshiftType.BOOLEAN) == "FALSE"
        assert python_to_sql_value("0", RedshiftType.BOOLEAN) == "FALSE"
        assert python_to_sql_value("true", RedshiftType.BOOLEAN) == "TRUE"
        assert python_to_sql_value("yes", RedshiftType.BOOLEAN) == "TRUE"

    def test_uninterpretable_boolean_raises(self):
        with pytest.raises(DataTypeError):
            python_to_sql_value("maybe", RedshiftType.BOOLEAN)

    def test_integer_values(self):
        assert python_to_sql_value(42, RedshiftType.INTEGER) == "42"
        assert python_to_sql_value(42.9, RedshiftType.INTEGER) == "42"

    def test_float_values(self):
        assert python_to_sql_value(3.14, RedshiftType.DOUBLE_PRECISION) == "3.14"
        # Infinity carries an explicit cast so Redshift does not have to
        # infer the type of a bare quoted literal.
        assert (
            python_to_sql_value(float("inf"), RedshiftType.DOUBLE_PRECISION)
            == "'Infinity'::FLOAT8"
        )
        assert (
            python_to_sql_value(float("-inf"), RedshiftType.DOUBLE_PRECISION)
            == "'-Infinity'::FLOAT8"
        )

    def test_nan_becomes_null(self):
        assert (
            python_to_sql_value(float("nan"), RedshiftType.DOUBLE_PRECISION) == "NULL"
        )

    def test_string_escaping(self):
        # Escaping matches Redshift's QUOTE_LITERAL: both single quotes and
        # backslashes are doubled inside a plain literal. See
        # tests/test_injection.py for the security properties.
        assert python_to_sql_value("it's", RedshiftType.VARCHAR) == "'it''s'"
        assert (
            python_to_sql_value("path\\to\\file", RedshiftType.VARCHAR)
            == "'path\\\\to\\\\file'"
        )
        assert python_to_sql_value("plain", RedshiftType.VARCHAR) == "'plain'"

    def test_timestamp_values(self):
        ts = pd.Timestamp("2024-01-15 10:30:00")
        result = python_to_sql_value(ts, RedshiftType.TIMESTAMP)
        assert "2024-01-15" in result
        assert result.startswith("'")
        assert result.endswith("'")

    def test_date_values(self):
        ts = pd.Timestamp("2024-01-15")
        result = python_to_sql_value(ts, RedshiftType.DATE)
        assert "2024-01-15" in result
