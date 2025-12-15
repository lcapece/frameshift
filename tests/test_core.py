"""Tests for the core FrameShift class."""

import pandas as pd
import pytest
from unittest.mock import MagicMock, patch

from frameshift import FrameShift, FrameShiftConfig, LoadResult
from frameshift.exceptions import ValidationError, InsertError


class TestFrameShiftConfig:
    """Tests for FrameShiftConfig."""

    def test_default_config(self):
        config = FrameShiftConfig()

        assert config.max_statement_bytes > 0
        assert config.batch_size > 0
        assert config.use_transactions is True
        assert config.on_error == "abort"

    def test_config_validation(self):
        # max_statement_bytes too large
        with pytest.raises(ValueError):
            FrameShiftConfig(max_statement_bytes=20 * 1024 * 1024)  # 20 MB

        # max_statement_bytes too small
        with pytest.raises(ValueError):
            FrameShiftConfig(max_statement_bytes=100)

        # Invalid on_error
        with pytest.raises(ValueError):
            FrameShiftConfig(on_error="invalid")

    def test_for_data_api(self):
        config = FrameShiftConfig.for_data_api()

        assert config.max_statement_bytes < 100 * 1024  # Under 100 KB

    def test_for_large_datasets(self):
        config = FrameShiftConfig.for_large_datasets()

        assert config.max_statement_bytes > 10 * 1024 * 1024
        assert config.batch_size > 1000
        assert config.commit_every > 0

    def test_copy_with_overrides(self):
        config = FrameShiftConfig(batch_size=100)
        new_config = config.copy(batch_size=500, dry_run=True)

        assert new_config.batch_size == 500
        assert new_config.dry_run is True
        assert config.batch_size == 100  # Original unchanged


class TestLoadResult:
    """Tests for LoadResult."""

    def test_load_result_repr(self):
        result = LoadResult(
            success=True,
            rows_loaded=1000,
            rows_failed=0,
            chunks_processed=5,
            chunks_failed=0,
            elapsed_seconds=2.5,
            rows_per_second=400.0,
            table_name="public.test",
            created_table=True,
            errors=[],
        )
        repr_str = repr(result)

        assert "SUCCESS" in repr_str
        assert "1,000" in repr_str
        assert "public.test" in repr_str

    def test_load_result_summary(self):
        result = LoadResult(
            success=False,
            rows_loaded=500,
            rows_failed=100,
            chunks_processed=5,
            chunks_failed=1,
            elapsed_seconds=5.0,
            rows_per_second=100.0,
            table_name="test",
            created_table=False,
            errors=["Error 1", "Error 2"],
        )
        summary = result.summary()

        assert "FAILED" in summary
        assert "500" in summary
        assert "Errors:" in summary
        assert "Error 1" in summary


