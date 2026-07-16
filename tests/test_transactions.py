"""
Tests for transaction handling during a load.

These use a fake cursor that records every statement and can be told to
fail on specific ones. A MagicMock accepts any SQL without complaint, which
makes it useless for asserting that Frameshift rolls back, uses savepoints,
or leaves the connection clean -- the behavior that decides whether a failed
load costs you a connection or a table.
"""

import pandas as pd
import pytest

from frameshift import FrameShift, FrameShiftConfig
from frameshift.exceptions import InsertError, ValidationError


class FakeCursor:
    """A cursor that records statements and can fail on cue."""

    def __init__(self, connection, fail_on=None, table_exists=False):
        self.connection = connection
        self.fail_on = fail_on or (lambda sql: False)
        self.table_exists = table_exists
        self.closed = False

    def execute(self, query, params=None):
        self.connection.statements.append(query)
        if self.fail_on(query):
            raise RuntimeError("simulated server error")

    def fetchone(self):
        return (1,) if self.table_exists else None

    def fetchall(self):
        return []

    def close(self):
        self.closed = True

    @property
    def rowcount(self):
        return 0


class FakeConnection:
    """A connection that records commits, rollbacks, and statements."""

    def __init__(self, fail_on=None, table_exists=False):
        self.statements: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.cursors: list[FakeCursor] = []
        self._fail_on = fail_on
        self._table_exists = table_exists

    def cursor(self):
        cur = FakeCursor(
            self, fail_on=self._fail_on, table_exists=self._table_exists
        )
        self.cursors.append(cur)
        return cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass

    def inserts(self):
        return [s for s in self.statements if s.lstrip().upper().startswith("INSERT")]


@pytest.fixture
def df():
    return pd.DataFrame({"id": [1, 2, 3], "name": ["a", "b", "c"]})


def fail_on_inserts(sql):
    return sql.lstrip().upper().startswith("INSERT")


class TestSuccessfulLoad:
    def test_commits_once(self, df):
        conn = FakeConnection()
        with FrameShift(connection=conn) as fs:
            result = fs.load(df, "t")

        assert result.success
        assert result.rows_loaded == 3
        assert conn.commits == 1
        assert conn.rollbacks == 0

    def test_creates_table_when_absent(self, df):
        conn = FakeConnection(table_exists=False)
        with FrameShift(connection=conn) as fs:
            result = fs.load(df, "t")

        assert result.created_table
        assert any(s.upper().startswith("CREATE") for s in conn.statements)

    def test_replace_drops_then_creates(self, df):
        conn = FakeConnection(table_exists=True)
        with FrameShift(connection=conn) as fs:
            fs.load(df, "t", if_exists="replace")

        upper = [s.strip().upper() for s in conn.statements]
        drop_index = next(i for i, s in enumerate(upper) if s.startswith("DROP"))
        create_index = next(i for i, s in enumerate(upper) if s.startswith("CREATE"))
        assert drop_index < create_index

    def test_fail_when_table_exists(self, df):
        conn = FakeConnection(table_exists=True)
        with FrameShift(connection=conn) as fs:
            with pytest.raises(ValidationError):
                fs.load(df, "t", if_exists="fail")

        assert conn.inserts() == []

    def test_invalid_if_exists_rejected(self, df):
        conn = FakeConnection()
        with FrameShift(connection=conn) as fs:
            with pytest.raises(ValidationError):
                fs.load(df, "t", if_exists="upsert")

    def test_cursor_is_closed(self, df):
        conn = FakeConnection()
        with FrameShift(connection=conn) as fs:
            fs.load(df, "t")

        assert all(c.closed for c in conn.cursors)


