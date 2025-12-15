"""
Distribution analysis example for Frameshift.

This example demonstrates how to:
- Analyze potential DISTKEY columns
- Predict data skew using MD5 hash simulation
- Compare multiple columns
- Make informed DISTKEY decisions
"""

import pandas as pd
import numpy as np
from frameshift import FrameShift, DistributionAnalyzer


def main():
    # Create sample data with different distribution characteristics
    np.random.seed(42)
    n_rows = 10000

    df = pd.DataFrame({
        # High cardinality - good DISTKEY candidate
        'user_id': range(1, n_rows + 1),

        # Medium cardinality
        'region': np.random.choice(['US', 'EU', 'APAC', 'LATAM'], n_rows),

        # Low cardinality - poor DISTKEY candidate
        'status': np.random.choice(['active', 'inactive'], n_rows, p=[0.8, 0.2]),

        # Skewed distribution - problematic
        'account_type': np.random.choice(
            ['free', 'basic', 'premium', 'enterprise'],
            n_rows,
            p=[0.7, 0.2, 0.08, 0.02]  # Very skewed
        ),

        # With NULLs
        'referrer_id': [
            i if np.random.random() > 0.3 else None
            for i in range(1, n_rows + 1)
        ],
    })

    print("Sample Data:")
    print(df.head(10))
    print(f"\nTotal rows: {len(df)}")

    # Create analyzer with 16 slices (typical for mid-size cluster)
    analyzer = DistributionAnalyzer(slice_count=16)

    # Analyze each column
    columns_to_analyze = ['user_id', 'region', 'status', 'account_type', 'referrer_id']

    print("\n" + "=" * 60)
    print("DISTRIBUTION ANALYSIS")
    print("=" * 60)

    for col in columns_to_analyze:
        print(f"\n{'-' * 60}")
        analysis = analyzer.analyze(df, col)
        print(analysis.summary())

    # Compare all columns side by side
    print("\n" + "=" * 60)
    print("COMPARISON TABLE")
    print("=" * 60)

    comparison = analyzer.compare_columns(df, columns_to_analyze)
    print(comparison.to_string(index=False))

    # Using FrameShift's built-in methods
    print("\n" + "=" * 60)
    print("USING FRAMESHIFT API")
    print("=" * 60)

    # Create FrameShift instance (connection not needed for analysis)
    # Using a mock connection for demonstration
    from unittest.mock import MagicMock
    mock_conn = MagicMock()

    fs = FrameShift(connection=mock_conn)

    # Analyze single column
    print("\nAnalyzing 'user_id':")
    analysis = fs.analyze_distribution(df, 'user_id', slice_count=16)
    print(f"  Is good DISTKEY: {analysis.is_good_distkey()}")
    print(f"  Skew ratio: {analysis.skew_ratio:.2f}x")
    print(f"  Cardinality: {analysis.cardinality_ratio:.1%}")

    # Compare multiple
    print("\nComparing columns:")
    comparison = fs.compare_distkeys(df, columns_to_analyze)
    best_column = comparison.iloc[0]['column']
    print(f"  Best DISTKEY candidate: {best_column}")

    # Get full recommendations
    print("\n" + "=" * 60)
    print("FULL RECOMMENDATIONS")
    print("=" * 60)

    recs = fs.get_recommendations(df, 'user_events')
    print(f"\nTable: {recs['table_name']}")
    print(f"Rows: {recs['row_count']:,}")
    print(f"Estimated size: {recs['estimated_size_mb']:.2f} MB")
    print(f"\nDISTKEY recommendation:")
    print(f"  Column: {recs['distkey']['column']}")
    print(f"  Reason: {recs['distkey']['reason']}")
    print(f"\nSORTKEY recommendation:")
    print(f"  Columns: {recs['sortkey']['columns']}")
    print(f"  Reason: {recs['sortkey']['reason']}")

    print("\n" + "=" * 60)
    print("DECISION GUIDE")
    print("=" * 60)
    print("""
    DISTKEY Selection Guidelines:

    1. GOOD candidates (skew ratio < 1.5):
       - High cardinality (many unique values)
       - Even distribution across values
       - Frequently used in JOIN conditions

    2. ACCEPTABLE candidates (skew ratio 1.5-2.0):
       - Medium cardinality
       - Slightly uneven distribution
       - Use if better options unavailable

    3. POOR candidates (skew ratio > 2.0):
       - Low cardinality (few unique values)
       - Highly skewed distribution
       - Will cause hot spots on certain slices

    For this dataset:
    - 'user_id' is EXCELLENT: unique per row, perfect distribution
    - 'region' is POOR: only 4 values for 16 slices
    - 'status' is POOR: only 2 values, very skewed
    - 'account_type' is POOR: 4 values with skewed distribution
    - 'referrer_id' has too many NULLs (30%)
    """)


if __name__ == '__main__':
    main()
