"""
Custom exceptions for the Frameshift library.

All exceptions inherit from FrameShiftError for easy catching
of any library-specific errors.
"""

from typing import Any


class FrameShiftError(Exception):
    """
    Base exception for all Frameshift errors.

    All custom exceptions in this library inherit from this class,
    allowing users to catch any Frameshift-related error with a
    single except clause.

    Example:
        >>> try:
        ...     fs.load(df, 'table')
        ... except FrameShiftError as e:
        ...     print(f"Frameshift error: {e}")
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} | Details: {self.details}"
        return self.message


class RedshiftConnectionError(FrameShiftError):
    """
    Raised when a database connection cannot be established.

    This may occur due to incorrect credentials, network issues,
    or an unavailable Redshift cluster.
    """

    def __init__(
        self,
        message: str = "Failed to connect to Redshift",
        host: str | None = None,
        port: int | None = None,
        **kwargs: Any,
    ) -> None:
        details = {"host": host, "port": port, **kwargs}
        super().__init__(message, details={k: v for k, v in details.items() if v is not None})


class ChunkingError(FrameShiftError):
    """
    Raised when data cannot be properly chunked for insertion.

    This may occur if a single row exceeds the maximum statement size,
    or if the data cannot be serialized properly.
    """

    def __init__(
        self,
        message: str = "Failed to chunk DataFrame",
        row_index: int | None = None,
        chunk_size: int | None = None,
        **kwargs: Any,
    ) -> None:
        details = {"row_index": row_index, "chunk_size": chunk_size, **kwargs}
        super().__init__(message, details={k: v for k, v in details.items() if v is not None})


class DataTypeError(FrameShiftError):
    """
    Raised when a data type conversion fails.

    This may occur when a DataFrame column cannot be converted
    to a compatible Redshift data type.
    """

    def __init__(
        self,
        message: str = "Data type conversion failed",
        column: str | None = None,
        dtype: str | None = None,
        value: Any = None,
        **kwargs: Any,
    ) -> None:
        details = {"column": column, "dtype": dtype, "value": repr(value), **kwargs}
        super().__init__(message, details={k: v for k, v in details.items() if v is not None})


class InsertError(FrameShiftError):
    """
    Raised when an INSERT statement fails to execute.

    This includes SQL syntax errors, constraint violations,
    and other database-level errors during insertion.
    """

    def __init__(
        self,
        message: str = "INSERT statement failed",
        table: str | None = None,
        rows_attempted: int | None = None,
        rows_inserted: int | None = None,
        sql_error: str | None = None,
        **kwargs: Any,
    ) -> None:
        details = {
            "table": table,
            "rows_attempted": rows_attempted,
            "rows_inserted": rows_inserted,
            "sql_error": sql_error,
            **kwargs,
        }
        super().__init__(message, details={k: v for k, v in details.items() if v is not None})


class ValidationError(FrameShiftError):
    """
    Raised when input validation fails.

    This includes invalid configuration options, malformed
    DataFrames, or invalid table/column names.
    """

    def __init__(
        self,
        message: str = "Validation failed",
        field: str | None = None,
        expected: str | None = None,
        received: str | None = None,
        **kwargs: Any,
    ) -> None:
        details = {"field": field, "expected": expected, "received": received, **kwargs}
        super().__init__(message, details={k: v for k, v in details.items() if v is not None})