class TestFrameShift:
    """Tests for FrameShift class."""

    @pytest.fixture
    def mock_connection(self):
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None  # Table doesn't exist
        cursor.rowcount = 0
        conn.cursor.return_value = cursor
        return conn

    @pytest.fixture
    def sample_df(self):
        return pd.DataFrame({
            "id": [1, 2, 3],
            "name": ["Alice", "Bob", "Charlie"],
            "value": [1.1, 2.2, 3.3],
        })

    def test_initialization(self, mock_connection):
        fs = FrameShift(connection=mock_connection)
        assert fs is not None
        assert fs.config is not None

    def test_initialization_with_config(self, mock_connection):
        config = FrameShiftConfig(batch_size=500)
        fs = FrameShift(connection=mock_connection, config=config)

        assert fs.config.batch_size == 500

    def test_infer_schema(self, mock_connection, sample_df):
        fs = FrameShift(connection=mock_connection)
        schema = fs.infer_schema(sample_df, "test_table")

        assert schema.table_name == "test_table"
        assert len(schema.columns) == 3

    def test_analyze_distribution(self, mock_connection, sample_df):
        fs = FrameShift(connection=mock_connection)
        analysis = fs.analyze_distribution(sample_df, "id")

        assert analysis.column == "id"
        assert analysis.unique_values == 3

    def test_compare_distkeys(self, mock_connection, sample_df):
        fs = FrameShift(connection=mock_connection)
        comparison = fs.compare_distkeys(sample_df, ["id", "name"])

        assert len(comparison) == 2
        assert "column" in comparison.columns

    def test_validate_unique_key(self, mock_connection, sample_df):
        fs = FrameShift(connection=mock_connection)
        validation = fs.validate_unique_key(sample_df, "id")

        assert validation.is_unique
        assert validation.unique_combinations == 3

    def test_validate_unique_key_duplicates(self, mock_connection):
        fs = FrameShift(connection=mock_connection)
        df = pd.DataFrame({"id": [1, 1, 2]})
        validation = fs.validate_unique_key(df, "id")

        assert not validation.is_unique
        assert validation.duplicate_count == 1

    def test_find_natural_keys(self, mock_connection, sample_df):
        fs = FrameShift(connection=mock_connection)
        keys = fs.find_natural_keys(sample_df)

        assert len(keys) > 0
        # id should be a natural key
        single_keys = [k for k, _ in keys if len(k) == 1]
        assert any("id" in k for k in single_keys)

    def test_estimate_load(self, mock_connection, sample_df):
        fs = FrameShift(connection=mock_connection)
        estimates = fs.estimate_load(sample_df)

        assert "total_rows" in estimates
        assert "estimated_chunks" in estimates
        assert estimates["total_rows"] == 3

    def test_get_recommendations(self, mock_connection, sample_df):
        fs = FrameShift(connection=mock_connection)
        recs = fs.get_recommendations(sample_df, "test")

        assert "distkey" in recs
        assert "sortkey" in recs
        assert "sql" in recs

    def test_generate_sql_dry_run(self, mock_connection, sample_df):
        fs = FrameShift(connection=mock_connection)
        statements = fs.generate_sql(sample_df, "test_table")

        assert len(statements) > 0
        # Should have CREATE TABLE and INSERT
        assert any("CREATE" in s for s in statements)
        assert any("INSERT" in s for s in statements)

    def test_context_manager(self, mock_connection):
        with FrameShift(connection=mock_connection) as fs:
            assert fs is not None

    @patch("frameshift.core.create_connection_manager")
    def test_load_dry_run(self, mock_create_conn, mock_connection, sample_df):
        mock_create_conn.return_value = MagicMock()
        mock_create_conn.return_value.connection.return_value.__enter__ = MagicMock(
            return_value=mock_connection
        )
        mock_create_conn.return_value.connection.return_value.__exit__ = MagicMock()

        config = FrameShiftConfig(dry_run=True)
        fs = FrameShift(connection=mock_connection, config=config)
        result = fs.load(sample_df, "test_table")

        assert result.sql_statements is not None
        assert len(result.sql_statements) > 0


class TestFrameShiftIntegration:
    """Integration-style tests (mocked database)."""

    @pytest.fixture
    def mock_cursor(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.rowcount = 0
        return cursor

    @pytest.fixture
    def mock_connection(self, mock_cursor):
        conn = MagicMock()
        conn.cursor.return_value = mock_cursor
        return conn

    def test_full_load_flow(self, mock_connection, mock_cursor):
        df = pd.DataFrame({
            "user_id": range(100),
            "email": [f"user{i}@test.com" for i in range(100)],
            "created_at": pd.date_range("2024-01-01", periods=100),
        })

        fs = FrameShift(connection=mock_connection)

        # Dry run first
        result = fs.load(
            df,
            "users",
            distkey="user_id",
            sortkey="created_at",
        )

        # Verify cursor.execute was called
        assert mock_cursor.execute.called

    def test_load_with_validation(self, mock_connection):
        df = pd.DataFrame({
            "id": [1, 2, 2, 3],  # Duplicate
            "name": ["a", "b", "c", "d"],
        })

        fs = FrameShift(connection=mock_connection)

        # Should fail validation
        with pytest.raises(ValidationError):
            fs.load(
                df,
                "test",
                unique_key="id",
                validate_unique=True,
            )
