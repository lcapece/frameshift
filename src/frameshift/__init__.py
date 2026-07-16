"""
Frameshift: load pandas DataFrames into Amazon Redshift without S3.

Frameshift generates multi-row INSERT statements. It exists for
environments where Redshift's COPY command is not an option -- no S3 write
access, no permission to create a staging bucket, or a network path that
does not reach S3 at all.

It is not a fast way to load Redshift, and it is not trying to be. If you
can reach S3, use COPY. See the README for where the line falls.
"""

from importlib.metadata import PackageNotFoundError, version

from frameshift.analyzer import (
    DistributionAnalysis,
    DistributionAnalyzer,
    UniqueKeyValidation,
    UniqueKeyValidator,
)
from frameshift.chunker import Chunk, DataFrameChunker, SQLGenerator
from frameshift.config import FrameShiftConfig
from frameshift.core import FrameShift, LoadResult
from frameshift.exceptions import (
    ChunkingError,
    DataTypeError,
    FrameShiftError,
    InsertError,
    RedshiftConnectionError,
    ValidationError,
)
from frameshift.identifiers import quote_identifier, validate_identifier
from frameshift.schema import SchemaInferer, TableSchema
from frameshift.types import (
    ColumnSpec,
    RedshiftType,
    infer_redshift_type,
    python_to_sql_value,
)

try:
    # Read the version from installed package metadata so it cannot drift
    # from pyproject.toml.
    __version__ = version("frameshift")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0.0.0.dev0"

__author__ = "Louis N. Capece"

__all__ = [
    # Core
    "FrameShift",
    "FrameShiftConfig",
    "LoadResult",
    # Schema
    "SchemaInferer",
    "TableSchema",
    "ColumnSpec",
    "RedshiftType",
    # Analysis
    "DistributionAnalysis",
    "DistributionAnalyzer",
    "UniqueKeyValidation",
    "UniqueKeyValidator",
    # SQL generation
    "Chunk",
    "DataFrameChunker",
    "SQLGenerator",
    "infer_redshift_type",
    "python_to_sql_value",
    "quote_identifier",
    "validate_identifier",
    # Exceptions
    "FrameShiftError",
    "ChunkingError",
    "DataTypeError",
    "InsertError",
    "RedshiftConnectionError",
    "ValidationError",
    # Metadata
    "__version__",
]