class TestFailureHandling:
    def test_abort_rolls_back(self, df):
        """
        A failed load must roll back. Without it the connection is left in a
        failed transaction, and -- because connections are reused, and may be
        the caller's own -- every later statement on it fails too.
        """
        conn = FakeConnection(fail_on=fail_on_inserts)
        with FrameShift(connection=conn) as fs:
            with pytest.raises(InsertError):
                fs.load(df, "t")

        assert conn.rollbacks == 1
        assert conn.commits == 0

    def test_abort_reports_row_range(self, df):
        conn = FakeConnection(fail_on=fail_on_inserts)
        with FrameShift(connection=conn) as fs:
            with pytest.raises(InsertError) as exc_info:
                fs.load(df, "t")

        assert "rows" in str(exc_info.value)

    def test_cursor_closed_on_failure(self, df):
        conn = FakeConnection(fail_on=fail_on_inserts)
        with FrameShift(connection=conn) as fs:
            with pytest.raises(InsertError):
                fs.load(df, "t")

        assert all(c.closed for c in conn.cursors)

    def test_skip_uses_savepoints(self, df):
        """
        on_error='skip' is only meaningful with savepoints. A failed
        statement aborts the whole transaction, so without a savepoint to
        roll back to, every subsequent chunk fails as well -- reporting one
        error per chunk for a single root cause, and loading nothing.
        """
        conn = FakeConnection(fail_on=fail_on_inserts)
        config = FrameShiftConfig(on_error="skip")
        with FrameShift(connection=conn, config=config) as fs:
            result = fs.load(df, "t")

        assert not result.success
        assert result.chunks_failed >= 1
        assert any("SAVEPOINT" in s.upper() for s in conn.statements)
        assert any("ROLLBACK TO SAVEPOINT" in s.upper() for s in conn.statements)

    def test_skip_continues_past_a_bad_chunk(self):
        """A failing chunk must not prevent later chunks from loading."""
        df = pd.DataFrame({"id": [1, 2, 3, 4]})

        def fail_on_second_row(sql):
            return sql.lstrip().upper().startswith("INSERT") and "(2)" in sql

        conn = FakeConnection(fail_on=fail_on_second_row)
        config = FrameShiftConfig(on_error="skip", batch_size=1)
        with FrameShift(connection=conn, config=config) as fs:
            result = fs.load(df, "t")

        assert result.chunks_processed == 3, "expected one row per chunk"
        assert result.chunks_failed == 1
        assert result.rows_loaded == 3
        assert result.rows_failed == 1
        assert not result.success
        # The surviving chunks still commit.
        assert conn.commits == 1

    def test_abort_does_not_use_savepoints(self, df):
        """Savepoints cost a round trip; skip them when aborting anyway."""
        conn = FakeConnection()
        config = FrameShiftConfig(on_error="abort")
        with FrameShift(connection=conn, config=config) as fs:
            fs.load(df, "t")

        assert not any("SAVEPOINT" in s.upper() for s in conn.statements)


class TestDryRun:
    def test_dry_run_touches_no_connection(self, df):
        conn = FakeConnection()
        config = FrameShiftConfig(dry_run=True)
        with FrameShift(connection=conn, config=config) as fs:
            result = fs.load(df, "t")

        assert conn.statements == []
        assert conn.commits == 0
        assert conn.rollbacks == 0
        assert result.sql_statements

    def test_dry_run_reports_created_table(self, df):
        """
        created_table was previously only set on the execute path, so a dry
        run reported False for a load that would in fact create the table.
        """
        conn = FakeConnection()
        config = FrameShiftConfig(dry_run=True)
        with FrameShift(connection=conn, config=config) as fs:
            result = fs.load(df, "t")

        assert result.created_table

    def test_dry_run_counts_rows(self, df):
        conn = FakeConnection()
        config = FrameShiftConfig(dry_run=True)
        with FrameShift(connection=conn, config=config) as fs:
            result = fs.load(df, "t")

        assert result.rows_loaded == 3
        assert result.rows_failed == 0

    def test_generate_sql_does_not_mutate_config(self, df):
        """
        generate_sql used to swap self.config in place, which corrupted a
        concurrent load on the same instance and left dry_run set if it
        raised.
        """
        conn = FakeConnection()
        fs = FrameShift(connection=conn)
        assert fs.config.dry_run is False

        fs.generate_sql(df, "t")

        assert fs.config.dry_run is False
        assert conn.statements == []

    def test_generate_sql_can_omit_ddl(self, df):
        conn = FakeConnection()
        fs = FrameShift(connection=conn)

        statements = fs.generate_sql(df, "t", include_create=False)

        assert statements
        assert not any(s.strip().upper().startswith("CREATE") for s in statements)
        assert all(s.strip().upper().startswith("INSERT") for s in statements)


class TestCommitEvery:
    def test_commits_periodically(self):
        df = pd.DataFrame({"id": list(range(6))})
        conn = FakeConnection()
        config = FrameShiftConfig(commit_every=1, batch_size=1)
        with FrameShift(connection=conn, config=config) as fs:
            result = fs.load(df, "t")

        assert result.chunks_processed == 6
        # One commit per chunk, plus the final commit.
        assert conn.commits == result.chunks_processed + 1
