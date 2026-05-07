"""Configuration for Frameshift."""

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
    Configuration settings for loading DataFrames into Redshift.
    """

    # Size limits
    max_statement_bytes: int = DEFAULT_MAX_STATEMENT_SIZE
    batch_size: int = 1000

    # Transaction handling
    use_transactions: bool = True
    commit_every: int = 0  # 0 = single transaction for all chunks

    # Error handling
    on_error: Literal["abort", "skip", "log"] = "abort"

    # SQL formatting
    include_columns: bool = True

    # Schema/table options
    schema: str | None = None

    # Data type options
    varchar_max_length: int = 65535
    preserve_index: bool = False

    # Execution options
    dry_run: bool = False
    verbosity: int = 1

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
        Create a configuration for larger loads.

        Returns:
            FrameShiftConfig configured for larger loads.
        """
        return cls(
            max_statement_bytes=15 * 1024 * 1024,  # 15 MB
            batch_size=5000,
            commit_every=1,  # Commit after each chunk
        )

    @classmethod
    def for_small_datasets(cls) -> "FrameShiftConfig":
        """
        Create a configuration for small loads.

        Returns:
            FrameShiftConfig configured for small loads.
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
