"""
Schema inference and table creation for Frameshift.

This module provides intelligent DataFrame-to-Redshift schema conversion,
including recommendations for DISTKEY, SORTKEY, and encoding options.
"""

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from frameshift.types import ColumnSpec, RedshiftType, infer_redshift_type
from frameshift.exceptions import ValidationError


@dataclass
class TableSchema:
    """
    Complete Redshift table schema definition.

    Attributes:
        table_name: Name of the table.
        schema_name: Schema name (default: 'public').
        columns: List of column specifications.
        distkey: Column name for distribution key.
        diststyle: Distribution style ('KEY', 'EVEN', 'ALL', 'AUTO').
        sortkey: List of column names for sort key.
        sortkey_type: Type of sort key ('COMPOUND' or 'INTERLEAVED').
        primary_key: List of column names for primary key.
        unique_keys: List of column name lists for unique constraints.
        if_not_exists: Add IF NOT EXISTS clause.
        temporary: Create as temporary table.
        backup: Enable backup ('YES' or 'NO').
    """

    table_name: str
    schema_name: str = "public"
    columns: list[ColumnSpec] = field(default_factory=list)
    distkey: str | None = None
    diststyle: str = "AUTO"
    sortkey: list[str] = field(default_factory=list)
    sortkey_type: str = "COMPOUND"
    primary_key: list[str] = field(default_factory=list)
    unique_keys: list[list[str]] = field(default_factory=list)
    if_not_exists: bool = True
    temporary: bool = False
    backup: str = "YES"

    def __post_init__(self) -> None:
        """Validate schema configuration."""
        if self.diststyle not in ("KEY", "EVEN", "ALL", "AUTO"):
            raise ValidationError(
                f"Invalid diststyle: {self.diststyle}",
                field="diststyle",
                expected="KEY, EVEN, ALL, or AUTO",
                received=self.diststyle,
            )
        if self.distkey and self.diststyle != "KEY":
            self.diststyle = "KEY"
        if self.sortkey_type not in ("COMPOUND", "INTERLEAVED"):
            raise ValidationError(
                f"Invalid sortkey_type: {self.sortkey_type}",
                field="sortkey_type",
                expected="COMPOUND or INTERLEAVED",
                received=self.sortkey_type,
            )

    @property
    def full_table_name(self) -> str:
        """Get fully qualified table name."""
        if self.schema_name:
            return f'"{self.schema_name}"."{self.table_name}"'
        return f'"{self.table_name}"'

    def to_create_table_sql(self) -> str:
        """
        Generate CREATE TABLE SQL statement.

        Returns:
            Complete CREATE TABLE statement with all options.
        """
        parts = ["CREATE"]

        if self.temporary:
            parts.append("TEMPORARY")

        parts.append("TABLE")

        if self.if_not_exists:
            parts.append("IF NOT EXISTS")

        parts.append(self.full_table_name)

        # Column definitions
        col_defs = [col.to_sql() for col in self.columns]

        # Primary key constraint
        if self.primary_key:
            pk_cols = ", ".join(f'"{c}"' for c in self.primary_key)
            col_defs.append(f"PRIMARY KEY ({pk_cols})")

        # Unique constraints
        for unique_cols in self.unique_keys:
            uk_cols = ", ".join(f'"{c}"' for c in unique_cols)
            col_defs.append(f"UNIQUE ({uk_cols})")

        parts.append(f"(\n  {',\n  '.join(col_defs)}\n)")

        # Table properties
        table_props = []

        # Backup
        if not self.temporary:
            table_props.append(f"BACKUP {self.backup}")

        # Distribution style/key
        if self.distkey:
            table_props.append(f'DISTSTYLE KEY DISTKEY ("{self.distkey}")')
        elif self.diststyle != "AUTO":
            table_props.append(f"DISTSTYLE {self.diststyle}")

        # Sort key
        if self.sortkey:
            sk_cols = ", ".join(f'"{c}"' for c in self.sortkey)
            if self.sortkey_type == "INTERLEAVED":
                table_props.append(f"INTERLEAVED SORTKEY ({sk_cols})")
            else:
                table_props.append(f"SORTKEY ({sk_cols})")

        if table_props:
            parts.append("\n" + "\n".join(table_props))

        return " ".join(parts) + ";"

    def to_insert_sql(self, include_columns: bool = True) -> str:
        """
        Generate INSERT statement prefix.

        Args:
            include_columns: Whether to include column names.

        Returns:
            INSERT INTO table (columns) VALUES prefix.
        """
        if include_columns:
            col_names = ", ".join(f'"{col.name}"' for col in self.columns)
            return f"INSERT INTO {self.full_table_name} ({col_names}) VALUES"
        return f"INSERT INTO {self.full_table_name} VALUES"


