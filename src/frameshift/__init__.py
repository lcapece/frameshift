"""Frameshift package."""

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

__version__ = "0.2.0"
__author__ = "Louis N. Capece"
