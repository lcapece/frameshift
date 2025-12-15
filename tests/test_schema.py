"""Tests for schema inference and table creation."""

import pandas as pd
import pytest

from frameshift.schema import SchemaInferer, TableSchema
from frameshift.types import RedshiftType, ColumnSpec
from frameshift.exceptions import ValidationError


class TestTableSchema:
    """Tests for TableSchema."""

    def test_basic_create_table(self):
        schema = TableSchema(
            table_name="test_table",
            schema_name="public",
            columns=[
                ColumnSpec("id", RedshiftType.INTEGER, nullable=False),
                ColumnSpec("name", RedshiftType.VARCHAR, length=256),
            ],
        )
        sql = schema.to_create_table_sql()

        assert "CREATE TABLE" in sql
        assert '"public"."test_table"' in sql
        assert '"id"' in sql
        assert '"name"' in sql
        assert "INTEGER" in sql
        assert "VARCHAR(256)" in sql

    def test_create_with_distkey(self):
        schema = TableSchema(
            table_name="test_table",
            columns=[
                ColumnSpec("id", RedshiftType.INTEGER),
            ],
            distkey="id",
        )
        sql = schema.to_create_table_sql()

        assert "DISTSTYLE KEY" in sql
        assert 'DISTKEY ("id")' in sql

    def test_create_with_sortkey(self):
        schema = TableSchema(
            table_name="test_table",
            columns=[
                ColumnSpec("created_at", RedshiftType.TIMESTAMP),
            ],
            sortkey=["created_at"],
        )
        sql = schema.to_create_table_sql()

        assert 'SORTKEY ("created_at")' in sql

    def test_create_with_compound_sortkey(self):
        schema = TableSchema(
            table_name="test_table",
            columns=[
                ColumnSpec("status", RedshiftType.VARCHAR, length=32),
                ColumnSpec("created_at", RedshiftType.TIMESTAMP),
            ],
            sortkey=["status", "created_at"],
            sortkey_type="COMPOUND",
        )
        sql = schema.to_create_table_sql()

        assert 'SORTKEY ("status", "created_at")' in sql

    def test_create_with_interleaved_sortkey(self):
        schema = TableSchema(
            table_name="test_table",
            columns=[
                ColumnSpec("a", RedshiftType.INTEGER),
                ColumnSpec("b", RedshiftType.INTEGER),
            ],
            sortkey=["a", "b"],
            sortkey_type="INTERLEAVED",
        )
        sql = schema.to_create_table_sql()

        assert "INTERLEAVED SORTKEY" in sql

    def test_create_with_primary_key(self):
        schema = TableSchema(
            table_name="test_table",
            columns=[
                ColumnSpec("id", RedshiftType.INTEGER, nullable=False),
            ],
            primary_key=["id"],
        )
        sql = schema.to_create_table_sql()

        assert 'PRIMARY KEY ("id")' in sql

    def test_create_with_unique_constraint(self):
        schema = TableSchema(
            table_name="test_table",
            columns=[
                ColumnSpec("email", RedshiftType.VARCHAR, length=256),
            ],
            unique_keys=[["email"]],
        )
        sql = schema.to_create_table_sql()

        assert 'UNIQUE ("email")' in sql

    def test_if_not_exists(self):
        schema = TableSchema(
            table_name="test_table",
            columns=[ColumnSpec("id", RedshiftType.INTEGER)],
            if_not_exists=True,
        )
        sql = schema.to_create_table_sql()

        assert "IF NOT EXISTS" in sql

    def test_temporary_table(self):
        schema = TableSchema(
            table_name="temp_table",
            columns=[ColumnSpec("id", RedshiftType.INTEGER)],
            temporary=True,
        )
        sql = schema.to_create_table_sql()

        assert "TEMPORARY TABLE" in sql

    def test_invalid_diststyle(self):
        with pytest.raises(ValidationError):
            TableSchema(
                table_name="test",
                columns=[],
                diststyle="INVALID",
            )

    def test_invalid_sortkey_type(self):
        with pytest.raises(ValidationError):
            TableSchema(
                table_name="test",
                columns=[],
                sortkey_type="INVALID",
            )

    def test_insert_sql_prefix(self):
        schema = TableSchema(
            table_name="test_table",
            schema_name="myschema",
            columns=[
                ColumnSpec("id", RedshiftType.INTEGER),
                ColumnSpec("name", RedshiftType.VARCHAR, length=100),
            ],
        )
        sql = schema.to_insert_sql()

        assert 'INSERT INTO "myschema"."test_table"' in sql
        assert '"id", "name"' in sql
        assert "VALUES" in sql


