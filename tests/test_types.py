"""Tests for type inference and conversion."""

import numpy as np
import pandas as pd
import pytest

from frameshift.types import (
    RedshiftType,
    ColumnSpec,
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
        assert "ENCODE zstd" in sql


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

    def test_integer_values(self):
        assert python_to_sql_value(42, RedshiftType.INTEGER) == "42"
        assert python_to_sql_value(42.9, RedshiftType.INTEGER) == "42"

    def test_float_values(self):
        assert python_to_sql_value(3.14, RedshiftType.DOUBLE_PRECISION) == "3.14"
        assert python_to_sql_value(float("inf"), RedshiftType.DOUBLE_PRECISION) == "'Infinity'"
        assert python_to_sql_value(float("-inf"), RedshiftType.DOUBLE_PRECISION) == "'-Infinity'"

    def test_string_escaping(self):
        # Single quotes
        result = python_to_sql_value("it's", RedshiftType.VARCHAR)
        assert result == "'it''s'"

        # Backslashes
        result = python_to_sql_value("path\\to\\file", RedshiftType.VARCHAR)
        assert "\\\\" in result

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
