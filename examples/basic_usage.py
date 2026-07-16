"""
Basic usage.

The dry-run section runs as-is: it renders SQL without a database, so you
can see exactly what Frameshift would send before pointing it at a real
cluster. The loading section needs real credentials and is guarded.
"""

import pandas as pd

from frameshift import FrameShift, FrameShiftConfig

# Set these to run the loading section against a real cluster.
HOST = None
DATABASE = "your_database"
USER = "your_user"
PASSWORD = "your_password"


def build_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "user_id": range(1, 101),
            "username": [f"user_{i}" for i in range(1, 101)],
            "email": [f"user{i}@example.com" for i in range(1, 101)],
            "created_at": pd.date_range("2024-01-01", periods=100),
            "is_active": [i % 3 != 0 for i in range(1, 101)],
            "score": [round(50 + i * 0.5, 2) for i in range(1, 101)],
        }
    )


def preview_sql(df: pd.DataFrame) -> None:
    """Render the SQL a load would execute, without a database."""
    print("--- Dry run: the SQL Frameshift would send ---\n")

    # dry_run never opens a connection, so the parameters below are unused.
    config = FrameShiftConfig(dry_run=True)
    fs = FrameShift(
        host="unused-in-dry-run",
        database="unused",
        user="unused",
        password="unused",
        config=config,
    )

    result = fs.load(df.head(5), "users_preview", distkey="user_id")

    for statement in result.sql_statements or []:
        print(statement[:500] + "..." if len(statement) > 500 else statement)
        print()


def estimate(df: pd.DataFrame) -> None:
    """Ask what a load would cost before committing to it."""
    print("--- Estimate ---\n")

    config = FrameShiftConfig(dry_run=True)
    fs = FrameShift(
        host="unused-in-dry-run",
        database="unused",
        user="unused",
        password="unused",
        config=config,
    )

    estimates = fs.estimate_load(df, "users")
    print(f"Rows:              {estimates['total_rows']:,}")
    print(f"INSERT statements: {estimates['estimated_chunks']}")
    print(f"Avg row size:      {estimates['avg_row_size_bytes']} bytes")
    for note in estimates["recommendations"]:
        print(f"  note: {note}")
    print()


def load_for_real(df: pd.DataFrame) -> None:
    """Load into an actual cluster. Requires HOST to be set."""
    print("--- Loading ---\n")

    with FrameShift(
        host=HOST,
        database=DATABASE,
        user=USER,
        password=PASSWORD,
        port=5439,
    ) as fs:
        result = fs.load(df, table_name="users", schema_name="public")
        print(result.summary())

        result = fs.load(
            df,
            table_name="users_optimized",
            distkey="user_id",
            sortkey="created_at",
            if_exists="replace",
        )
        print(result.summary())


def main() -> None:
    df = build_dataframe()

    print("Sample DataFrame:")
    print(df.head())
    print(f"\nShape: {df.shape}\n")

    estimate(df)
    preview_sql(df)

    if HOST:
        load_for_real(df)
    else:
        print("--- Loading ---\n")
        print("Set HOST at the top of this file to load into a real cluster.")


if __name__ == "__main__":
    main()
