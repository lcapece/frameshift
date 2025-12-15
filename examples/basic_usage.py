"""
Basic usage example for Frameshift.

This example demonstrates the fundamental operations:
- Creating a connection
- Loading a DataFrame
- Handling results
"""

import pandas as pd
from frameshift import FrameShift, FrameShiftConfig


def main():
    # Create sample data
    df = pd.DataFrame({
        'user_id': range(1, 101),
        'username': [f'user_{i}' for i in range(1, 101)],
        'email': [f'user{i}@example.com' for i in range(1, 101)],
        'created_at': pd.date_range('2024-01-01', periods=100),
        'is_active': [i % 3 != 0 for i in range(1, 101)],
        'score': [round(50 + i * 0.5, 2) for i in range(1, 101)],
    })

    print("Sample DataFrame:")
    print(df.head())
    print(f"\nShape: {df.shape}")
    print(f"Dtypes:\n{df.dtypes}")

    # Connect to Redshift
    # Replace with your actual connection details
    fs = FrameShift(
        host='your-cluster.region.redshift.amazonaws.com',
        database='your_database',
        user='your_user',
        password='your_password',
        port=5439,
    )

    # Option 1: Basic load (creates table if not exists)
    print("\n--- Loading data ---")
    result = fs.load(
        df,
        table_name='users',
        schema_name='public',
    )
    print(result.summary())

    # Option 2: Load with specific options
    print("\n--- Loading with options ---")
    result = fs.load(
        df,
        table_name='users_optimized',
        distkey='user_id',
        sortkey='created_at',
        if_exists='replace',  # Drop and recreate
    )
    print(result.summary())

    # Option 3: Dry run (generate SQL without executing)
    print("\n--- Dry run (SQL preview) ---")
    config = FrameShiftConfig(dry_run=True)
    fs_dry = FrameShift(
        host='your-cluster.region.redshift.amazonaws.com',
        database='your_database',
        user='your_user',
        password='your_password',
        config=config,
    )

    result = fs_dry.load(df.head(5), 'users_preview')
    if result.sql_statements:
        for stmt in result.sql_statements:
            print(stmt[:500] + '...' if len(stmt) > 500 else stmt)
            print()

    # Clean up
    fs.close()


if __name__ == '__main__':
    main()
