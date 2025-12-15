"""Tests for distribution analysis and unique key validation."""

import pandas as pd
import pytest

from frameshift.analyzer import (
    DistributionAnalyzer,
    DistributionAnalysis,
    UniqueKeyValidator,
    UniqueKeyValidation,
)
from frameshift.exceptions import ValidationError


class TestDistributionAnalyzer:
    """Tests for DistributionAnalyzer."""

    @pytest.fixture
    def analyzer(self):
        return DistributionAnalyzer(slice_count=8)

    @pytest.fixture
    def sample_df(self):
        return pd.DataFrame({
            "id": range(1000),
            "category": ["A", "B", "C", "D"] * 250,
            "value": [1] * 1000,  # All same value - worst case
        })

    def test_high_cardinality_distribution(self, analyzer, sample_df):
        """High cardinality column should have good distribution."""
        analysis = analyzer.analyze(sample_df, "id")

        assert analysis.unique_values == 1000
        assert analysis.cardinality_ratio == 1.0
        assert analysis.skew_ratio < 2.0  # Should be well distributed
        assert analysis.is_good_distkey()

    def test_low_cardinality_distribution(self, analyzer, sample_df):
        """Low cardinality column should show skew."""
        analysis = analyzer.analyze(sample_df, "category")

        assert analysis.unique_values == 4
        assert analysis.cardinality_ratio < 0.01
        # With only 4 values across 8 slices, some will be empty
        assert not analysis.is_good_distkey()

    def test_single_value_distribution(self, analyzer, sample_df):
        """Single value should show severe skew."""
        analysis = analyzer.analyze(sample_df, "value")

        assert analysis.unique_values == 1
        assert analysis.cardinality_ratio < 0.01
        assert not analysis.is_good_distkey()

    def test_null_handling(self, analyzer):
        """NULLs should be counted and reported."""
        df = pd.DataFrame({
            "col": [1, 2, None, None, 5]
        })
        analysis = analyzer.analyze(df, "col")

        assert analysis.null_count == 2
        assert analysis.row_count == 5

    def test_column_not_found(self, analyzer, sample_df):
        """Should raise error for missing column."""
        with pytest.raises(ValidationError):
            analyzer.analyze(sample_df, "nonexistent")

    def test_compare_columns(self, analyzer, sample_df):
        """Compare multiple columns as DISTKEY candidates."""
        comparison = analyzer.compare_columns(
            sample_df, ["id", "category", "value"]
        )

        assert len(comparison) == 3
        assert "column" in comparison.columns
        assert "skew_ratio" in comparison.columns
        assert "is_good_distkey" in comparison.columns

        # id should be ranked highest (lowest skew)
        assert comparison.iloc[0]["column"] == "id"

    def test_analysis_summary(self, analyzer, sample_df):
        """Summary should be human readable."""
        analysis = analyzer.analyze(sample_df, "id")
        summary = analysis.summary()

        assert "Distribution Analysis" in summary
        assert "id" in summary
        assert "Unique Values" in summary
        assert "Skew Ratio" in summary

    def test_to_dict(self, analyzer, sample_df):
        """to_dict should return serializable data."""
        analysis = analyzer.analyze(sample_df, "id")
        data = analysis.to_dict()

        assert isinstance(data, dict)
        assert "column" in data
        assert "skew_ratio" in data
        assert "is_good_distkey" in data


class TestUniqueKeyValidator:
    """Tests for UniqueKeyValidator."""

    @pytest.fixture
    def validator(self):
        return UniqueKeyValidator()

    def test_unique_single_column(self, validator):
        """Single column with unique values."""
        df = pd.DataFrame({"id": [1, 2, 3, 4, 5]})
        result = validator.validate(df, "id")

        assert result.is_unique
        assert result.duplicate_count == 0
        assert result.unique_combinations == 5

    def test_duplicate_single_column(self, validator):
        """Single column with duplicates."""
        df = pd.DataFrame({"id": [1, 2, 2, 3, 3, 3]})
        result = validator.validate(df, "id")

        assert not result.is_unique
        assert result.duplicate_count == 3  # 2 extra 2s + 2 extra 3s = wait, 6-3=3
        assert result.unique_combinations == 3
        assert result.sample_duplicates is not None

    def test_unique_composite_key(self, validator):
        """Composite key that is unique."""
        df = pd.DataFrame({
            "user_id": [1, 1, 2, 2],
            "date": ["2024-01-01", "2024-01-02", "2024-01-01", "2024-01-02"],
        })
        result = validator.validate(df, ["user_id", "date"])

        assert result.is_unique
        assert result.unique_combinations == 4

    def test_duplicate_composite_key(self, validator):
        """Composite key with duplicates."""
        df = pd.DataFrame({
            "user_id": [1, 1, 1, 2],
            "date": ["2024-01-01", "2024-01-01", "2024-01-02", "2024-01-01"],
        })
        result = validator.validate(df, ["user_id", "date"])

        assert not result.is_unique
        assert result.duplicate_count == 1

    def test_column_not_found(self, validator):
        """Should raise error for missing column."""
        df = pd.DataFrame({"id": [1, 2, 3]})
        with pytest.raises(ValidationError):
            validator.validate(df, "nonexistent")

    def test_find_natural_keys(self, validator):
        """Find potential natural keys."""
        df = pd.DataFrame({
            "id": [1, 2, 3, 4],  # Unique
            "name": ["A", "B", "A", "B"],  # Not unique
            "code": ["X1", "X2", "X3", "X4"],  # Unique
        })
        keys = validator.find_natural_keys(df)

        assert len(keys) >= 1
        # Should find single column keys
        single_col_keys = [k for k, _ in keys if len(k) == 1]
        assert len(single_col_keys) >= 2

    def test_validation_summary(self, validator):
        """Summary should be readable."""
        df = pd.DataFrame({"id": [1, 2, 2, 3]})
        result = validator.validate(df, "id")
        summary = result.summary()

        assert "Unique Key Validation" in summary
        assert "id" in summary
        assert "Duplicate" in summary
