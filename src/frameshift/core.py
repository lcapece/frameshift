"""
Core FrameShift class for loading DataFrames into Redshift.

This is the main entry point for the Frameshift library.
"""

from dataclasses import dataclass
from typing import Any, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import logging
import threading
import time

import pandas as pd

from frameshift.config import FrameShiftConfig
from frameshift.connection import (
    ConnectionManager,
    DBConnection,
    create_connection_manager,
)
from frameshift.schema import SchemaInferer, TableSchema
from frameshift.chunker import DataFrameChunker, SQLGenerator, Chunk
from frameshift.analyzer import DistributionAnalyzer, UniqueKeyValidator
from frameshift.types import ColumnSpec, infer_redshift_type
from frameshift.exceptions import (
    FrameShiftError,
    InsertError,
    ValidationError,
)


logger = logging.getLogger(__name__)


@dataclass
class LoadResult:
    """
    Result of a DataFrame load operation.

    Attributes:
        success: Whether the load completed successfully.
        rows_loaded: Total number of rows loaded.
        rows_failed: Number of rows that failed to load.
        chunks_processed: Number of chunks processed.
        chunks_failed: Number of chunks that failed.
        elapsed_seconds: Total time taken.
        rows_per_second: Loading throughput.
        table_name: Target table name.
        created_table: Whether a new table was created.
        errors: List of error messages.
        sql_statements: List of SQL statements (if dry_run=True).
    """

    success: bool
    rows_loaded: int
    rows_failed: int
    chunks_processed: int
    chunks_failed: int
    elapsed_seconds: float
    rows_per_second: float
    table_name: str
    created_table: bool
    errors: list[str]
    sql_statements: list[str] | None = None

    def __repr__(self) -> str:
        status = "SUCCESS" if self.success else "FAILED"
        return (
            f"LoadResult({status}: {self.rows_loaded:,} rows loaded to "
            f"'{self.table_name}' in {self.elapsed_seconds:.2f}s "
            f"({self.rows_per_second:.0f} rows/sec))"
        )

    def summary(self) -> str:
        """Generate detailed summary."""
        lines = [
            f"Load Result: {'SUCCESS' if self.success else 'FAILED'}",
            "=" * 50,
            f"Table:            {self.table_name}",
            f"Rows Loaded:      {self.rows_loaded:,}",
            f"Rows Failed:      {self.rows_failed:,}",
            f"Chunks Processed: {self.chunks_processed}",
            f"Chunks Failed:    {self.chunks_failed}",
            f"Elapsed Time:     {self.elapsed_seconds:.2f} seconds",
            f"Throughput:       {self.rows_per_second:,.0f} rows/second",
            f"Table Created:    {'Yes' if self.created_table else 'No'}",
        ]

        if self.errors:
            lines.extend(["", "Errors:"])
            for error in self.errors[:10]:  # Show first 10 errors
                lines.append(f"  - {error}")
            if len(self.errors) > 10:
                lines.append(f"  ... and {len(self.errors) - 10} more errors")

        return "\n".join(lines)