class TestSchemaInferer:
    """Tests for SchemaInferer."""

    @pytest.fixture
    def inferer(self):
        return SchemaInferer()

    @pytest.fixture
    def sample_df(self):
        return pd.DataFrame({
            "user_id": [1, 2, 3, 4, 5],
            "email": ["a@test.com", "b@test.com", "c@test.com", "d@test.com", "e@test.com"],
            "created_at": pd.date_range("2024-01-01", periods=5),
            "score": [1.1, 2.2, 3.3, 4.4, 5.5],
            "active": [True, False, True, True, False],
        })

    def test_basic_inference(self, inferer, sample_df):
        schema = inferer.infer_schema(sample_df, "users")

        assert schema.table_name == "users"
        assert len(schema.columns) == 5

        # Check type inference
        col_types = {c.name: c.redshift_type for c in schema.columns}
        assert col_types["user_id"] == RedshiftType.BIGINT
        assert col_types["email"] == RedshiftType.VARCHAR
        assert col_types["created_at"] == RedshiftType.TIMESTAMP
        assert col_types["score"] == RedshiftType.DOUBLE_PRECISION
        assert col_types["active"] == RedshiftType.BOOLEAN

    def test_explicit_distkey(self, inferer, sample_df):
        schema = inferer.infer_schema(
            sample_df, "users", distkey="user_id"
        )

        assert schema.distkey == "user_id"

        # Column should be marked as distkey
        user_id_col = next(c for c in schema.columns if c.name == "user_id")
        assert user_id_col.is_distkey

    def test_explicit_sortkey(self, inferer, sample_df):
        schema = inferer.infer_schema(
            sample_df, "users", sortkey=["created_at"]
        )

        assert schema.sortkey == ["created_at"]

        created_at_col = next(c for c in schema.columns if c.name == "created_at")
        assert created_at_col.is_sortkey
        assert created_at_col.sortkey_position == 1

    def test_auto_suggest_keys(self, inferer, sample_df):
        schema = inferer.infer_schema(
            sample_df, "users", auto_suggest_keys=True
        )

        # Should suggest user_id as distkey (high cardinality, id pattern)
        assert schema.distkey == "user_id"

        # Should suggest created_at as sortkey (timestamp)
        assert "created_at" in schema.sortkey

    def test_primary_key(self, inferer, sample_df):
        schema = inferer.infer_schema(
            sample_df, "users", primary_key="user_id"
        )

        assert schema.primary_key == ["user_id"]

        user_id_col = next(c for c in schema.columns if c.name == "user_id")
        assert user_id_col.is_unique
        assert user_id_col.nullable is False

    def test_generate_recommendations(self, inferer, sample_df):
        recs = inferer.generate_recommendations(sample_df, "users")

        assert "table_name" in recs
        assert "row_count" in recs
        assert "columns" in recs
        assert "distkey" in recs
        assert "sortkey" in recs
        assert "sql" in recs

        assert recs["row_count"] == 5
        assert len(recs["columns"]) == 5

    def test_preserve_index(self, inferer):
        df = pd.DataFrame(
            {"value": [1, 2, 3]},
            index=pd.Index([10, 20, 30], name="my_index")
        )
        schema = inferer.infer_schema(
            df, "test", preserve_index=True
        )

        col_names = [c.name for c in schema.columns]
        assert "my_index" in col_names
        assert "value" in col_names
