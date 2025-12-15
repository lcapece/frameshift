"""
Unique key validation example for Frameshift.

This example demonstrates how to:
- Validate unique constraints before loading
- Find duplicates in your data
- Discover natural keys
- Handle validation failures gracefully
"""

import pandas as pd
import numpy as np
from frameshift import FrameShift, UniqueKeyValidator


def main():
    # Create sample data with some duplicates
    np.random.seed(42)

    df = pd.DataFrame({
        'order_id': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        'customer_id': [101, 102, 101, 103, 102, 104, 101, 105, 103, 106],
        'order_date': pd.to_datetime([
            '2024-01-01', '2024-01-01', '2024-01-02', '2024-01-02',
            '2024-01-02', '2024-01-03', '2024-01-03', '2024-01-03',
            '2024-01-04', '2024-01-04'
        ]),
        'product_id': ['P001', 'P002', 'P001', 'P003', 'P002', 'P001', 'P002', 'P003', 'P001', 'P002'],
        'quantity': [1, 2, 1, 3, 1, 2, 1, 1, 2, 1],
        'total': [99.99, 149.99, 99.99, 299.99, 149.99, 199.99, 99.99, 79.99, 199.99, 149.99],
    })

    print("Sample Order Data:")
    print(df)

    # Create validator
    validator = UniqueKeyValidator()

    # Test 1: Single column that IS unique
    print("\n" + "=" * 60)
    print("TEST 1: Single Unique Column (order_id)")
    print("=" * 60)

    result = validator.validate(df, 'order_id')
    print(result.summary())

    # Test 2: Single column that is NOT unique
    print("\n" + "=" * 60)
    print("TEST 2: Non-Unique Column (customer_id)")
    print("=" * 60)

    result = validator.validate(df, 'customer_id')
    print(result.summary())

    if result.sample_duplicates is not None:
        print("\nDuplicate Details:")
        print(result.sample_duplicates)

    # Test 3: Composite key that IS unique
    print("\n" + "=" * 60)
    print("TEST 3: Composite Key (customer_id + order_date + product_id)")
    print("=" * 60)

    result = validator.validate(df, ['customer_id', 'order_date', 'product_id'])
    print(result.summary())

    # Test 4: Composite key that is NOT unique
    print("\n" + "=" * 60)
    print("TEST 4: Non-Unique Composite (customer_id + product_id)")
    print("=" * 60)

    # Add a duplicate row for this test
    df_with_dups = pd.concat([
        df,
        pd.DataFrame({
            'order_id': [11],
            'customer_id': [101],
            'order_date': pd.to_datetime(['2024-01-05']),
            'product_id': ['P001'],  # Same customer + product as row 0 and 2
            'quantity': [1],
            'total': [99.99],
        })
    ], ignore_index=True)

    result = validator.validate(df_with_dups, ['customer_id', 'product_id'])
    print(result.summary())

    # Test 5: Find natural keys
    print("\n" + "=" * 60)
    print("TEST 5: Discover Natural Keys")
    print("=" * 60)

    natural_keys = validator.find_natural_keys(df, max_columns=3)

    if natural_keys:
        print("Found natural keys:")
        for columns, unique_count in natural_keys:
            cols_str = " + ".join(columns)
            print(f"  {cols_str}: {unique_count} unique combinations")
    else:
        print("No natural keys found (try increasing max_columns)")

    # Using FrameShift API
    print("\n" + "=" * 60)
    print("USING FRAMESHIFT API")
    print("=" * 60)

    from unittest.mock import MagicMock
    mock_conn = MagicMock()
    fs = FrameShift(connection=mock_conn)

    # Validate before load
    print("\nValidating unique key before load...")
    validation = fs.validate_unique_key(df, 'order_id')
    print(f"Is unique: {validation.is_unique}")
    print(f"Unique combinations: {validation.unique_combinations}")

    # Find natural keys
    print("\nSearching for natural keys...")
    keys = fs.find_natural_keys(df, max_columns=2)
    for cols, count in keys[:3]:  # Top 3
        print(f"  {cols}: {count} unique")

    # Practical workflow: Validate then load
    print("\n" + "=" * 60)
    print("PRACTICAL WORKFLOW")
    print("=" * 60)

    def safe_load(fs, df, table_name, unique_key):
        """Load data with unique key validation."""
        print(f"\nValidating unique key: {unique_key}")

        validation = fs.validate_unique_key(df, unique_key)

        if not validation.is_unique:
            print(f"ERROR: Found {validation.duplicate_count} duplicate keys!")
            print("Sample duplicates:")
            if validation.sample_duplicates is not None:
                print(validation.sample_duplicates)

            # Option 1: Deduplicate
            print("\nOption 1: Deduplicate (keep first)")
            if isinstance(unique_key, list):
                df_deduped = df.drop_duplicates(subset=unique_key, keep='first')
            else:
                df_deduped = df.drop_duplicates(subset=[unique_key], keep='first')
            print(f"Rows after dedup: {len(df_deduped)}")

            # Option 2: Fail
            print("\nOption 2: Abort load")
            return None

        print(f"Validation passed! All {validation.unique_combinations} keys are unique.")
        print("Proceeding with load...")

        # In real usage, this would actually load
        # result = fs.load(df, table_name, unique_key=unique_key)
        return "Success"

    # Test with unique data
    print("\n--- Testing with unique data ---")
    safe_load(fs, df, 'orders', 'order_id')

    # Test with duplicate data
    print("\n--- Testing with duplicate data ---")
    safe_load(fs, df_with_dups, 'orders', ['customer_id', 'product_id'])


if __name__ == '__main__':
    main()
