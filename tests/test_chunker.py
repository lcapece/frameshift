"""Tests for DataFrame chunking and SQL generation."""

import pandas as pd
import pytest

from frameshift.chunker import DataFrameChunker, SQLGenerator, Chunk
from frameshift.types import RedshiftType, ColumnSpec
from frameshift.exceptions import ChunkingError


class TestDataFrameChunker:
    """Tests for DataFrameChunker."""

    @pytest.fixture
    def chunker(self):
        return DataFrameChunker(
            max_bytes=10000,  # 10 KB for testing
            initial_batch_size=100,
        )

    @pytest.fixture
    def column_specs(self):
        return [
            ColumnSpec("id", RedshiftType.INTEGER),
            ColumnSpec("name", RedshiftType.VARCHAR, length=100),
            ColumnSpec("value", RedshiftType.DOUBLE_PRECISION),
        ]

    @pytest.fixture
    def sample_df(self):
        return pd.DataFrame({
            "id": range(500),
            "name": ["test_name"] * 500,
            "value": [1.23456] * 500,
        })

    def test_basic_chunking(self, chunker, sample_df, column_specs):
        chunks = list(chunker.chunk(sample_df, column_specs))

        assert len(chunks) > 0
        assert all(isinstance(c, Chunk) for c in chunks)

        # Verify all rows are covered
        total_rows = sum(c.row_count for c in chunks)
        assert total_rows == len(sample_df)

    def test_chunk_attributes(self, chunker, sample_df, column_specs):
        chunks = list(chunker.chunk(sample_df, column_specs))
        chunk = chunks[0]

        assert chunk.chunk_index == 0
        assert chunk.start_row == 0
        assert chunk.row_count == len(chunk.data)
        assert chunk.estimated_size > 0
        assert chunk.estimated_size <= chunker.max_bytes

    def test_empty_dataframe(self, chunker, column_specs):
        df = pd.DataFrame(columns=["id", "name", "value"])
        chunks = list(chunker.chunk(df, column_specs))

        assert len(chunks) == 0

    def test_single_row(self, chunker, column_specs):
        df = pd.DataFrame({
            "id": [1],
            "name": ["test"],
            "value": [1.0],
        })
        chunks = list(chunker.chunk(df, column_specs))

        assert len(chunks) == 1
        assert chunks[0].row_count == 1

    def test_chunk_size_respects_limit(self, chunker, column_specs):
        # Create larger dataset
        df = pd.DataFrame({
            "id": range(1000),
            "name": ["x" * 50] * 1000,  # Larger strings
            "value": [1.23456789] * 1000,
        })
        chunks = list(chunker.chunk(df, column_specs))

        for chunk in chunks:
            assert chunk.estimated_size <= chunker.max_bytes

    def test_estimate_chunks(self, chunker, sample_df, column_specs):
        estimates = chunker.estimate_chunks(sample_df, column_specs)

        assert "total_rows" in estimates
        assert "estimated_chunks" in estimates
        assert "avg_row_size_bytes" in estimates
        assert estimates["total_rows"] == 500
        assert estimates["estimated_chunks"] > 0

    def test_oversized_single_row(self):
        # Create chunker with tiny limit
        chunker = DataFrameChunker(max_bytes=50)
        column_specs = [
            ColumnSpec("data", RedshiftType.VARCHAR, length=1000),
        ]
        df = pd.DataFrame({
            "data": ["x" * 100],  # Row larger than limit
        })

        with pytest.raises(ChunkingError):
            list(chunker.chunk(df, column_specs))


class TestSQLGenerator:
    """Tests for SQLGenerator."""

    @pytest.fixture
    def column_specs(self):
        return [
            ColumnSpec("id", RedshiftType.INTEGER),
            ColumnSpec("name", RedshiftType.VARCHAR, length=100),
            ColumnSpec("active", RedshiftType.BOOLEAN),
        ]

    @pytest.fixture
    def generator(self, column_specs):
        return SQLGenerator(
            table_name="test_table",
            schema_name="public",
            column_specs=column_specs,
        )

    def test_insert_prefix_with_columns(self, generator):
        prefix = generator.generate_insert_prefix(include_columns=True)

        assert 'INSERT INTO "public"."test_table"' in prefix
        assert '"id"' in prefix
        assert '"name"' in prefix
        assert '"active"' in prefix
        assert "VALUES" in prefix

    def test_insert_prefix_without_columns(self, generator):
        prefix = generator.generate_insert_prefix(include_columns=False)

        assert 'INSERT INTO "public"."test_table"' in prefix
        assert '"id"' not in prefix
        assert "VALUES" in prefix

    def test_generate_insert_statement(self, generator):
        df = pd.DataFrame({
            "id": [1, 2],
            "name": ["Alice", "Bob"],
            "active": [True, False],
        })
        sql = generator.generate_insert_statement(df)

        assert "INSERT INTO" in sql
        assert "VALUES" in sql
        assert "(1, 'Alice', TRUE)" in sql
        assert "(2, 'Bob', FALSE)" in sql
        assert sql.endswith(";")

    def test_generate_insert_empty_df(self, generator):
        df = pd.DataFrame(columns=["id", "name", "active"])
        sql = generator.generate_insert_statement(df)

        assert sql == ""

    def test_generate_values_only(self, generator):
        df = pd.DataFrame({
            "id": [1],
            "name": ["Test"],
            "active": [True],
        })
        values = generator.generate_values_only(df)

        assert "INSERT" not in values
        assert "(1, 'Test', TRUE)" in values

    def test_special_character_escaping(self, generator):
        df = pd.DataFrame({
            "id": [1],
            "name": ["O'Brien"],
            "active": [True],
        })
        sql = generator.generate_insert_statement(df)

        assert "O''Brien" in sql  # Escaped quote

    def test_null_values(self, generator):
        df = pd.DataFrame({
            "id": [1],
            "name": [None],
            "active": [True],
        })
        sql = generator.generate_insert_statement(df)

        assert "NULL" in sql

    def test_full_table_name_no_schema(self, column_specs):
        gen = SQLGenerator(
            table_name="test",
            schema_name=None,
            column_specs=column_specs,
        )
        assert gen.full_table_name == '"test"'

    def test_full_table_name_with_schema(self, generator):
        assert generator.full_table_name == '"public"."test_table"'
