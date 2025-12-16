"""
Frameshift: Load pandas DataFrames into Amazon Redshift without S3.

This library enables direct DataFrame-to-Redshift loading using efficient
multi-row INSERT statements, bypassing the need for S3 staging.

**IMPORTANT: Use Case Guidance**

This library is designed for AD-HOC use cases:
- Development and testing environments
- One-time data migrations
- Exploratory data analysis
- Situations where S3 access is not available
- Small to medium datasets (typically < 1M rows)

This library is NOT recommended for:
- Repetitive ETL jobs or production pipelines
- Very large datasets (> 1M rows)
- High-frequency data loading
- Performance-critical applications

For production ETL workloads, always prefer the COPY command with S3
staging, which offers parallel loading and much higher throughput.

Example:
    >>> import pandas as pd
    >>> from frameshift import FrameShift
    >>>
    >>> df = pd.DataFrame({'id': [1, 2, 3], 'name': ['Alice', 'Bob', 'Charlie']})
    >>> fs = FrameShift(
    ...     host='your-cluster.region.redshift.amazonaws.com',
    ...     database='mydb',
    ...     user='admin',
    ...     password='secret',
    ...     port=5439
    ... )
    >>> result = fs.load(df, 'my_table')
    >>> print(result.summary())

Distribution Analysis:
    >>> # Analyze a column before choosing as DISTKEY
    >>> analysis = fs.analyze_distribution(df, 'user_id')
    >>> print(analysis.summary())
    >>> print(f"Good DISTKEY: {analysis.is_good_distkey()}")

Unique Key Validation:
    >>> validation = fs.validate_unique_key(df, ['user_id', 'event_date'])
    >>> if not validation.is_unique:
    ...     print(f"Found {validation.duplicate_count} duplicates!")
"""

from frameshift.core import FrameShift, LoadResult
from frameshift.config import FrameShiftConfig
from frameshift.schema import SchemaInferer, TableSchema
from frameshift.chunker import DataFrameChunker, SQLGenerator, Chunk
from frameshift.analyzer import (
    DistributionAnalyzer,
    DistributionAnalysis,
    UniqueKeyValidator,
    UniqueKeyValidation,
)
from frameshift.types import (
    RedshiftType,
    ColumnSpec,
    infer_redshift_type,
    python_to_sql_value,
)
from frameshift.exceptions import (
    FrameShiftError,
    RedshiftConnectionError,
    ChunkingError,
    DataTypeError,
    InsertError,
    ValidationError,
)

__version__ = "0.1.0"
__author__ = "Louis N. Capece"

__all__ = [
    # Main interface
    "FrameShift",
    "LoadResult",
    # Configuration
    "FrameShiftConfig",
    # Schema
    "SchemaInferer",
    "TableSchema",
    # Chunking
    "DataFrameChunker",
    "SQLGenerator",
    "Chunk",
    # Analysis
    "DistributionAnalyzer",
    "DistributionAnalysis",
    "UniqueKeyValidator",
    "UniqueKeyValidation",
    # Types
    "RedshiftType",
    "ColumnSpec",
    "infer_redshift_type",
    "python_to_sql_value",
    # Exceptions
    "FrameShiftError",
    "RedshiftConnectionError",
    "ChunkingError",
    "DataTypeError",
    "InsertError",
    "ValidationError",
    # Version
    "__version__",
]
