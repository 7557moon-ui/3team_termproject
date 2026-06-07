"""
Merge monthly online shopping transaction amount columns into quarterly columns.

Input example:
  상품군별(1), 상품군별(2), 판매매체별(1), 2025.01, ..., 2025.12

Output:
  상품군별(1), 상품군별(2), 판매매체별(1), 2025_Q1, 2025_Q2, 2025_Q3, 2025_Q4
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


QUARTER_MONTHS = {
    "Q1": ["01", "02", "03"],
    "Q2": ["04", "05", "06"],
    "Q3": ["07", "08", "09"],
    "Q4": ["10", "11", "12"],
}


def read_csv_with_fallback(path: Path) -> pd.DataFrame:
    for encoding in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("csv", b"", 0, 1, f"Could not decode {path}")


def merge_months_to_quarters(df: pd.DataFrame, year: int) -> pd.DataFrame:
    id_columns = [column for column in df.columns if not str(column).startswith(f"{year}.")]
    result = df[id_columns].copy()

    for quarter, months in QUARTER_MONTHS.items():
        month_columns = [f"{year}.{month}" for month in months]
        missing = [column for column in month_columns if column not in df.columns]
        if missing:
            raise ValueError(f"Missing monthly columns for {quarter}: {missing}")

        numeric_months = df[month_columns].apply(
            lambda column: pd.to_numeric(
                column.astype(str).str.replace(",", "", regex=False),
                errors="coerce",
            )
        )
        result[f"{year}_{quarter}"] = numeric_months.sum(axis=1)

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge monthly sales CSV into quarterly CSV.")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(
            r"C:\Users\Windows 10\Downloads\온라인쇼핑몰_판매매체별_상품군별거래액_20260604205702.csv"
        ),
    )
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/온라인쇼핑몰_판매매체별_상품군별거래액_2025_분기별.csv"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    df = read_csv_with_fallback(args.input)
    quarterly_df = merge_months_to_quarters(df, args.year)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    quarterly_df.to_csv(args.output, index=False, encoding="utf-8-sig")

    print(f"Input rows: {len(df):,}")
    print(f"Output rows: {len(quarterly_df):,}")
    print(f"Saved: {args.output}")
    print(quarterly_df.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
