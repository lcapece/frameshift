"""
Schema inference example for Frameshift.

This example demonstrates how to:
- Infer Redshift schema from DataFrames
- Customize DISTKEY and SORTKEY
- Generate CREATE TABLE statements
- Handle various data types
"""

import pandas as pd
import numpy as np
from datetime import datetime, date
from frameshift import FrameShift, SchemaInferer, TableSchema
from frameshift.types import RedshiftType, ColumnSpec


def main():
    # Create sample data with various types
    df = pd.DataFrame({
        # Integer types
        'id': pd.array([1, 2, 3, 4, 5], dtype='Int64'),
        'small_int': pd.array([1, 2, 3, 4, 5], dtype='Int16'),

        # Float types
        'price': [19.99, 29.99, 39.99, 49.99, 59.99],
        'discount': np.array([0.1, 0.15, 0.2, 0.25, 0.3], dtype='float32'),

        # String types
        'name': ['Product A', 'Product B', 'Product C', 'Product D', 'Product E'],
        'description': [
            'A short description',
            'A medium length description for this product',
            'A very long description ' * 10,
            None,  # NULL value
            'Another description',
        ],

        # Boolean
        'is_active': [True, False, True, True, False],

        # Date/Time types
        'created_at': pd.date_range('2024-01-01', periods=5),
        'updated_at': pd.date_range('2024-06-01', periods=5, tz='UTC'),

        # Category
        'category': pd.Categorical(['Electronics', 'Books', 'Electronics', 'Clothing', 'Books']),
    })

    print("Sample DataFrame:")
    print(df)
    print(f"\nDtypes:\n{df.dtypes}")

    # Method 1: Use SchemaInferer directly
    print("\n" + "=" * 60)
    print("METHOD 1: SchemaInferer")
    print("=" * 60)

    inferer = SchemaInferer(varchar_max_length=65535)

    # Basic inference
    schema = inferer.infer_schema(df, 'products')
    print("\nInferred Schema:")
    for col in schema.columns:
        print(f"  {col.name}: {col.redshift_type.value}" +
              (f"({col.length})" if col.length else "") +
              (" NOT NULL" if not col.nullable else ""))

    # With auto-suggested keys
    schema = inferer.infer_schema(
        df, 'products',
        auto_suggest_keys=True
    )
    print(f"\nAuto-suggested DISTKEY: {schema.distkey}")
    print(f"Auto-suggested SORTKEY: {schema.sortkey}")

    # With explicit keys
    schema = inferer.infer_schema(
        df, 'products',
        distkey='id',
        sortkey=['created_at', 'category'],
        primary_key='id',
        unique_key=['name'],
    )

    print("\n" + "-" * 40)
    print("CREATE TABLE SQL:")
    print("-" * 40)
    print(schema.to_create_table_sql())

    # Method 2: Use FrameShift API
    print("\n" + "=" * 60)
    print("METHOD 2: FrameShift API")
    print("=" * 60)

    from unittest.mock import MagicMock
    mock_conn = MagicMock()
    fs = FrameShift(connection=mock_conn)

    schema = fs.infer_schema(
        df, 'products',
        distkey='id',
        sortkey='created_at',
    )
    print("\nInferred schema via FrameShift:")
    print(schema.to_create_table_sql())

    # Get full recommendations
    print("\n" + "-" * 40)
    print("FULL RECOMMENDATIONS:")
    print("-" * 40)

    recs = fs.get_recommendations(df, 'products')

    print(f"\nColumn Analysis:")
    for col_info in recs['columns']:
        print(f"  {col_info['name']}:")
        print(f"    pandas dtype: {col_info['pandas_dtype']}")
        print(f"    Redshift type: {col_info['redshift_type']}")
        print(f"    Nullable: {col_info['nullable']}")
        print(f"    Unique values: {col_info['unique_count']}")

    # Method 3: Manual column specification
    print("\n" + "=" * 60)
    print("METHOD 3: Manual Column Specs")
    print("=" * 60)

    manual_columns = [
        ColumnSpec('id', RedshiftType.INTEGER, nullable=False, is_distkey=True),
        ColumnSpec('name', RedshiftType.VARCHAR, length=100, is_unique=True),
        ColumnSpec('price', RedshiftType.DECIMAL, precision=10, scale=2),
        ColumnSpec('created_at', RedshiftType.TIMESTAMP, is_sortkey=True),
        ColumnSpec('description', RedshiftType.VARCHAR, length=4096, encode='lzo'),
    ]

    manual_schema = TableSchema(
        table_name='products_manual',
        schema_name='analytics',
        columns=manual_columns,
        distkey='id',
        sortkey=['created_at'],
        primary_key=['id'],
        unique_keys=[['name']],
    )

    print("\nManual Schema SQL:")
    print(manual_schema.to_create_table_sql())

    # Generate INSERT statement prefix
    print("\n" + "-" * 40)
    print("INSERT Statement Prefix:")
    print("-" * 40)
    print(manual_schema.to_insert_sql())

    # Advanced: Temporary table
    print("\n" + "=" * 60)
    print("TEMPORARY TABLE")
    print("=" * 60)

    temp_schema = TableSchema(
        table_name='temp_products',
        columns=manual_columns[:3],
        temporary=True,
        if_not_exists=False,
    )
    print(temp_schema.to_create_table_sql())


if __name__ == '__main__':
    main()