class FrameShift:
    """
    Load pandas DataFrames into Amazon Redshift without S3.

    FrameShift enables direct DataFrame-to-Redshift loading using
    efficient multi-row INSERT statements. This is ideal for:

    - Ad-hoc data loading and exploration
    - Development and testing environments
    - Situations where S3 access is not available
    - Small to medium datasets (< 1M rows typically)

    **IMPORTANT: This library is NOT recommended for:**

    - Repetitive ETL jobs or production pipelines
    - Very large datasets (use COPY from S3 instead)
    - High-frequency data loading
    - Performance-critical applications

    For production ETL workloads, always prefer the COPY command
    with S3 staging, which offers parallel loading and much higher
    throughput.

    Example:
        >>> import pandas as pd
        >>> from frameshift import FrameShift
        >>>
        >>> # Create connection
        >>> fs = FrameShift(
        ...     host='your-cluster.region.redshift.amazonaws.com',
        ...     database='mydb',
        ...     user='admin',
        ...     password='secret'
        ... )
        >>>
        >>> # Load DataFrame
        >>> df = pd.DataFrame({'id': [1, 2, 3], 'name': ['A', 'B', 'C']})
        >>> result = fs.load(df, 'my_table')
        >>> print(result.summary())
        >>>
        >>> # Analyze distribution before loading
        >>> analysis = fs.analyze_distribution(df, 'id')
        >>> print(analysis.summary())
    """

    def __init__(
        self,
        host: str | None = None,
        database: str | None = None,
        user: str | None = None,
        password: str | None = None,
        port: int = 5439,
        connection: DBConnection | None = None,
        connection_string: str | None = None,
        driver: str = "psycopg2",
        config: FrameShiftConfig | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize FrameShift.

        Connection can be established in several ways:
        1. Direct parameters: host, database, user, password, port
        2. External connection: pass an existing connection object
        3. SQLAlchemy: pass a connection_string

        Args:
            host: Redshift cluster endpoint.
            database: Database name.
            user: Username.
            password: Password.
            port: Port number (default: 5439 for Redshift).
            connection: Existing database connection.
            connection_string: SQLAlchemy connection URL.
            driver: Driver to use ('psycopg2', 'redshift-connector').
            config: FrameShiftConfig instance.
            **kwargs: Additional connection parameters.
        """
        self.config = config or FrameShiftConfig()

        self._connection_manager = create_connection_manager(
            host=host,
            database=database,
            user=user,
            password=password,
            port=port,
            connection=connection,
            connection_string=connection_string,
            driver=driver,
            **kwargs,
        )

        self._schema_inferer = SchemaInferer(
            varchar_max_length=self.config.varchar_max_length
        )
        self._chunker = DataFrameChunker(
            max_bytes=self.config.max_statement_bytes,
            initial_batch_size=self.config.batch_size,
        )
        self._distribution_analyzer = DistributionAnalyzer()
        self._unique_validator = UniqueKeyValidator()

    def load(
        self,
        df: pd.DataFrame,
        table_name: str,
        schema_name: str | None = None,
        if_exists: str = "append",
        distkey: str | None = None,
        sortkey: list[str] | str | None = None,
        primary_key: list[str] | str | None = None,
        unique_key: list[str] | str | None = None,
        validate_unique: bool = False,
        column_specs: list[ColumnSpec] | None = None,
        progress_callback: Callable[[int, int, int], None] | None = None,
    ) -> LoadResult:
        """
        Load a DataFrame into a Redshift table.

        Args:
            df: DataFrame to load.
            table_name: Target table name.
            schema_name: Schema name (default: from config or 'public').
            if_exists: Action if table exists ('append', 'replace', 'fail').
            distkey: Column for distribution key.
            sortkey: Column(s) for sort key.
            primary_key: Column(s) for primary key.
            unique_key: Column(s) for unique constraint.
            validate_unique: Validate unique key before loading.
            column_specs: Override inferred column specifications.
            progress_callback: Called with (rows_done, total_rows, chunk_num).

        Returns:
            LoadResult with operation details.
        """
        start_time = time.time()
        schema_name = schema_name or self.config.schema or "public"

        errors: list[str] = []
        sql_statements: list[str] = []
        created_table = False
        rows_loaded = 0
        chunks_processed = 0
        chunks_failed = 0

        try:
            # Validate unique key if requested
            if validate_unique and unique_key:
                validation = self._unique_validator.validate(df, unique_key)
                if not validation.is_unique:
                    raise ValidationError(
                        f"Unique key validation failed: {validation.duplicate_count} "
                        f"duplicate keys found",
                        field="unique_key",
                    )

            # Infer schema
            table_schema = self._schema_inferer.infer_schema(
                df=df,
                table_name=table_name,
                schema_name=schema_name,
                distkey=distkey,
                sortkey=sortkey,
                primary_key=primary_key,
                unique_key=unique_key,
                preserve_index=self.config.preserve_index,
                auto_suggest_keys=False,  # Use explicit keys only
            )

            # Override column specs if provided
            if column_specs:
                table_schema.columns = column_specs

            # Get connection
            with self._connection_manager.connection() as conn:
                cursor = conn.cursor()

                # Handle table existence
                table_exists = self._table_exists(
                    cursor, table_name, schema_name
                )

                if table_exists:
                    if if_exists == "fail":
                        raise ValidationError(
                            f"Table {schema_name}.{table_name} already exists",
                            field="if_exists",
                        )
                    elif if_exists == "replace":
                        drop_sql = f'DROP TABLE IF EXISTS "{schema_name}"."{table_name}"'
                        if self.config.dry_run:
                            sql_statements.append(drop_sql)
                        else:
                            cursor.execute(drop_sql)
                        table_exists = False

                if not table_exists:
                    create_sql = table_schema.to_create_table_sql()
                    if self.config.dry_run:
                        sql_statements.append(create_sql)
                    else:
                        cursor.execute(create_sql)
                        created_table = True

                # Determine if parallel loading should be used
                total_rows = len(df)
                use_parallel = False
                num_threads = 1

                if not self.config.dry_run:
                    if self.config.parallel_threads == 0:
                        # Auto: use parallel if above threshold
                        if total_rows >= self.config.parallel_threshold:
                            num_threads = min(16, max(2, total_rows // 5000))
                            use_parallel = True
                    elif self.config.parallel_threads > 1:
                        num_threads = self.config.parallel_threads
                        use_parallel = True

                # Close cursor for parallel loading (each thread gets its own)
                if use_parallel:
                    cursor.close()

                    # Determine PK column for MD5 distribution
                    pk_column = None
                    if primary_key:
                        pk_column = primary_key if isinstance(primary_key, str) else primary_key[0]
                    elif unique_key:
                        pk_column = unique_key if isinstance(unique_key, str) else unique_key[0]
                    elif distkey:
                        pk_column = distkey

                    # Run parallel loading
                    (
                        rows_loaded,
                        rows_failed_count,
                        chunks_processed,
                        chunks_failed,
                        parallel_errors,
                    ) = self._load_parallel(
                        df=df,
                        table_name=table_name,
                        schema_name=schema_name,
                        table_schema=table_schema,
                        num_threads=num_threads,
                        pk_column=pk_column,
                        progress_callback=progress_callback,
                    )
                    errors.extend(parallel_errors)

                else:
                    # Single-threaded loading (original behavior)
                    # Begin transaction if configured
                    if self.config.use_transactions:
                        cursor.execute("BEGIN")

                    # Generate SQL and chunk data
                    sql_gen = SQLGenerator(
                        table_name=table_name,
                        schema_name=schema_name,
                        column_specs=table_schema.columns,
                    )

                    insert_prefix = sql_gen.generate_insert_prefix(
                        self.config.include_columns
                    )
                    insert_prefix_size = len(insert_prefix.encode("utf-8"))

                    # Process chunks
                    commit_counter = 0

                    for chunk in self._chunker.chunk(
                        df, table_schema.columns, insert_prefix_size
                    ):
                        try:
                            insert_sql = sql_gen.generate_insert_statement(
                                chunk.data, self.config.include_columns
                            )

                            if self.config.dry_run:
                                sql_statements.append(insert_sql)
                            else:
                                cursor.execute(insert_sql)

                            rows_loaded += chunk.row_count
                            chunks_processed += 1
                            commit_counter += 1

                            # Progress callback
                            if progress_callback:
                                progress_callback(
                                    rows_loaded, total_rows, chunks_processed
                                )

                            # Periodic commit
                            if (
                                self.config.commit_every > 0
                                and commit_counter >= self.config.commit_every
                                and not self.config.dry_run
                            ):
                                conn.commit()
                                cursor.execute("BEGIN")
                                commit_counter = 0

                            # Log progress
                            if self.config.verbosity >= 2:
                                logger.debug(
                                    f"Chunk {chunks_processed}: "
                                    f"{chunk.row_count} rows "
                                    f"({rows_loaded}/{total_rows})"
                                )

                        except Exception as e:
                            chunks_failed += 1
                            error_msg = (
                                f"Chunk {chunk.chunk_index} failed: {e}"
                            )
                            errors.append(error_msg)

                            if self.config.on_error == "abort":
                                raise InsertError(
                                    error_msg,
                                    table=f"{schema_name}.{table_name}",
                                    rows_attempted=chunk.row_count,
                                )
                            elif self.config.on_error == "log":
                                logger.error(error_msg)

                    # Final commit
                    if self.config.use_transactions and not self.config.dry_run:
                        conn.commit()

                    cursor.close()

        except FrameShiftError:
            raise
        except Exception as e:
            errors.append(str(e))
            raise InsertError(
                f"Load failed: {e}",
                table=f"{schema_name}.{table_name}",
                rows_inserted=rows_loaded,
            )

        elapsed = time.time() - start_time
        rows_per_sec = rows_loaded / elapsed if elapsed > 0 else 0

        return LoadResult(
            success=chunks_failed == 0,
            rows_loaded=rows_loaded,
            rows_failed=len(df) - rows_loaded,
            chunks_processed=chunks_processed,
            chunks_failed=chunks_failed,
            elapsed_seconds=elapsed,
            rows_per_second=rows_per_sec,
            table_name=f"{schema_name}.{table_name}",
            created_table=created_table,
            errors=errors,
            sql_statements=sql_statements if self.config.dry_run else None,
        )

    def _table_exists(
        self, cursor: Any, table_name: str, schema_name: str
    ) -> bool:
        """Check if a table exists."""
        query = """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = %s AND table_name = %s
        """
        cursor.execute(query, (schema_name, table_name))
        return cursor.fetchone() is not None

    def _distribute_by_md5(
        self,
        df: pd.DataFrame,
        num_threads: int,
        pk_column: str | None = None,
    ) -> list[pd.DataFrame]:
        """
        Distribute DataFrame rows across threads using MD5 hash.

        Uses the first hex character of MD5(pk) to assign rows to threads.
        This mirrors Redshift's hash distribution for even data spread.

        Args:
            df: DataFrame to distribute.
            num_threads: Number of threads (1-16).
            pk_column: Primary key column (uses index if None).

        Returns:
            List of DataFrames, one per thread.
        """
        if num_threads == 1:
            return [df]

        # Map hex chars to thread IDs (0-15 for 16 threads)
        hex_chars = '0123456789abcdef'
        chars_per_thread = 16 // num_threads

        # Compute MD5 hash for each row
        if pk_column and pk_column in df.columns:
            hash_values = df[pk_column].astype(str).apply(
                lambda x: hashlib.md5(x.encode()).hexdigest()[0]
            )
        else:
            # Use row index
            hash_values = pd.Series(range(len(df))).apply(
                lambda x: hashlib.md5(str(x).encode()).hexdigest()[0]
            )

        # Assign thread based on first hex char
        thread_assignments = hash_values.apply(
            lambda h: hex_chars.index(h) // chars_per_thread
        )

        # Split into DataFrames per thread
        thread_dfs = []
        for thread_id in range(num_threads):
            mask = thread_assignments == thread_id
            thread_df = df[mask].copy()
            thread_dfs.append(thread_df)

        return thread_dfs

    def _load_thread_worker(
        self,
        thread_id: int,
        df: pd.DataFrame,
        table_name: str,
        schema_name: str,
        table_schema: Any,
        progress_state: dict,
        progress_lock: threading.Lock,
        progress_callback: Callable | None,
    ) -> dict:
        """
        Worker function for parallel loading.

        Each thread gets its own connection and processes its chunk of data.
        """
        result = {
            'thread_id': thread_id,
            'rows_loaded': 0,
            'chunks_processed': 0,
            'chunks_failed': 0,
            'errors': [],
        }

        if df.empty:
            return result

        try:
            # Each thread gets its own connection
            with self._connection_manager.connection() as conn:
                cursor = conn.cursor()

                try:
                    sql_gen = SQLGenerator(
                        table_name=table_name,
                        schema_name=schema_name,
                        column_specs=table_schema.columns,
                    )

                    insert_prefix = sql_gen.generate_insert_prefix(
                        self.config.include_columns
                    )
                    insert_prefix_size = len(insert_prefix.encode("utf-8"))

                    # Process chunks for this thread's data
                    for chunk in self._chunker.chunk(
                        df, table_schema.columns, insert_prefix_size
                    ):
                        try:
                            insert_sql = sql_gen.generate_insert_statement(
                                chunk.data, self.config.include_columns
                            )
                            cursor.execute(insert_sql)
                            conn.commit()  # Commit each chunk for parallel safety

                            result['rows_loaded'] += chunk.row_count
                            result['chunks_processed'] += 1

                            # Update shared progress
                            if progress_callback:
                                with progress_lock:
                                    progress_state['rows_done'] += chunk.row_count
                                    progress_state['chunks_done'] += 1
                                    progress_callback(
                                        progress_state['rows_done'],
                                        progress_state['total_rows'],
                                        progress_state['chunks_done'],
                                    )

                        except Exception as e:
                            result['chunks_failed'] += 1
                            result['errors'].append(
                                f"Thread {thread_id}, Chunk {chunk.chunk_index}: {e}"
                            )
                            if self.config.on_error == 'abort':
                                raise

                finally:
                    cursor.close()

        except Exception as e:
            result['errors'].append(f"Thread {thread_id} failed: {e}")

        return result

    def _load_parallel(
        self,
        df: pd.DataFrame,
        table_name: str,
        schema_name: str,
        table_schema: Any,
        num_threads: int,
        pk_column: str | None,
        progress_callback: Callable | None,
    ) -> tuple[int, int, int, int, list[str]]:
        """
        Load data using multiple parallel threads with MD5 distribution.

        Returns:
            Tuple of (rows_loaded, rows_failed, chunks_processed, chunks_failed, errors)
        """
        # Distribute data across threads using MD5
        thread_dfs = self._distribute_by_md5(df, num_threads, pk_column)

        if self.config.verbosity >= 1:
            distribution = [len(tdf) for tdf in thread_dfs]
            logger.info(
                f"Parallel load: {num_threads} threads, "
                f"distribution: {distribution}"
            )

        # Shared progress state
        progress_lock = threading.Lock()
        progress_state = {
            'rows_done': 0,
            'chunks_done': 0,
            'total_rows': len(df),
        }

        # Execute threads
        rows_loaded = 0
        chunks_processed = 0
        chunks_failed = 0
        errors = []

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = {
                executor.submit(
                    self._load_thread_worker,
                    thread_id,
                    thread_dfs[thread_id],
                    table_name,
                    schema_name,
                    table_schema,
                    progress_state,
                    progress_lock,
                    progress_callback,
                ): thread_id
                for thread_id in range(num_threads)
            }

            for future in as_completed(futures):
                thread_id = futures[future]
                try:
                    result = future.result()
                    rows_loaded += result['rows_loaded']
                    chunks_processed += result['chunks_processed']
                    chunks_failed += result['chunks_failed']
                    errors.extend(result['errors'])
                except Exception as e:
                    errors.append(f"Thread {thread_id} exception: {e}")
                    chunks_failed += 1

        rows_failed = len(df) - rows_loaded
        return rows_loaded, rows_failed, chunks_processed, chunks_failed, errors

    def generate_sql(
        self,
        df: pd.DataFrame,
        table_name: str,
        schema_name: str | None = None,
        distkey: str | None = None,
        sortkey: list[str] | str | None = None,
        include_create: bool = True,
    ) -> list[str]:
        """
        Generate SQL statements without executing.

        Useful for previewing what will be executed or for
        generating SQL to run manually.

        Args:
            df: DataFrame to convert.
            table_name: Target table name.
            schema_name: Schema name.
            distkey: Distribution key column.
            sortkey: Sort key column(s).
            include_create: Include CREATE TABLE statement.

        Returns:
            List of SQL statements.
        """
        schema_name = schema_name or self.config.schema or "public"

        # Use dry_run mode
        config = self.config.copy(dry_run=True)
        original_config = self.config
        self.config = config

        try:
            result = self.load(
                df=df,
                table_name=table_name,
                schema_name=schema_name,
                if_exists="append",
                distkey=distkey,
                sortkey=sortkey,
            )

            statements = result.sql_statements or []

            if not include_create and statements:
                # Remove CREATE TABLE statement
                statements = [
                    s for s in statements
                    if not s.strip().upper().startswith("CREATE")
                ]

            return statements

        finally:
            self.config = original_config

    def infer_schema(
        self,
        df: pd.DataFrame,
        table_name: str,
        schema_name: str | None = None,
        distkey: str | None = None,
        sortkey: list[str] | str | None = None,
        auto_suggest_keys: bool = True,
    ) -> TableSchema:
        """
        Infer optimal Redshift schema from DataFrame.

        Args:
            df: DataFrame to analyze.
            table_name: Target table name.
            schema_name: Schema name.
            distkey: Override distribution key.
            sortkey: Override sort key.
            auto_suggest_keys: Auto-suggest DISTKEY/SORTKEY.

        Returns:
            TableSchema with inferred types and keys.
        """
        return self._schema_inferer.infer_schema(
            df=df,
            table_name=table_name,
            schema_name=schema_name or self.config.schema or "public",
            distkey=distkey,
            sortkey=sortkey,
            auto_suggest_keys=auto_suggest_keys,
        )

    def analyze_distribution(
        self,
        df: pd.DataFrame,
        column: str,
        slice_count: int = 16,
    ):
        """
        Analyze distribution characteristics of a column.

        Use this to predict data skew before choosing a DISTKEY.
        Uses MD5 hashing to simulate Redshift's distribution.

        Args:
            df: DataFrame to analyze.
            column: Column to analyze.
            slice_count: Number of slices to simulate.

        Returns:
            DistributionAnalysis with detailed metrics.
        """
        analyzer = DistributionAnalyzer(slice_count=slice_count)
        return analyzer.analyze(df, column)

    def compare_distkeys(
        self,
        df: pd.DataFrame,
        columns: list[str],
        slice_count: int = 16,
    ) -> pd.DataFrame:
        """
        Compare multiple columns as DISTKEY candidates.

        Args:
            df: DataFrame to analyze.
            columns: Columns to compare.
            slice_count: Number of slices to simulate.

        Returns:
            DataFrame with comparison metrics.
        """
        analyzer = DistributionAnalyzer(slice_count=slice_count)
        return analyzer.compare_columns(df, columns)

    def validate_unique_key(
        self,
        df: pd.DataFrame,
        columns: list[str] | str,
    ):
        """
        Validate that columns form a unique key.

        Args:
            df: DataFrame to validate.
            columns: Column(s) to check.

        Returns:
            UniqueKeyValidation with results.
        """
        return self._unique_validator.validate(df, columns)

    def find_natural_keys(
        self,
        df: pd.DataFrame,
        max_columns: int = 3,
    ) -> list[tuple[list[str], int]]:
        """
        Find potential natural keys in DataFrame.

        Args:
            df: DataFrame to analyze.
            max_columns: Maximum columns in composite key.

        Returns:
            List of (column_combination, unique_count) tuples.
        """
        return self._unique_validator.find_natural_keys(df, max_columns)

    def estimate_load(
        self,
        df: pd.DataFrame,
        table_name: str | None = None,
    ) -> dict[str, Any]:
        """
        Estimate loading statistics without loading.

        Args:
            df: DataFrame to analyze.
            table_name: Optional table name for schema inference.

        Returns:
            Dictionary with estimates.
        """
        # Infer column specs
        columns = []
        for col in df.columns:
            col_spec = infer_redshift_type(df[col], self.config.varchar_max_length)
            col_spec.name = str(col)
            columns.append(col_spec)

        # Estimate chunking
        estimates = self._chunker.estimate_chunks(df, columns)

        # Add recommendations
        estimates["recommendations"] = []

        if len(df) > 100000:
            estimates["recommendations"].append(
                "Consider using COPY from S3 for better performance with "
                f"{len(df):,} rows."
            )

        if estimates["estimated_chunks"] > 100:
            estimates["recommendations"].append(
                f"Large number of chunks ({estimates['estimated_chunks']}). "
                "This may take a while. Consider loading in batches."
            )

        return estimates

    def get_recommendations(
        self,
        df: pd.DataFrame,
        table_name: str,
    ) -> dict[str, Any]:
        """
        Get comprehensive recommendations for loading.

        Args:
            df: DataFrame to analyze.
            table_name: Target table name.

        Returns:
            Dictionary with schema and loading recommendations.
        """
        return self._schema_inferer.generate_recommendations(df, table_name)

    def close(self) -> None:
        """Close the connection."""
        self._connection_manager.close()

    def __enter__(self) -> "FrameShift":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        self.close()
