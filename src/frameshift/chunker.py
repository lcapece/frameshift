"""
DataFrame chunking for multi-row INSERT statements.

This module handles splitting DataFrames into chunks that fit within
Redshift's 16 MB SQL statement size limit.
"""

from dataclasses import dataclass
from typing import Iterator, Any

import pandas as pd
import numpy as np

from frameshift.config import FrameShiftConfig, MAX_STATEMENT_SIZE_BYTES
from frameshift.types import ColumnSpec, python_to_sql_value
from frameshift.exceptions import ChunkingError


@dataclass
class Chunk:
    """
    A chunk of data ready for INSERT.

    Attributes:
        data: DataFrame slice for this chunk.
        chunk_index: Index of this chunk (0-based).
        start_row: Starting row index in original DataFrame.
        end_row: Ending row index in original DataFrame.
        estimated_size: Estimated SQL statement size in bytes.
        row_count: Number of rows in this chunk.
    """

    data: pd.DataFrame
    chunk_index: int
    start_row: int
    end_row: int
    estimated_size: int
    row_count: int

    def __repr__(self) -> str:
        return (
            f"Chunk(index={self.chunk_index}, rows={self.row_count}, "
            f"range=[{self.start_row}:{self.end_row}], "
            f"size={self.estimated_size:,} bytes)"
        )


