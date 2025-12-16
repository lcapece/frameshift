"""
Database connection handling for Frameshift.

This module provides connection management for Redshift,
supporting multiple connection methods (psycopg2, redshift-connector,
SQLAlchemy, or user-provided connections).
"""

from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Any, Iterator, Protocol, runtime_checkable

from frameshift.exceptions import RedshiftConnectionError


@runtime_checkable
class DBConnection(Protocol):
    """Protocol for database connections."""

    def cursor(self) -> Any:
        """Return a cursor object."""
        ...

    def commit(self) -> None:
        """Commit the current transaction."""
        ...

    def rollback(self) -> None:
        """Rollback the current transaction."""
        ...

    def close(self) -> None:
        """Close the connection."""
        ...


@runtime_checkable
class DBCursor(Protocol):
    """Protocol for database cursors."""

    def execute(self, query: str, params: Any = None) -> None:
        """Execute a query."""
        ...

    def fetchone(self) -> Any:
        """Fetch one row."""
        ...

    def fetchall(self) -> list[Any]:
        """Fetch all rows."""
        ...

    def close(self) -> None:
        """Close the cursor."""
        ...

    @property
    def rowcount(self) -> int:
        """Number of affected rows."""
        ...


class ConnectionManager(ABC):
    """
    Abstract base class for connection management.

    Subclasses implement specific connection strategies
    (direct connection, connection pool, external connection, etc.).
    """

    @abstractmethod
    def get_connection(self) -> DBConnection:
        """Get a database connection."""
        ...

    @abstractmethod
    def release_connection(self, conn: DBConnection) -> None:
        """Release a connection back to the pool or close it."""
        ...

    @contextmanager
    def connection(self) -> Iterator[DBConnection]:
        """Context manager for connection handling."""
        conn = self.get_connection()
        try:
            yield conn
        finally:
            self.release_connection(conn)

    @contextmanager
    def cursor(self) -> Iterator[DBCursor]:
        """Context manager for cursor handling."""
        with self.connection() as conn:
            cur = conn.cursor()
            try:
                yield cur
            finally:
                cur.close()


class Psycopg2ConnectionManager(ConnectionManager):
    """
    Connection manager using psycopg2.

    psycopg2 is the most common PostgreSQL adapter and works
    well with Redshift due to its PostgreSQL compatibility.
    """

    def __init__(
        self,
        host: str,
        database: str,
        user: str,
        password: str,
        port: int = 5439,
        **kwargs: Any,
    ) -> None:
        """
        Initialize psycopg2 connection manager.

        Args:
            host: Redshift cluster endpoint.
            database: Database name.
            user: Username.
            password: Password.
            port: Port number (default: 5439).
            **kwargs: Additional psycopg2 connection parameters.
        """
        self.connection_params = {
            "host": host,
            "dbname": database,
            "user": user,
            "password": password,
            "port": port,
            **kwargs,
        }
        self._connection: DBConnection | None = None

    def get_connection(self) -> DBConnection:
        """Get or create a psycopg2 connection."""
        if self._connection is not None:
            return self._connection

        try:
            import psycopg2

            self._connection = psycopg2.connect(**self.connection_params)
            return self._connection
        except ImportError:
            raise RedshiftConnectionError(
                "psycopg2 is not installed. Install with: pip install psycopg2-binary",
                host=self.connection_params.get("host"),
            )
        except Exception as e:
            raise RedshiftConnectionError(
                f"Failed to connect to Redshift: {e}",
                host=self.connection_params.get("host"),
                port=self.connection_params.get("port"),
            )

    def release_connection(self, conn: DBConnection) -> None:
        """Keep connection open for reuse."""
        pass  # Don't close, we reuse the connection

    def close(self) -> None:
        """Close the connection."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None


class RedshiftConnectorManager(ConnectionManager):
    """
    Connection manager using amazon-redshift-connector.

    This is Amazon's official Redshift driver with better
    support for Redshift-specific features.
    """

    def __init__(
        self,
        host: str,
        database: str,
        user: str,
        password: str,
        port: int = 5439,
        **kwargs: Any,
    ) -> None:
        """
        Initialize redshift-connector connection manager.

        Args:
            host: Redshift cluster endpoint.
            database: Database name.
            user: Username.
            password: Password.
            port: Port number (default: 5439).
            **kwargs: Additional connection parameters.
        """
        self.connection_params = {
            "host": host,
            "database": database,
            "user": user,
            "password": password,
            "port": port,
            **kwargs,
        }
        self._connection: DBConnection | None = None

    def get_connection(self) -> DBConnection:
        """Get or create a redshift-connector connection."""
        if self._connection is not None:
            return self._connection

        try:
            import redshift_connector

            self._connection = redshift_connector.connect(**self.connection_params)
            return self._connection
        except ImportError:
            raise RedshiftConnectionError(
                "redshift-connector is not installed. "
                "Install with: pip install redshift-connector",
                host=self.connection_params.get("host"),
            )
        except Exception as e:
            raise RedshiftConnectionError(
                f"Failed to connect to Redshift: {e}",
                host=self.connection_params.get("host"),
                port=self.connection_params.get("port"),
            )

    def release_connection(self, conn: DBConnection) -> None:
        """Keep connection open for reuse."""
        pass

    def close(self) -> None:
        """Close the connection."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None


