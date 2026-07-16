"""
Frameshift: get a pandas DataFrame into Amazon Redshift without S3.

For when you need data in Redshift and cannot use COPY -- no S3 write
access, no network path to S3 from your VPC, or no time to get either
approved. Frameshift talks to Redshift over the connection you already
have, and needs nothing else.

This is not a best practice and it is not for production. Loading Redshift
with INSERT is the wrong way to load Redshift: the right way is COPY from
S3, which ingests in parallel across every slice. Frameshift sends
statements down one connection for the leader node to parse. It is the slow
way, deliberately, because it is what is left when S3 is off the table.

Use it to get out of a bind -- a one-off load, a lookup table, a test
fixture, a locked-down environment. Do not schedule it nightly; if you find
yourself doing that, go get S3 access.

What it does promise is that the quick-and-dirty path is correct: values
escaped properly, sensible inferred types with real DISTKEY/SORTKEY support,
statements sized to fit Redshift's limits, and failures that roll back
rather than leaving you half-loaded.

If you can reach S3, use COPY.
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
