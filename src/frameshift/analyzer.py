"""
Data distribution analysis for Frameshift.

This module provides tools for analyzing data distribution characteristics
to help optimize Redshift table design, particularly for DISTKEY selection.
"""

import hashlib
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from frameshift.exceptions import ValidationError


# Redshift uses 2-byte slot IDs, distributing across slices
# Common slice counts based on node types
COMMON_SLICE_COUNTS = [2, 4, 8, 16, 32, 64, 128, 256]
DEFAULT_SLICE_COUNT = 16  # Reasonable default for analysis


@dataclass
class DistributionAnalysis:
    """
    Results of distribution skew analysis.

    Attributes:
        column: Name of the analyzed column.
        slice_count: Number of slices used in simulation.
        row_count: Total number of rows.
        unique_values: Number of unique values.
        cardinality_ratio: Ratio of unique values to total rows.
        min_rows_per_slice: Minimum rows in any slice.
        max_rows_per_slice: Maximum rows in any slice.
        avg_rows_per_slice: Average rows per slice.
        std_rows_per_slice: Standard deviation of rows per slice.
        skew_ratio: Ratio of max to average (1.0 = perfect distribution).
        coefficient_of_variation: CV of slice distribution.
        recommendation: Text recommendation based on analysis.
        slice_distribution: Dict mapping slice ID to row count.
        top_values: Most frequent values and their counts.
        null_count: Number of NULL values.
    """

    column: str
    slice_count: int
    row_count: int
    unique_values: int
    cardinality_ratio: float
    min_rows_per_slice: int
    max_rows_per_slice: int
    avg_rows_per_slice: float
    std_rows_per_slice: float
    skew_ratio: float
    coefficient_of_variation: float
    recommendation: str
    slice_distribution: dict[int, int]
    top_values: list[tuple[Any, int]]
    null_count: int

    def is_good_distkey(self) -> bool:
        """
        Determine if column would make a good distribution key.

        Returns:
            True if distribution characteristics are favorable.
        """
        # Good DISTKEY criteria:
        # - Skew ratio < 2.0 (no slice has 2x average)
        # - Cardinality ratio > 0.01 (at least 1% unique)
        # - Low null ratio
        null_ratio = self.null_count / self.row_count if self.row_count > 0 else 0
        return (
            self.skew_ratio < 2.0
            and self.cardinality_ratio > 0.01
            and null_ratio < 0.1
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert analysis to dictionary."""
        return {
            "column": self.column,
            "slice_count": self.slice_count,
            "row_count": self.row_count,
            "unique_values": self.unique_values,
            "cardinality_ratio": round(self.cardinality_ratio, 4),
            "min_rows_per_slice": self.min_rows_per_slice,
            "max_rows_per_slice": self.max_rows_per_slice,
            "avg_rows_per_slice": round(self.avg_rows_per_slice, 2),
            "std_rows_per_slice": round(self.std_rows_per_slice, 2),
            "skew_ratio": round(self.skew_ratio, 2),
            "coefficient_of_variation": round(self.coefficient_of_variation, 4),
            "is_good_distkey": self.is_good_distkey(),
            "recommendation": self.recommendation,
            "null_count": self.null_count,
            "top_values": self.top_values[:10],
        }

    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            f"Distribution Analysis for '{self.column}'",
            "=" * 50,
            f"Total Rows:      {self.row_count:,}",
            f"Unique Values:   {self.unique_values:,} ({self.cardinality_ratio:.1%} cardinality)",
            f"NULL Count:      {self.null_count:,}",
            "",
            f"Simulated Slices: {self.slice_count}",
            f"Min/Max/Avg:     {self.min_rows_per_slice:,} / {self.max_rows_per_slice:,} / {self.avg_rows_per_slice:,.0f}",
            f"Skew Ratio:      {self.skew_ratio:.2f}x (1.0 = perfect)",
            f"CV:              {self.coefficient_of_variation:.2%}",
            "",
            f"Good DISTKEY:    {'Yes' if self.is_good_distkey() else 'No'}",
            "",
            "Recommendation:",
            self.recommendation,
        ]

        if self.top_values:
            lines.extend(["", "Top Values:"])
            for val, count in self.top_values[:5]:
                pct = count / self.row_count * 100 if self.row_count > 0 else 0
                lines.append(f"  {val!r}: {count:,} ({pct:.1f}%)")

        return "\n".join(lines)


class DistributionAnalyzer:
    """
    Analyze data distribution for optimal Redshift DISTKEY selection.

    This class simulates how Redshift would distribute data across
    slices based on a hash of the distribution key column, allowing
    you to predict and prevent data skew before loading.

    Redshift uses an internal hash function to distribute rows across
    slices. This analyzer simulates that distribution using MD5 hashing,
    which provides a similar uniform distribution characteristic.

    Example:
        >>> analyzer = DistributionAnalyzer(slice_count=16)
        >>> analysis = analyzer.analyze(df, 'user_id')
        >>> print(analysis.summary())
        >>> if analysis.is_good_distkey():
        ...     print("user_id is a good distribution key!")
    """

    def __init__(self, slice_count: int = DEFAULT_SLICE_COUNT) -> None:
        """
        Initialize the distribution analyzer.

        Args:
            slice_count: Number of slices to simulate. Use a value
                matching your Redshift cluster configuration for
                most accurate results.
        """
        if slice_count < 1:
            raise ValidationError(
                "slice_count must be at least 1",
                field="slice_count",
                received=str(slice_count),
            )
        self.slice_count = slice_count

    def analyze(
        self,
        df: pd.DataFrame,
        column: str,
        top_n: int = 10,
    ) -> DistributionAnalysis:
        """
        Analyze distribution of a column as potential DISTKEY.

        Uses MD5 hashing to simulate Redshift's distribution algorithm.
        MD5 is used because it provides uniform distribution similar to
        Redshift's internal hash function.

        Args:
            df: DataFrame to analyze.
            column: Column name to analyze.
            top_n: Number of top values to include.

        Returns:
            DistributionAnalysis with detailed metrics.
        """
        if column not in df.columns:
            raise ValidationError(
                f"Column '{column}' not found in DataFrame",
                field="column",
                received=column,
            )

        series = df[column]
        row_count = len(series)
        null_count = int(series.isna().sum())
        non_null = series.dropna()

        # Calculate basic statistics
        unique_values = int(non_null.nunique())
        cardinality_ratio = unique_values / row_count if row_count > 0 else 0

        # Get top values
        value_counts = non_null.value_counts().head(top_n)
        top_values = [(val, int(count)) for val, count in value_counts.items()]

        # Simulate hash distribution across slices
        slice_distribution = self._compute_slice_distribution(non_null)

        # Handle case where all values are NULL
        if not slice_distribution:
            slice_distribution = {i: 0 for i in range(self.slice_count)}
            # All NULLs go to slice 0 in Redshift
            slice_distribution[0] = null_count

        # Calculate distribution statistics
        counts = list(slice_distribution.values())
        min_rows = min(counts) if counts else 0
        max_rows = max(counts) if counts else 0
        avg_rows = np.mean(counts) if counts else 0
        std_rows = np.std(counts) if counts else 0

        # Skew ratio: how much bigger is max vs average?
        skew_ratio = max_rows / avg_rows if avg_rows > 0 else float("inf")

        # Coefficient of variation
        cv = std_rows / avg_rows if avg_rows > 0 else float("inf")

        # Generate recommendation
        recommendation = self._generate_recommendation(
            column=column,
            cardinality_ratio=cardinality_ratio,
            skew_ratio=skew_ratio,
            null_ratio=null_count / row_count if row_count > 0 else 0,
            unique_values=unique_values,
        )

        return DistributionAnalysis(
            column=column,
            slice_count=self.slice_count,
            row_count=row_count,
            unique_values=unique_values,
            cardinality_ratio=cardinality_ratio,
            min_rows_per_slice=min_rows,
            max_rows_per_slice=max_rows,
            avg_rows_per_slice=float(avg_rows),
            std_rows_per_slice=float(std_rows),
            skew_ratio=float(skew_ratio),
            coefficient_of_variation=float(cv),
            recommendation=recommendation,
            slice_distribution=slice_distribution,
            top_values=top_values,
            null_count=null_count,
        )

    def _compute_slice_distribution(
        self, series: pd.Series
    ) -> dict[int, int]:
        """
        Compute distribution of values across slices using MD5 hash.

        Redshift uses an internal hash function for distribution.
        MD5 provides similar uniform distribution characteristics.
        """
        slice_counts: dict[int, int] = {i: 0 for i in range(self.slice_count)}

        # Hash each value and assign to slice
        for value in series:
            slice_id = self._hash_to_slice(value)
            slice_counts[slice_id] += 1

        return slice_counts

    def _hash_to_slice(self, value: Any) -> int:
        """
        Hash a value to a slice ID using MD5.

        Args:
            value: Value to hash.

        Returns:
            Slice ID (0 to slice_count-1).
        """
        # Convert to string and encode
        str_val = str(value).encode("utf-8")

        # MD5 hash
        hash_bytes = hashlib.md5(str_val).digest()

        # Use first 8 bytes as integer
        hash_int = int.from_bytes(hash_bytes[:8], byteorder="big")

        # Map to slice
        return hash_int % self.slice_count

    def _generate_recommendation(
        self,
        column: str,
        cardinality_ratio: float,
        skew_ratio: float,
        null_ratio: float,
        unique_values: int,
    ) -> str:
        """Generate actionable recommendation based on analysis."""
        issues = []
        strengths = []

        # Check cardinality
        if cardinality_ratio < 0.001:
            issues.append(
                f"Very low cardinality ({cardinality_ratio:.2%}). "
                "This column has too few unique values for good distribution."
            )
        elif cardinality_ratio < 0.01:
            issues.append(
                f"Low cardinality ({cardinality_ratio:.2%}). "
                "Consider a different column with more unique values."
            )
        else:
            strengths.append(f"Good cardinality ({cardinality_ratio:.1%}).")

        # Check skew
        if skew_ratio > 5.0:
            issues.append(
                f"Severe skew detected (ratio: {skew_ratio:.1f}x). "
                "Some slices will have much more data than others."
            )
        elif skew_ratio > 2.0:
            issues.append(
                f"Moderate skew detected (ratio: {skew_ratio:.1f}x). "
                "Distribution is somewhat uneven."
            )
        else:
            strengths.append(f"Good distribution (skew ratio: {skew_ratio:.2f}x).")

        # Check nulls
        if null_ratio > 0.5:
            issues.append(
                f"High NULL ratio ({null_ratio:.1%}). "
                "NULLs all hash to the same slice, causing skew."
            )
        elif null_ratio > 0.1:
            issues.append(
                f"Moderate NULL ratio ({null_ratio:.1%}). "
                "Consider handling NULLs before loading."
            )

        # Generate final recommendation
        if not issues:
            return (
                f"'{column}' is a GOOD candidate for DISTKEY. "
                + " ".join(strengths)
            )
        elif len(issues) == 1 and strengths:
            return (
                f"'{column}' is an ACCEPTABLE candidate for DISTKEY with caveats. "
                + issues[0]
            )
        else:
            return (
                f"'{column}' is NOT recommended as DISTKEY. "
                + " ".join(issues)
            )

    def compare_columns(
        self,
        df: pd.DataFrame,
        columns: list[str],
    ) -> pd.DataFrame:
        """
        Compare multiple columns as DISTKEY candidates.

        Args:
            df: DataFrame to analyze.
            columns: List of column names to compare.

        Returns:
            DataFrame with comparison metrics for each column.
        """
        results = []

        for col in columns:
            try:
                analysis = self.analyze(df, col)
                results.append({
                    "column": col,
                    "unique_values": analysis.unique_values,
                    "cardinality_ratio": analysis.cardinality_ratio,
                    "skew_ratio": analysis.skew_ratio,
                    "cv": analysis.coefficient_of_variation,
                    "null_count": analysis.null_count,
                    "is_good_distkey": analysis.is_good_distkey(),
                    "recommendation": "Good" if analysis.is_good_distkey() else "Not Recommended",
                })
            except Exception as e:
                results.append({
                    "column": col,
                    "unique_values": None,
                    "cardinality_ratio": None,
                    "skew_ratio": None,
                    "cv": None,
                    "null_count": None,
                    "is_good_distkey": False,
                    "recommendation": f"Error: {e}",
                })

        comparison_df = pd.DataFrame(results)
        # Sort by skew ratio (lower is better)
        comparison_df = comparison_df.sort_values(
            "skew_ratio", ascending=True, na_position="last"
        )
        return comparison_df


@dataclass
class UniqueKeyValidation:
    """
    Results of unique key validation.

    Attributes:
        columns: Columns that form the key.
        is_unique: Whether the combination is unique.
        total_rows: Total number of rows.
        unique_combinations: Number of unique key combinations.
        duplicate_count: Number of duplicate key occurrences.
        duplicate_rows: Total rows involved in duplicates.
        sample_duplicates: Sample of duplicate key values.
    """

    columns: list[str]
    is_unique: bool
    total_rows: int
    unique_combinations: int
    duplicate_count: int
    duplicate_rows: int
    sample_duplicates: pd.DataFrame | None

    def summary(self) -> str:
        """Generate human-readable summary."""
        key_cols = ", ".join(f"'{c}'" for c in self.columns)
        lines = [
            f"Unique Key Validation: {key_cols}",
            "=" * 50,
            f"Total Rows:           {self.total_rows:,}",
            f"Unique Combinations:  {self.unique_combinations:,}",
            f"Is Unique:            {'Yes' if self.is_unique else 'No'}",
        ]

        if not self.is_unique:
            lines.extend([
                "",
                f"Duplicate Keys:       {self.duplicate_count:,}",
                f"Rows with Duplicates: {self.duplicate_rows:,}",
            ])

            if self.sample_duplicates is not None and not self.sample_duplicates.empty:
                lines.extend(["", "Sample Duplicates:"])
                lines.append(self.sample_duplicates.to_string())

        return "\n".join(lines)


class UniqueKeyValidator:
    """
    Validate unique key constraints before loading to Redshift.

    Redshift enforces unique constraints but does not prevent duplicate
    inserts (it's the user's responsibility). This validator helps
    identify duplicates before attempting to load.

    Example:
        >>> validator = UniqueKeyValidator()
        >>> result = validator.validate(df, ['user_id', 'event_date'])
        >>> if not result.is_unique:
        ...     print(f"Found {result.duplicate_count} duplicate keys!")
        ...     print(result.sample_duplicates)
    """

    def validate(
        self,
        df: pd.DataFrame,
        columns: list[str] | str,
        sample_size: int = 10,
    ) -> UniqueKeyValidation:
        """
        Validate that columns form a unique key.

        Args:
            df: DataFrame to validate.
            columns: Column(s) that should be unique.
            sample_size: Number of duplicate examples to include.

        Returns:
            UniqueKeyValidation with detailed results.
        """
        if isinstance(columns, str):
            columns = [columns]

        # Validate columns exist
        missing = [c for c in columns if c not in df.columns]
        if missing:
            raise ValidationError(
                f"Columns not found: {missing}",
                field="columns",
                received=str(missing),
            )

        total_rows = len(df)

        # Count unique combinations
        if len(columns) == 1:
            unique_combinations = df[columns[0]].nunique()
            duplicated_mask = df[columns[0]].duplicated(keep=False)
        else:
            unique_combinations = df.groupby(columns, dropna=False).ngroups
            duplicated_mask = df.duplicated(subset=columns, keep=False)

        is_unique = unique_combinations == total_rows

        # Count duplicates
        duplicate_rows = int(duplicated_mask.sum())
        duplicate_count = total_rows - unique_combinations

        # Get sample duplicates
        sample_duplicates = None
        if not is_unique and duplicate_rows > 0:
            duplicates_df = df[duplicated_mask]

            # Get sample of duplicate keys
            if len(columns) == 1:
                dup_keys = duplicates_df[columns[0]].value_counts()
                dup_keys = dup_keys[dup_keys > 1].head(sample_size)
                sample_keys = dup_keys.index.tolist()
                sample_duplicates = df[df[columns[0]].isin(sample_keys)][columns + [c for c in df.columns if c not in columns][:3]]
            else:
                # For composite keys, get first N duplicate groups
                dup_groups = duplicates_df.groupby(columns, dropna=False).size()
                dup_groups = dup_groups[dup_groups > 1].head(sample_size)

                # Build filter for sample
                sample_rows = []
                for key_vals in dup_groups.index:
                    if not isinstance(key_vals, tuple):
                        key_vals = (key_vals,)
                    mask = pd.Series(True, index=df.index)
                    for col, val in zip(columns, key_vals):
                        if pd.isna(val):
                            mask &= df[col].isna()
                        else:
                            mask &= df[col] == val
                    sample_rows.append(df[mask].head(3))

                if sample_rows:
                    sample_duplicates = pd.concat(sample_rows, ignore_index=True)

            if sample_duplicates is not None:
                sample_duplicates = sample_duplicates.head(sample_size * 3)

        return UniqueKeyValidation(
            columns=columns,
            is_unique=is_unique,
            total_rows=total_rows,
            unique_combinations=unique_combinations,
            duplicate_count=duplicate_count,
            duplicate_rows=duplicate_rows,
            sample_duplicates=sample_duplicates,
        )

    def find_natural_keys(
        self,
        df: pd.DataFrame,
        max_columns: int = 3,
        exclude_columns: list[str] | None = None,
    ) -> list[tuple[list[str], int]]:
        """
        Find potential natural keys in the DataFrame.

        Args:
            df: DataFrame to analyze.
            max_columns: Maximum columns in a composite key.
            exclude_columns: Columns to exclude from consideration.

        Returns:
            List of (column_combination, unique_count) tuples,
            sorted by uniqueness (unique combinations descending).
        """
        exclude = set(exclude_columns or [])
        candidates = [c for c in df.columns if c not in exclude]

        results: list[tuple[list[str], int]] = []
        total_rows = len(df)

        # Check single columns
        for col in candidates:
            unique_count = df[col].nunique()
            if unique_count == total_rows:
                results.append(([col], unique_count))

        # Check pairs if no single column is unique
        if not results and max_columns >= 2:
            from itertools import combinations

            for cols in combinations(candidates, 2):
                unique_count = df.groupby(list(cols), dropna=False).ngroups
                if unique_count == total_rows:
                    results.append((list(cols), unique_count))

        # Check triples if needed
        if not results and max_columns >= 3:
            from itertools import combinations

            for cols in combinations(candidates, 3):
                unique_count = df.groupby(list(cols), dropna=False).ngroups
                if unique_count == total_rows:
                    results.append((list(cols), unique_count))

        # Sort by number of columns (prefer simpler keys)
        results.sort(key=lambda x: (len(x[0]), -x[1]))
        return results