class ExternalConnectionManager(ConnectionManager):
    """
    Connection manager for user-provided connections.

    Use this when you want to manage the connection lifecycle
    yourself or integrate with an existing connection pool.
    """

    def __init__(self, connection: DBConnection) -> None:
        """
        Initialize with an external connection.

        Args:
            connection: A database connection object.
        """
        if not isinstance(connection, DBConnection):
            raise RedshiftConnectionError(
                "Provided connection does not implement required interface. "
                "Connection must have cursor(), commit(), rollback(), and close() methods."
            )
        self._connection = connection

    def get_connection(self) -> DBConnection:
        """Return the external connection."""
        return self._connection

    def release_connection(self, conn: DBConnection) -> None:
        """Do nothing - external connection is managed externally."""
        pass

    def close(self) -> None:
        """Do nothing - external connection is managed externally."""
        pass


class SQLAlchemyConnectionManager(ConnectionManager):
    """
    Connection manager using SQLAlchemy.

    Useful when integrating with SQLAlchemy-based applications
    or when you need connection pooling.
    """

    def __init__(
        self,
        connection_string: str | None = None,
        engine: Any = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize SQLAlchemy connection manager.

        Args:
            connection_string: SQLAlchemy connection URL.
            engine: Existing SQLAlchemy engine.
            **kwargs: Additional engine creation parameters.
        """
        if engine is not None:
            self._engine = engine
        elif connection_string:
            try:
                from sqlalchemy import create_engine

                self._engine = create_engine(connection_string, **kwargs)
            except ImportError:
                raise RedshiftConnectionError(
                    "SQLAlchemy is not installed. "
                    "Install with: pip install sqlalchemy sqlalchemy-redshift"
                )
        else:
            raise RedshiftConnectionError(
                "Either connection_string or engine must be provided"
            )

        self._connection: Any = None

    def get_connection(self) -> DBConnection:
        """Get a connection from the engine."""
        if self._connection is None:
            self._connection = self._engine.connect()
        return self._connection

    def release_connection(self, conn: DBConnection) -> None:
        """Keep connection open for reuse."""
        pass

    def close(self) -> None:
        """Close the connection."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None


def create_connection_manager(
    host: str | None = None,
    database: str | None = None,
    user: str | None = None,
    password: str | None = None,
    port: int = 5439,
    connection: DBConnection | None = None,
    connection_string: str | None = None,
    driver: str = "psycopg2",
    **kwargs: Any,
) -> ConnectionManager:
    """
    Factory function to create appropriate connection manager.

    Args:
        host: Redshift cluster endpoint.
        database: Database name.
        user: Username.
        password: Password.
        port: Port number (default: 5439).
        connection: Existing connection object.
        connection_string: SQLAlchemy connection URL.
        driver: Driver to use ('psycopg2', 'redshift-connector', 'sqlalchemy').
        **kwargs: Additional connection parameters.

    Returns:
        Appropriate ConnectionManager instance.
    """
    # External connection takes precedence
    if connection is not None:
        return ExternalConnectionManager(connection)

    # SQLAlchemy connection string
    if connection_string is not None:
        return SQLAlchemyConnectionManager(connection_string=connection_string, **kwargs)

    # Direct connection parameters
    if not all([host, database, user, password]):
        raise RedshiftConnectionError(
            "Must provide either: (1) host, database, user, password, "
            "(2) an existing connection, or (3) a SQLAlchemy connection_string"
        )

    if driver == "redshift-connector":
        return RedshiftConnectorManager(
            host=host,
            database=database,
            user=user,
            password=password,
            port=port,
            **kwargs,
        )
    elif driver == "sqlalchemy":
        conn_str = (
            f"redshift+psycopg2://{user}:{password}@{host}:{port}/{database}"
        )
        return SQLAlchemyConnectionManager(connection_string=conn_str, **kwargs)
    else:  # Default to psycopg2
        return Psycopg2ConnectionManager(
            host=host,
            database=database,
            user=user,
            password=password,
            port=port,
            **kwargs,
        )
