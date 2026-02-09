"""
Metadata Manager - Tool Functions for Autonomous CSV Analysis
Provides tools for the Metadata Analyst to search and filter CSV data
"""

import pandas as pd
import os
from typing import Dict, Any
from pathlib import Path

# Default CSV file path
CSV_FILE_PATH = Path(__file__).parent / "data" / "data_list.csv"


def get_csv_schema(file_path: str = None) -> str:
    """
    Extract CSV schema (column names and sample rows) without loading entire file.
    
    Args:
        file_path (str): Path to CSV file. Uses default if not specified.
        
    Returns:
        str: Formatted string containing column names and first 3 rows
        
    Purpose:
        Allows Metadata Analyst to explore data structure quickly
    """
    if file_path is None:
        file_path = CSV_FILE_PATH
        
    try:
        # Load only first 4 rows (header + 3 samples)
        df = pd.read_csv(
            file_path,
            nrows=3,
            on_bad_lines='skip',
            engine='python'
        )
        
        schema_info = "## CSV Schema Information\n\n"
        
        # Column information
        schema_info += "### Columns:\n"
        for i, col in enumerate(df.columns, 1):
            schema_info += f"{i}. `{col}`\n"
        
        # Sample data
        schema_info += "\n### Sample Data (first 3 rows):\n"
        schema_info += df.to_markdown(index=False)
        
        return schema_info
        
    except Exception as e:
        return f"❌ Error loading CSV schema: {str(e)}"


def filter_csv(file_path: str = None, column: str = None, value: str = None) -> str:
    """
    Filter CSV rows by column value and return results as Markdown table.
    
    Args:
        file_path (str): Path to CSV file. Uses default if not specified.
        column (str): Column name to filter on
        value (str): Value to search for (substring match)
        
    Returns:
        str: Markdown formatted table of filtered results, or error message
        
    Purpose:
        Allows Metadata Analyst to find relevant rows matching a criteria
        
    Examples:
        filter_csv(column="발주 기관", value="고려대")
        filter_csv(column="사업명", value="시스템")
    """
    if file_path is None:
        file_path = CSV_FILE_PATH
    
    if column is None or value is None:
        return "❌ Error: Both column and value must be specified"
    
    try:
        # Load CSV with error handling
        df = pd.read_csv(
            file_path,
            on_bad_lines='skip',
            engine='python'
        )
        
        # Check if column exists
        if column not in df.columns:
            available_cols = ", ".join(df.columns.tolist())
            return (f"❌ Column '{column}' not found.\n\n"
                   f"Available columns:\n{available_cols}")
        
        # Filter by substring match (case-insensitive)
        filtered_df = df[
            df[column].astype(str).str.contains(value, case=False, na=False)
        ]
        
        # Check if results exist
        if filtered_df.empty:
            return f"❌ No data found matching '{value}' in column '{column}'"
        
        # Convert to Markdown table
        result = f"### Search Results: {value} in {column}\n\n"
        result += f"**Found {len(filtered_df)} matching rows**\n\n"
        result += filtered_df.to_markdown(index=False)
        
        return result
        
    except Exception as e:
        return f"❌ Error filtering CSV: {str(e)}"


def search_csv_by_multiple_filters(
    file_path: str = None, 
    filters: Dict[str, str] = None
) -> str:
    """
    Advanced search with multiple column filters (AND logic).
    
    Args:
        file_path (str): Path to CSV file
        filters (Dict[str, str]): Dictionary of {column: value} pairs
        
    Returns:
        str: Markdown formatted table or error message
        
    Purpose:
        Allows complex queries like: 발주기관='고려대' AND 사업명 contains '시스템'
    """
    if file_path is None:
        file_path = CSV_FILE_PATH
    
    if not filters:
        return "❌ Error: No filters specified"
    
    try:
        df = pd.read_csv(
            file_path,
            on_bad_lines='skip',
            engine='python'
        )
        
        # Apply all filters
        for column, value in filters.items():
            if column not in df.columns:
                return f"❌ Column '{column}' not found"
            
            df = df[df[column].astype(str).str.contains(value, case=False, na=False)]
        
        if df.empty:
            filter_str = " AND ".join([f"{k}='{v}'" for k, v in filters.items()])
            return f"❌ No results found for: {filter_str}"
        
        result = f"### Multi-Filter Search Results\n\n"
        result += f"**Found {len(df)} matching rows**\n\n"
        result += df.to_markdown(index=False)
        
        return result
        
    except Exception as e:
        return f"❌ Error in multi-filter search: {str(e)}"


def get_column_values(file_path: str = None, column: str = None, limit: int = 10) -> str:
    """
    Get unique values from a specific column.
    
    Purpose:
        Helps Analyst understand what values are available in a column
    """
    if file_path is None:
        file_path = CSV_FILE_PATH
    
    if column is None:
        return "❌ Error: Column must be specified"
    
    try:
        df = pd.read_csv(
            file_path,
            on_bad_lines='skip',
            engine='python'
        )
        
        if column not in df.columns:
            return f"❌ Column '{column}' not found"
        
        unique_vals = df[column].dropna().unique()[:limit]
        
        result = f"### Unique Values in '{column}' (first {limit}):\n\n"
        for val in unique_vals:
            result += f"- {val}\n"
        
        return result
        
    except Exception as e:
        return f"❌ Error retrieving column values: {str(e)}"


# ============================================================================
# Tool Registration for LangChain Agent
# ============================================================================

METADATA_TOOLS = [
    {
        "name": "get_csv_schema",
        "description": "Get CSV column structure and sample data first 3 rows",
        "function": get_csv_schema
    },
    {
        "name": "filter_csv",
        "description": "Filter CSV by column value and return markdown table",
        "function": filter_csv
    },
    {
        "name": "search_csv_by_multiple_filters",
        "description": "Search CSV with multiple AND conditions",
        "function": search_csv_by_multiple_filters
    },
    {
        "name": "get_column_values",
        "description": "Get unique values available in a column",
        "function": get_column_values
    }
]


if __name__ == "__main__":
    print("=" * 70)
    print("METADATA MANAGER - CSV TOOL FUNCTIONS")
    print("=" * 70)
    
    # Test get_csv_schema
    print("\n[TEST 1] Get CSV Schema:")
    print(get_csv_schema())
    
    # Test filter_csv
    print("\n[TEST 2] Filter by 발주 기관 = '고려대':")
    print(filter_csv(column="발주 기관", value="고려대"))
    
    # Test get_column_values
    print("\n[TEST 3] Get unique values from '발주 기관':")
    print(get_column_values(column="발주 기관", limit=5))
