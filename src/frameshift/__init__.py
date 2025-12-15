"""
Frameshift: Load pandas DataFrames into Amazon Redshift without S3.

This library enables direct DataFrame-to-Redshift loading using efficient
multi-row INSERT statements, bypassing the need for S3 staging.

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
    >>> fs.load(df, 'my_table')
"""

from frameshift.core import FrameShift
from frameshift.chunker import DataFrameChunker
from frameshift.config import FrameShiftConfig
from frameshift.exceptions import (
    FrameShiftError,
    ConnectionError,
    ChunkingError,
    DataTypeError,
    InsertError,
    ValidationError,
)

__version__ = "0.1.0"
__author__ = "Ryan H"

__all__ = [
    # Main interface
    "FrameShift",
    # Configuration
    "FrameShiftConfig",
    # Utilities
    "DataFrameChunker",
    # Exceptions
    "FrameShiftError",
    "ConnectionError",
    "ChunkingError",
    "DataTypeError",
    "InsertError",
    "ValidationError",
    # Version
    "__version__",
]