class DataFrameChunker:
    """
    Split DataFrames into chunks suitable for multi-row INSERT.

    This class handles the complexity of chunking data to fit within
    Redshift's SQL statement size limits while maximizing rows per
    INSERT for optimal performance.

    The chunker uses adaptive sizing: it starts with an estimated
    rows-per-chunk based on a sample, then adjusts dynamically if
    actual SQL sizes differ from estimates.

    Example:
        >>> chunker = DataFrameChunker(max_bytes=15_000_000)
        >>> for chunk in chunker.chunk(df, column_specs):
        ...     print(f"Chunk {chunk.chunk_index}: {chunk.row_count} rows")
    """

    def __init__(
        self,
        max_bytes: int = MAX_STATEMENT_SIZE_BYTES - 1024 * 1024,
        initial_batch_size: int = 1000,
        sample_size: int = 100,
    ) -> None:
        """
        Initialize the chunker.

        Args:
            max_bytes: Maximum bytes per INSERT statement.
            initial_batch_size: Starting rows per chunk estimate.
            sample_size: Rows to sample for size estimation.
        """
        self.max_bytes = max_bytes
        self.initial_batch_size = initial_batch_size
        self.sample_size = sample_size

    def chunk(
        self,
        df: pd.DataFrame,
        column_specs: list[ColumnSpec],
        insert_prefix_size: int = 0,
    ) -> Iterator[Chunk]:
        """
        Generate chunks from a DataFrame.

        Args:
            df: DataFrame to chunk.
            column_specs: Column specifications for SQL generation.
            insert_prefix_size: Size of INSERT prefix in bytes.

        Yields:
            Chunk objects containing data slices.
        """
        if df.empty:
            return

        total_rows = len(df)

        # Estimate average row size from sample
        avg_row_size = self._estimate_row_size(df, column_specs)

        # Calculate initial rows per chunk
        available_bytes = self.max_bytes - insert_prefix_size - 100  # Safety margin
        estimated_rows_per_chunk = max(1, int(available_bytes / avg_row_size))

        # Cap at reasonable maximum
        rows_per_chunk = min(estimated_rows_per_chunk, self.initial_batch_size * 10)

        chunk_index = 0
        start_row = 0

        while start_row < total_rows:
            # Get candidate chunk
            end_row = min(start_row + rows_per_chunk, total_rows)
            chunk_df = df.iloc[start_row:end_row]

            # Calculate actual size
            actual_size = self._calculate_chunk_size(
                chunk_df, column_specs, insert_prefix_size
            )

            # Adjust if too large
            if actual_size > self.max_bytes and len(chunk_df) > 1:
                # Binary search for optimal chunk size
                rows_per_chunk = self._find_optimal_chunk_size(
                    df,
                    column_specs,
                    insert_prefix_size,
                    start_row,
                    rows_per_chunk,
                )
                end_row = min(start_row + rows_per_chunk, total_rows)
                chunk_df = df.iloc[start_row:end_row]
                actual_size = self._calculate_chunk_size(
                    chunk_df, column_specs, insert_prefix_size
                )

            # Verify single row doesn't exceed limit
            if len(chunk_df) == 1 and actual_size > self.max_bytes:
                raise ChunkingError(
                    f"Single row at index {start_row} exceeds maximum "
                    f"statement size ({actual_size:,} > {self.max_bytes:,} bytes)",
                    row_index=start_row,
                    chunk_size=actual_size,
                )

            yield Chunk(
                data=chunk_df.reset_index(drop=True),
                chunk_index=chunk_index,
                start_row=start_row,
                end_row=end_row,
                estimated_size=actual_size,
                row_count=len(chunk_df),
            )

            start_row = end_row
            chunk_index += 1

            # Adapt rows_per_chunk based on this chunk
            if actual_size > 0:
                efficiency = actual_size / self.max_bytes
                if efficiency < 0.5:
                    # Under-utilized, increase chunk size
                    rows_per_chunk = min(
                        int(rows_per_chunk * 1.5),
                        total_rows - start_row,
                    )
                elif efficiency > 0.9:
                    # Near limit, be more conservative
                    rows_per_chunk = max(1, int(rows_per_chunk * 0.8))

    def _estimate_row_size(
        self,
        df: pd.DataFrame,
        column_specs: list[ColumnSpec],
    ) -> float:
        """Estimate average row size from a sample."""
        sample_size = min(self.sample_size, len(df))
        if sample_size == 0:
            return 100  # Default estimate

        # Sample random rows
        sample_df = df.sample(n=sample_size, random_state=42)

        total_size = 0
        for _, row in sample_df.iterrows():
            row_size = self._calculate_row_size(row, column_specs)
            total_size += row_size

        return total_size / sample_size

    def _calculate_row_size(
        self,
        row: pd.Series,
        column_specs: list[ColumnSpec],
    ) -> int:
        """Calculate the SQL size of a single row."""
        # Size of "(" + values + ")," format
        size = 3  # "(", ")", ","

        values = []
        for col_spec in column_specs:
            value = row.get(col_spec.name)
            sql_value = python_to_sql_value(value, col_spec.redshift_type)
            values.append(sql_value)

        # Join with ", "
        values_str = ", ".join(values)
        size += len(values_str.encode("utf-8"))

        return size

    def _calculate_chunk_size(
        self,
        chunk_df: pd.DataFrame,
        column_specs: list[ColumnSpec],
        insert_prefix_size: int,
    ) -> int:
        """Calculate total SQL size for a chunk."""
        size = insert_prefix_size

        row_sizes = []
        for _, row in chunk_df.iterrows():
            row_size = self._calculate_row_size(row, column_specs)
            row_sizes.append(row_size)

        # Sum all row sizes, accounting for spacing
        size += sum(row_sizes)
        # Add newlines between rows
        size += len(chunk_df) * 2

        return size

    def _find_optimal_chunk_size(
        self,
        df: pd.DataFrame,
        column_specs: list[ColumnSpec],
        insert_prefix_size: int,
        start_row: int,
        max_rows: int,
    ) -> int:
        """Binary search for optimal chunk size."""
        left = 1
        right = max_rows
        optimal = 1

        while left <= right:
            mid = (left + right) // 2
            end_row = min(start_row + mid, len(df))
            chunk_df = df.iloc[start_row:end_row]

            size = self._calculate_chunk_size(
                chunk_df, column_specs, insert_prefix_size
            )

            if size <= self.max_bytes:
                optimal = mid
                left = mid + 1
            else:
                right = mid - 1

        return optimal

    def estimate_chunks(
        self,
        df: pd.DataFrame,
        column_specs: list[ColumnSpec],
        insert_prefix_size: int = 0,
    ) -> dict[str, Any]:
        """
        Estimate chunking statistics without actually chunking.

        Args:
            df: DataFrame to analyze.
            column_specs: Column specifications.
            insert_prefix_size: Size of INSERT prefix.

        Returns:
            Dictionary with chunking estimates.
        """
        if df.empty:
            return {
                "total_rows": 0,
                "estimated_chunks": 0,
                "avg_row_size_bytes": 0,
                "estimated_total_size_bytes": 0,
                "max_rows_per_chunk": 0,
            }

        avg_row_size = self._estimate_row_size(df, column_specs)
        available_bytes = self.max_bytes - insert_prefix_size - 100

        estimated_rows_per_chunk = max(1, int(available_bytes / avg_row_size))
        estimated_chunks = max(1, len(df) // estimated_rows_per_chunk + 1)

        return {
            "total_rows": len(df),
            "estimated_chunks": estimated_chunks,
            "avg_row_size_bytes": int(avg_row_size),
            "estimated_total_size_bytes": int(avg_row_size * len(df)),
            "max_rows_per_chunk": estimated_rows_per_chunk,
            "max_statement_bytes": self.max_bytes,
        }


class SQLGenerator:
    """
    Generate SQL INSERT statements from DataFrames.

    This class creates properly formatted multi-row INSERT statements
    with correct escaping and type conversion.
    """

    def __init__(
        self,
        table_name: str,
        schema_name: str | None = None,
        column_specs: list[ColumnSpec] | None = None,
    ) -> None:
        """
        Initialize the SQL generator.

        Args:
            table_name: Target table name.
            schema_name: Schema name (optional).
            column_specs: Column specifications for type handling.
        """
        self.table_name = table_name
        self.schema_name = schema_name
        self.column_specs = column_specs or []

    @property
    def full_table_name(self) -> str:
        """Get fully qualified table name."""
        if self.schema_name:
            return f'"{self.schema_name}"."{self.table_name}"'
        return f'"{self.table_name}"'

    def generate_insert_prefix(self, include_columns: bool = True) -> str:
        """Generate the INSERT INTO ... VALUES prefix."""
        if include_columns and self.column_specs:
            col_names = ", ".join(f'"{col.name}"' for col in self.column_specs)
            return f"INSERT INTO {self.full_table_name} ({col_names}) VALUES\n"
        return f"INSERT INTO {self.full_table_name} VALUES\n"

    def generate_insert_statement(
        self,
        df: pd.DataFrame,
        include_columns: bool = True,
    ) -> str:
        """
        Generate complete INSERT statement for a DataFrame.

        Args:
            df: DataFrame to convert.
            include_columns: Whether to include column names.

        Returns:
            Complete INSERT statement string.
        """
        if df.empty:
            return ""

        prefix = self.generate_insert_prefix(include_columns)
        rows = []

        for _, row in df.iterrows():
            values = []
            for col_spec in self.column_specs:
                value = row.get(col_spec.name)
                sql_value = python_to_sql_value(value, col_spec.redshift_type)
                values.append(sql_value)

            row_sql = f"({', '.join(values)})"
            rows.append(row_sql)

        return prefix + ",\n".join(rows) + ";"

    def generate_values_only(self, df: pd.DataFrame) -> str:
        """
        Generate only the VALUES portion (no INSERT prefix).

        Useful for combining with parameterized queries or
        for debugging/logging purposes.
        """
        if df.empty:
            return ""

        rows = []
        for _, row in df.iterrows():
            values = []
            for col_spec in self.column_specs:
                value = row.get(col_spec.name)
                sql_value = python_to_sql_value(value, col_spec.redshift_type)
                values.append(sql_value)

            row_sql = f"({', '.join(values)})"
            rows.append(row_sql)

        return ",\n".join(rows)
