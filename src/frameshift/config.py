"""
Configuration management for Frameshift.

This module provides a centralized configuration class with
sensible defaults and validation for all Frameshift settings.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

# Redshift SQL statement maximum size is 16 MB
# We use a conservative default to leave room for SQL overhead
MAX_STATEMENT_SIZE_BYTES = 16 * 1024 * 1024  # 16 MB
DEFAULT_MAX_STATEMENT_SIZE = 15 * 1024 * 1024  # 15 MB (conservative)

# Redshift Data API has a 100 KB limit
DATA_API_MAX_SIZE = 100 * 1024  # 100 KB


@dataclass
class FrameShiftConfig:
    """
    Configuration settings for Frameshift operations.

    This class encapsulates all configuration options with sensible
    defaults optimized for typical Redshift workloads.

    Attributes:
        max_statement_bytes: Maximum size of a single INSERT statement in bytes.
            Defaults to 15 MB (conservative limit under Redshift's 16 MB max).
        batch_size: Number of rows to attempt per INSERT statement before
            checking size constraints. This is an initial estimate that
            gets adjusted based on actual data size.
        use_transactions: Whether to wrap all inserts in a transaction.
        commit_every: Commit transaction every N chunks (0 = single transaction).
        on_error: Error handling strategy ('abort', 'skip', 'log').
        null_string: String to use for NULL values in SQL.
        escape_quotes: Whether to escape single quotes in string values.
        include_columns: If True, include column names in INSERT statements.
        schema: Default schema name (None uses 'public').
        table_exists_action: Action when table doesn't exist ('error', 'create').
        progress_callback: Optional callback for progress reporting.
        varchar_max_length: Default VARCHAR length for string columns.
        preserve_index: Whether to include DataFrame index as a column.
        dry_run: If True, generate SQL without executing.
        verbosity: Logging verbosity level (0=quiet, 1=normal, 2=verbose).

    Example:
        >>> config = FrameShiftConfig(
        ...     max_statement_bytes=10 * 1024 * 1024,  # 10 MB
        ...     batch_size=5000,
        ...     use_transactions=True,
        ...     commit_every=10,  # Commit every 10 chunks
        ... )
        >>> fs = FrameShift(config=config, **conn_params)
    """

    # Size limits
    max_statement_bytes: int = DEFAULT_MAX_STATEMENT_SIZE
    batch_size: int = 1000

    # Parallel loading (MD5 hash distribution across threads)
    parallel_threads: int = 4  # 0=auto, 1=single-threaded, 2-16=fixed threads
    parallel_threshold: int = 5000  # Min rows to enable parallel (when auto)

    # Transaction handling
    use_transactions: bool = True
    commit_every: int = 0  # 0 = single transaction for all chunks

    # Error handling
    on_error: Literal["abort", "skip", "log"] = "abort"

    # SQL formatting
    null_string: str = "NULL"
    escape_quotes: bool = True
    include_columns: bool = True

    # Schema/table options
    schema: str | None = None
    table_exists_action: Literal["error", "create"] = "error"

    # Data type options
    varchar_max_length: int = 65535
    preserve_index: bool = False

    # Execution options
    dry_run: bool = False
    verbosity: int = 1

    # Progress tracking
    progress_callback: Any = None

    # Internal tracking (not user-configurable)
    _estimated_row_size: int = field(default=0, repr=False)

    def __post_init__(self) -> None:
        """Validate configuration values."""
        if self.max_statement_bytes > MAX_STATEMENT_SIZE_BYTES:
            raise ValueError(
                f"max_statement_bytes ({self.max_statement_bytes}) exceeds "
                f"Redshift's 16 MB limit ({MAX_STATEMENT_SIZE_BYTES})"
            )
        if self.max_statement_bytes < 1024:
            raise ValueError("max_statement_bytes must be at least 1024 bytes")
        if self.batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        if self.on_error not in ("abort", "skip", "log"):
            raise ValueError(f"on_error must be 'abort', 'skip', or 'log', got {self.on_error}")
        if self.varchar_max_length < 1 or self.varchar_max_length > 65535:
            raise ValueError("varchar_max_length must be between 1 and 65535")
        if self.parallel_threads < 0 or self.parallel_threads > 16:
            raise ValueError("parallel_threads must be between 0 and 16 (0=auto)")
        if self.parallel_threshold < 1:
            raise ValueError("parallel_threshold must be at least 1")

    @classmethod
    def for_data_api(cls) -> "FrameShiftConfig":
        """
        Create a configuration optimized for Redshift Data API.

        The Data API has a 100 KB query limit, so this configuration
        uses smaller batch sizes and statement sizes.

        Returns:
            FrameShiftConfig configured for Data API usage.
        """
        return cls(
            max_statement_bytes=95 * 1024,  # 95 KB (conservative)
            batch_size=100,
        )

    @classmethod
    def for_large_datasets(cls) -> "FrameShiftConfig":
        """
        Create a configuration optimized for large dataset loading.

        Uses maximum statement sizes, parallel threads, and periodic
        commits to balance performance with memory usage.

        Returns:
            FrameShiftConfig configured for large datasets.
        """
        return cls(
            max_statement_bytes=15 * 1024 * 1024,  # 15 MB
            batch_size=5000,
            parallel_threads=8,  # Use 8 parallel threads
            commit_every=1,  # Commit after each chunk per thread
        )

    @classmethod
    def for_small_datasets(cls) -> "FrameShiftConfig":
        """
        Create a configuration optimized for small dataset loading.

        Uses smaller batches for faster initial feedback and
        simpler error handling.

        Returns:
            FrameShiftConfig configured for small datasets.
        """
        return cls(
            max_statement_bytes=1 * 1024 * 1024,  # 1 MB
            batch_size=100,
            use_transactions=True,
            commit_every=1,  # Commit after each chunk
        )

    def copy(self, **overrides: Any) -> "FrameShiftConfig":
        """
        Create a copy of this configuration with optional overrides.

        Args:
            **overrides: Configuration values to override.

        Returns:
            New FrameShiftConfig instance with overridden values.
        """
        from dataclasses import asdict

        current = asdict(self)
        # Remove internal fields
        current.pop("_estimated_row_size", None)
        current.update(overrides)
        return FrameShiftConfig(**current)
