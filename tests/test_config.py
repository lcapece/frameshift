"""Tests for configuration module."""

import pytest

from frameshift.config import (
    FrameShiftConfig,
    MAX_STATEMENT_SIZE_BYTES,
    DEFAULT_MAX_STATEMENT_SIZE,
    DATA_API_MAX_SIZE,
)


class TestConstants:
    """Tests for configuration constants."""

    def test_max_statement_size(self):
        assert MAX_STATEMENT_SIZE_BYTES == 16 * 1024 * 1024  # 16 MB

    def test_default_max_size(self):
        assert DEFAULT_MAX_STATEMENT_SIZE < MAX_STATEMENT_SIZE_BYTES

    def test_data_api_size(self):
        assert DATA_API_MAX_SIZE == 100 * 1024  # 100 KB


class TestFrameShiftConfig:
    """Tests for FrameShiftConfig."""

    def test_defaults(self):
        config = FrameShiftConfig()

        assert config.max_statement_bytes == DEFAULT_MAX_STATEMENT_SIZE
        assert config.batch_size == 1000
        assert config.use_transactions is True
        assert config.commit_every == 0
        assert config.on_error == "abort"
        assert config.dry_run is False

    def test_custom_values(self):
        config = FrameShiftConfig(
            max_statement_bytes=5 * 1024 * 1024,
            batch_size=500,
            on_error="skip",
        )

        assert config.max_statement_bytes == 5 * 1024 * 1024
        assert config.batch_size == 500
        assert config.on_error == "skip"

    def test_max_bytes_validation(self):
        # Too large
        with pytest.raises(ValueError, match="16 MB limit"):
            FrameShiftConfig(max_statement_bytes=20 * 1024 * 1024)

        # Too small
        with pytest.raises(ValueError, match="at least 1024"):
            FrameShiftConfig(max_statement_bytes=512)

    def test_batch_size_validation(self):
        with pytest.raises(ValueError, match="at least 1"):
            FrameShiftConfig(batch_size=0)

        with pytest.raises(ValueError):
            FrameShiftConfig(batch_size=-1)

    def test_on_error_validation(self):
        # Valid values
        FrameShiftConfig(on_error="abort")
        FrameShiftConfig(on_error="skip")
        FrameShiftConfig(on_error="log")

        # Invalid value
        with pytest.raises(ValueError, match="on_error"):
            FrameShiftConfig(on_error="invalid")

    def test_varchar_max_length_validation(self):
        with pytest.raises(ValueError, match="varchar_max_length"):
            FrameShiftConfig(varchar_max_length=0)

        with pytest.raises(ValueError, match="varchar_max_length"):
            FrameShiftConfig(varchar_max_length=70000)

    def test_for_data_api(self):
        config = FrameShiftConfig.for_data_api()

        assert config.max_statement_bytes <= DATA_API_MAX_SIZE
        assert config.batch_size < 1000

    def test_for_large_datasets(self):
        config = FrameShiftConfig.for_large_datasets()

        assert config.max_statement_bytes >= 10 * 1024 * 1024
        assert config.batch_size >= 1000
        assert config.commit_every > 0

    def test_for_small_datasets(self):
        config = FrameShiftConfig.for_small_datasets()

        assert config.max_statement_bytes <= 5 * 1024 * 1024
        assert config.batch_size <= 500
        assert config.commit_every == 1

    def test_copy(self):
        original = FrameShiftConfig(batch_size=100)
        copied = original.copy()

        assert copied.batch_size == 100
        assert copied is not original

    def test_copy_with_overrides(self):
        original = FrameShiftConfig(batch_size=100, dry_run=False)
        copied = original.copy(batch_size=500, dry_run=True)

        assert copied.batch_size == 500
        assert copied.dry_run is True
        assert original.batch_size == 100
        assert original.dry_run is False