class SchemaInferer:
    """
    Intelligent schema inference from pandas DataFrames.

    This class analyzes DataFrame structure and data characteristics
    to recommend optimal Redshift table schemas, including DISTKEY,
    SORTKEY, and encoding options.

    Example:
        >>> df = pd.DataFrame({
        ...     'user_id': [1, 2, 3],
        ...     'event_date': pd.date_range('2024-01-01', periods=3),
        ...     'event_type': ['click', 'view', 'purchase']
        ... })
        >>> inferer = SchemaInferer()
        >>> schema = inferer.infer_schema(df, 'events')
        >>> print(schema.to_create_table_sql())
    """

    def __init__(
        self,
        varchar_max_length: int = 65535,
        default_encoding: str | None = None,
    ) -> None:
        """
        Initialize the schema inferer.

        Args:
            varchar_max_length: Maximum VARCHAR length to use.
            default_encoding: Default compression encoding.
        """
        self.varchar_max_length = varchar_max_length
        self.default_encoding = default_encoding

    def infer_schema(
        self,
        df: pd.DataFrame,
        table_name: str,
        schema_name: str = "public",
        distkey: str | None = None,
        sortkey: list[str] | str | None = None,
        primary_key: list[str] | str | None = None,
        unique_key: list[str] | str | None = None,
        preserve_index: bool = False,
        auto_suggest_keys: bool = True,
    ) -> TableSchema:
        """
        Infer a complete table schema from a DataFrame.

        Args:
            df: The DataFrame to analyze.
            table_name: Name for the target table.
            schema_name: Schema name (default: 'public').
            distkey: Column to use as distribution key.
            sortkey: Column(s) to use as sort key.
            primary_key: Column(s) for primary key constraint.
            unique_key: Column(s) for unique constraint.
            preserve_index: Include DataFrame index as column.
            auto_suggest_keys: Automatically suggest DISTKEY/SORTKEY.

        Returns:
            TableSchema with inferred column types and keys.
        """
        columns: list[ColumnSpec] = []

        # Handle index
        if preserve_index:
            if df.index.name:
                index_series = df.index.to_series()
                index_series.name = df.index.name
                col_spec = infer_redshift_type(index_series, self.varchar_max_length)
                col_spec.nullable = False
                columns.append(col_spec)
            elif isinstance(df.index, pd.RangeIndex):
                columns.append(
                    ColumnSpec(
                        name="index",
                        redshift_type=RedshiftType.BIGINT,
                        nullable=False,
                    )
                )

        # Infer column types
        for col in df.columns:
            col_spec = infer_redshift_type(df[col], self.varchar_max_length)
            col_spec.name = str(col)
            if self.default_encoding:
                col_spec.encode = self.default_encoding
            columns.append(col_spec)

        # Normalize key inputs
        sortkey_list = self._normalize_key_list(sortkey)
        pk_list = self._normalize_key_list(primary_key)
        uk_list = self._normalize_key_list(unique_key)

        # Auto-suggest keys if enabled and not provided
        if auto_suggest_keys:
            if not distkey:
                distkey = self._suggest_distkey(df, columns)
            if not sortkey_list:
                sortkey_list = self._suggest_sortkey(df, columns)

        # Update column specs with key information
        for col in columns:
            if col.name == distkey:
                col.is_distkey = True
            if col.name in sortkey_list:
                col.is_sortkey = True
                col.sortkey_position = sortkey_list.index(col.name) + 1
            if col.name in pk_list or col.name in uk_list:
                col.is_unique = True
                col.nullable = False

        return TableSchema(
            table_name=table_name,
            schema_name=schema_name,
            columns=columns,
            distkey=distkey,
            sortkey=sortkey_list,
            primary_key=pk_list,
            unique_keys=[uk_list] if uk_list else [],
        )

    def _normalize_key_list(
        self, keys: list[str] | str | None
    ) -> list[str]:
        """Convert key specification to list."""
        if keys is None:
            return []
        if isinstance(keys, str):
            return [keys]
        return list(keys)

    def _suggest_distkey(
        self,
        df: pd.DataFrame,
        columns: list[ColumnSpec],
    ) -> str | None:
        """
        Suggest optimal distribution key based on data characteristics.

        Prefers columns with:
        1. High cardinality (many unique values)
        2. Even distribution
        3. Frequently used in JOINs (common naming patterns)
        """
        candidates: list[tuple[str, float]] = []

        for col_spec in columns:
            col_name = col_spec.name
            if col_name not in df.columns:
                continue

            series = df[col_name]

            # Skip columns with too many NULLs
            null_ratio = series.isna().mean()
            if null_ratio > 0.1:
                continue

            # Calculate cardinality ratio
            unique_count = series.nunique()
            total_count = len(series)
            cardinality_ratio = unique_count / total_count if total_count > 0 else 0

            # Score based on cardinality
            score = cardinality_ratio

            # Bonus for common key patterns
            lower_name = col_name.lower()
            if any(
                pattern in lower_name
                for pattern in ["_id", "id_", "key", "user", "account", "customer"]
            ):
                score *= 1.5

            # Prefer integer types for distribution
            if col_spec.redshift_type in (
                RedshiftType.INTEGER,
                RedshiftType.BIGINT,
            ):
                score *= 1.2

            # Penalize very low cardinality
            if cardinality_ratio < 0.01:
                score *= 0.1

            candidates.append((col_name, score))

        if not candidates:
            return None

        # Return highest scoring column
        candidates.sort(key=lambda x: x[1], reverse=True)
        best_candidate = candidates[0]

        # Only suggest if score is reasonable
        if best_candidate[1] > 0.1:
            return best_candidate[0]

        return None

    def _suggest_sortkey(
        self,
        df: pd.DataFrame,
        columns: list[ColumnSpec],
    ) -> list[str]:
        """
        Suggest optimal sort key based on data characteristics.

        Prefers columns with:
        1. Date/timestamp types (for range queries)
        2. Sequential/ordered data
        3. Common filter patterns
        """
        suggestions: list[tuple[str, float]] = []

        for col_spec in columns:
            col_name = col_spec.name
            if col_name not in df.columns:
                continue

            score = 0.0

            # Strong preference for date/timestamp columns
            if col_spec.redshift_type in (
                RedshiftType.DATE,
                RedshiftType.TIMESTAMP,
                RedshiftType.TIMESTAMPTZ,
            ):
                score = 10.0

                # Extra bonus for common date column names
                lower_name = col_name.lower()
                if any(
                    pattern in lower_name
                    for pattern in [
                        "created",
                        "updated",
                        "date",
                        "time",
                        "timestamp",
                        "_at",
                        "_on",
                    ]
                ):
                    score *= 1.5

            # Also consider status/type columns for compound sortkey
            elif col_spec.redshift_type == RedshiftType.VARCHAR:
                series = df[col_name]
                cardinality = series.nunique()

                # Low cardinality categorical = good secondary sort
                if 2 <= cardinality <= 20:
                    lower_name = col_name.lower()
                    if any(
                        pattern in lower_name
                        for pattern in ["status", "type", "category", "state"]
                    ):
                        score = 3.0

            if score > 0:
                suggestions.append((col_name, score))

        # Sort by score and return top 1-2 columns
        suggestions.sort(key=lambda x: x[1], reverse=True)

        result = []
        for col_name, score in suggestions[:2]:
            if score >= 3.0:  # Only include high-confidence suggestions
                result.append(col_name)

        return result

    def generate_recommendations(
        self,
        df: pd.DataFrame,
        table_name: str,
    ) -> dict[str, Any]:
        """
        Generate detailed schema recommendations with explanations.

        Args:
            df: The DataFrame to analyze.
            table_name: Target table name.

        Returns:
            Dictionary with recommendations and explanations.
        """
        schema = self.infer_schema(
            df, table_name, auto_suggest_keys=True
        )

        recommendations = {
            "table_name": table_name,
            "row_count": len(df),
            "column_count": len(df.columns),
            "estimated_size_mb": df.memory_usage(deep=True).sum() / (1024 * 1024),
            "columns": [],
            "distkey": {
                "column": schema.distkey,
                "reason": self._explain_distkey(df, schema.distkey),
            },
            "sortkey": {
                "columns": schema.sortkey,
                "type": schema.sortkey_type,
                "reason": self._explain_sortkey(df, schema.sortkey),
            },
            "sql": schema.to_create_table_sql(),
        }

        for col_spec in schema.columns:
            # Build type string properly
            type_str = col_spec.redshift_type.value
            if col_spec.length:
                type_str = f"{type_str}({col_spec.length})"
            elif col_spec.precision:
                scale = col_spec.scale or 0
                type_str = f"{type_str}({col_spec.precision},{scale})"

            col_info = {
                "name": col_spec.name,
                "pandas_dtype": str(df[col_spec.name].dtype) if col_spec.name in df.columns else "index",
                "redshift_type": type_str,
                "nullable": col_spec.nullable,
                "null_count": int(df[col_spec.name].isna().sum()) if col_spec.name in df.columns else 0,
                "unique_count": int(df[col_spec.name].nunique()) if col_spec.name in df.columns else 0,
            }
            recommendations["columns"].append(col_info)

        return recommendations

    def _explain_distkey(self, df: pd.DataFrame, distkey: str | None) -> str:
        """Generate explanation for DISTKEY recommendation."""
        if not distkey:
            return (
                "No DISTKEY recommended. Consider using DISTSTYLE AUTO or EVEN "
                "for general-purpose tables, or specify a high-cardinality column "
                "that is frequently used in JOIN conditions."
            )

        if distkey not in df.columns:
            return f"DISTKEY '{distkey}' specified but not found in DataFrame."

        series = df[distkey]
        cardinality = series.nunique()
        cardinality_ratio = cardinality / len(df) if len(df) > 0 else 0

        return (
            f"Column '{distkey}' recommended as DISTKEY: "
            f"{cardinality:,} unique values ({cardinality_ratio:.1%} cardinality). "
            "Good distribution keys have high cardinality and are frequently "
            "used in JOIN conditions to enable collocated joins."
        )

    def _explain_sortkey(self, df: pd.DataFrame, sortkey: list[str]) -> str:
        """Generate explanation for SORTKEY recommendation."""
        if not sortkey:
            return (
                "No SORTKEY recommended. Consider adding a date/timestamp column "
                "as SORTKEY if you frequently filter by time ranges."
            )

        explanations = []
        for col in sortkey:
            if col in df.columns:
                dtype = str(df[col].dtype)
                explanations.append(f"'{col}' ({dtype})")

        return (
            f"Columns {', '.join(explanations)} recommended as SORTKEY. "
            "Sort keys optimize range-restricted queries and improve "
            "compression for sorted data."
        )
