"""
Create 2025 device/gender/age share files for every Naver Shopping 3rd-depth category.

The Naver Shopping Insight breakdown endpoints return relative ratios, not raw
click counts. For each category and dimension, this script converts those ratios
into shares by normalizing the yearly sum of each segment's ratio:

  segment_share_percent = segment_yearly_ratio_sum / all_segments_yearly_ratio_sum * 100

This is the most direct share calculation possible from the public API response.

Expected input:
  outputs/naver_shopping_3depth_categories_2025.csv from the previous script.

Environment variables:
  NAVER_CLIENT_ID_1 / NAVER_CLIENT_SECRET_1
  NAVER_CLIENT_ID_2 / NAVER_CLIENT_SECRET_2
  NAVER_CLIENT_ID_3 / NAVER_CLIENT_SECRET_3
  NAVER_CLIENT_ID_4 / NAVER_CLIENT_SECRET_4
  NAVER_CLIENT_ID_5 / NAVER_CLIENT_SECRET_5
  NAVER_CLIENT_ID_6 / NAVER_CLIENT_SECRET_6

You can also pass a CSV/XLSX credential file with client_id/client_secret columns.
"""

from __future__ import annotations

import argparse
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import requests


API_URLS = {
    "device": "https://openapi.naver.com/v1/datalab/shopping/category/device",
    "gender": "https://openapi.naver.com/v1/datalab/shopping/category/gender",
    "age": "https://openapi.naver.com/v1/datalab/shopping/category/age",
}

EXPECTED_GROUPS = {
    "device": ["pc", "mo"],
    "gender": ["f", "m"],
    "age": ["10", "20", "30", "40", "50", "60"],
}

GROUP_LABELS = {
    "pc": "PC",
    "mo": "Mobile",
    "f": "Female",
    "m": "Male",
    "10": "10s",
    "20": "20s",
    "30": "30s",
    "40": "40s",
    "50": "50s",
    "60": "60s_plus",
}


@dataclass(frozen=True)
class ShoppingCategory:
    name: str
    code: str
    parent1_name: str = ""
    parent1_code: str = ""
    parent2_name: str = ""
    parent2_code: str = ""


@dataclass
class ApiCredential:
    label: str
    client_id: str
    client_secret: str
    used_calls: int = 0


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path, dtype=str).fillna("")
    if suffix == ".csv":
        return pd.read_csv(path, dtype=str).fillna("")
    raise ValueError(f"Unsupported file type: {path.suffix}")


def add_credential(
    credentials: list[ApiCredential],
    label: str,
    client_id: str | None,
    client_secret: str | None,
) -> None:
    if not client_id or not client_secret:
        return

    client_id = clean_credential_value(client_id)
    client_secret = clean_credential_value(client_secret)
    if not client_id or not client_secret:
        return

    if not is_valid_header_value(client_id) or not is_valid_header_value(client_secret):
        print(
            f"Skipping credential '{label}': client_id/client_secret must contain "
            "only ASCII characters. Check that you replaced template values with real Naver keys."
        )
        return

    if looks_like_template_value(client_id) or looks_like_template_value(client_secret):
        print(
            f"Skipping credential '{label}': this looks like a template value, "
            "not a real Naver API key."
        )
        return

    if any(item.client_id == client_id for item in credentials):
        return

    credentials.append(ApiCredential(label=label, client_id=client_id, client_secret=client_secret))


def clean_credential_value(value: object) -> str:
    text = str(value).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    return text


def is_valid_header_value(value: str) -> bool:
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        return False
    return "\r" not in value and "\n" not in value


def looks_like_template_value(value: str) -> bool:
    upper_value = value.upper()
    return any(
        marker in upper_value
        for marker in ["YOUR_", "CLIENT_ID", "CLIENT_SECRET", "NAVER_CLIENT", "INSERT_"]
    )


def load_credentials(path: Path | None) -> list[ApiCredential]:
    credentials: list[ApiCredential] = []

    if path:
        df = read_table(path)
        columns = {str(col).strip().lower().replace("_", ""): col for col in df.columns}
        id_col = columns.get("clientid")
        secret_col = columns.get("clientsecret")
        label_col = columns.get("label")

        if not id_col or not secret_col:
            raise ValueError("Credential file must contain client_id and client_secret columns.")

        for idx, row in enumerate(df.itertuples(index=False), start=1):
            row_dict = dict(zip(df.columns, row))
            label = str(row_dict.get(label_col, "")).strip() if label_col else f"file_key_{idx}"
            add_credential(credentials, label or f"file_key_{idx}", row_dict[id_col], row_dict[secret_col])

    add_credential(
        credentials,
        "default",
        os.getenv("NAVER_CLIENT_ID") or os.getenv("NAVER_API_ID"),
        os.getenv("NAVER_CLIENT_SECRET") or os.getenv("NAVER_API_SECRET"),
    )

    for idx in range(1, 11):
        add_credential(
            credentials,
            f"key_{idx}",
            os.getenv(f"NAVER_CLIENT_ID_{idx}") or os.getenv(f"NAVER_API_ID_{idx}"),
            os.getenv(f"NAVER_CLIENT_SECRET_{idx}") or os.getenv(f"NAVER_API_SECRET_{idx}"),
        )
        add_credential(
            credentials,
            f"key{idx}",
            os.getenv(f"NAVER_CLIENT_ID{idx}") or os.getenv(f"NAVER_API_ID{idx}"),
            os.getenv(f"NAVER_CLIENT_SECRET{idx}") or os.getenv(f"NAVER_API_SECRET{idx}"),
        )

    if not credentials:
        raise RuntimeError(
            "No valid Naver API credentials found. Use real values in "
            "NAVER_CLIENT_ID_1/NAVER_CLIENT_SECRET_1 or in a credentials CSV."
        )

    return credentials


def choose_credential(credentials: list[ApiCredential], daily_limit_per_key: int) -> ApiCredential:
    available = [
        item
        for item in credentials
        if daily_limit_per_key <= 0 or item.used_calls < daily_limit_per_key
    ]
    if not available:
        usage = ", ".join(f"{item.label}={item.used_calls}" for item in credentials)
        raise RuntimeError(f"All API keys reached the configured daily limit. Usage: {usage}")
    return min(available, key=lambda item: item.used_calls)


def apply_initial_usage(credentials: list[ApiCredential], path: Path | None) -> None:
    if not path:
        return
    if not path.exists():
        raise FileNotFoundError(f"Initial usage file not found: {path}")

    df = read_table(path)
    columns = {str(col).strip().lower(): col for col in df.columns}
    label_col = columns.get("key_label") or columns.get("label")
    used_col = (
        columns.get("used_calls")
        or columns.get("used_calls_this_run")
        or columns.get("calls")
    )

    if not label_col or not used_col:
        raise ValueError("Initial usage file must contain key_label and used_calls columns.")

    usage = {
        str(row[label_col]).strip(): int(float(row[used_col]))
        for _, row in df.iterrows()
        if str(row.get(label_col, "")).strip()
    }

    for credential in credentials:
        credential.used_calls += usage.get(credential.label, 0)


def load_categories(path: Path) -> list[ShoppingCategory]:
    df = read_table(path)
    required = {"name", "code"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Category file must contain name/code columns. Missing: {sorted(missing)}")

    categories: list[ShoppingCategory] = []
    for row in df.itertuples(index=False):
        row_dict = dict(zip(df.columns, row))
        name = str(row_dict.get("name", "")).strip()
        code = str(row_dict.get("code", "")).strip()
        if not name or not code:
            continue
        categories.append(
            ShoppingCategory(
                name=name,
                code=code,
                parent1_name=str(row_dict.get("parent1_name", "")).strip(),
                parent1_code=str(row_dict.get("parent1_code", "")).strip(),
                parent2_name=str(row_dict.get("parent2_name", "")).strip(),
                parent2_code=str(row_dict.get("parent2_code", "")).strip(),
            )
        )

    if not categories:
        raise ValueError(f"No categories found in {path}.")

    return categories


def load_completed_pairs(raw_path: Path) -> set[tuple[str, str]]:
    if not raw_path.exists():
        return set()

    try:
        raw_df = pd.read_csv(raw_path, dtype=str, usecols=["category_code", "dimension"])
    except (ValueError, pd.errors.EmptyDataError):
        return set()

    return set(zip(raw_df["category_code"].astype(str), raw_df["dimension"].astype(str)))


def request_breakdown(
    dimension: str,
    category: ShoppingCategory,
    year: int,
    credential: ApiCredential,
    retries: int,
) -> dict[str, Any]:
    headers = {
        "X-Naver-Client-Id": credential.client_id,
        "X-Naver-Client-Secret": credential.client_secret,
        "Content-Type": "application/json",
    }
    payload = {
        "startDate": f"{year}-01-01",
        "endDate": f"{year}-12-31",
        "timeUnit": "month",
        "category": category.code,
    }

    for attempt in range(1, retries + 1):
        try:
            response = requests.post(
                API_URLS[dimension],
                headers=headers,
                json=payload,
                timeout=(10, 60),
            )
        except requests.RequestException as exc:
            if attempt == retries:
                raise RuntimeError(
                    f"Naver API network error with {credential.label} for "
                    f"{dimension}/{category.code} after {retries} attempts: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc

            wait_seconds = min(60.0, 2.0 * attempt)
            print(
                f"  Network error: {type(exc).__name__}. "
                f"Retrying in {wait_seconds:.1f}s..."
            )
            time.sleep(wait_seconds)
            continue

        if response.status_code == 200:
            credential.used_calls += 1
            return response.json()

        if attempt == retries:
            raise RuntimeError(
                f"Naver API failed with {credential.label} for {dimension}/{category.code}: "
                f"HTTP {response.status_code} / {response.text}"
            )

        wait_seconds = 1.5 * attempt
        print(f"  API error HTTP {response.status_code}. Retrying in {wait_seconds:.1f}s...")
        time.sleep(wait_seconds)

    raise RuntimeError("Naver API request failed.")


def response_to_rows(
    response_json: dict[str, Any],
    dimension: str,
    category: ShoppingCategory,
    year: int,
    key_label: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    results = response_json.get("results", [])

    for result in results:
        for point in result.get("data", []):
            group = str(point.get("group", "")).strip()
            if not group:
                continue

            period = pd.to_datetime(point["period"]).date().isoformat()
            rows.append(
                {
                    "year": year,
                    "period": period,
                    "dimension": dimension,
                    "segment": group,
                    "segment_label": GROUP_LABELS.get(group, group),
                    "parent1_name": category.parent1_name,
                    "parent1_code": category.parent1_code,
                    "parent2_name": category.parent2_name,
                    "parent2_code": category.parent2_code,
                    "category_name": category.name,
                    "category_code": category.code,
                    "raw_ratio": float(point["ratio"]),
                    "api_key_label": key_label,
                }
            )

    if not rows:
        for group in EXPECTED_GROUPS[dimension]:
            rows.append(
                {
                    "year": year,
                    "period": "",
                    "dimension": dimension,
                    "segment": group,
                    "segment_label": GROUP_LABELS.get(group, group),
                    "parent1_name": category.parent1_name,
                    "parent1_code": category.parent1_code,
                    "parent2_name": category.parent2_name,
                    "parent2_code": category.parent2_code,
                    "category_name": category.name,
                    "category_code": category.code,
                    "raw_ratio": 0.0,
                    "api_key_label": key_label,
                }
            )

    return rows


def append_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    df = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(
        path,
        mode="a",
        header=not path.exists(),
        index=False,
        encoding="utf-8-sig",
    )


def append_failure(
    path: Path,
    category: ShoppingCategory,
    dimension: str,
    message: str,
) -> None:
    rows = [
        {
            "failed_at": pd.Timestamp.now().isoformat(),
            "dimension": dimension,
            "parent1_name": category.parent1_name,
            "parent1_code": category.parent1_code,
            "parent2_name": category.parent2_name,
            "parent2_code": category.parent2_code,
            "category_name": category.name,
            "category_code": category.code,
            "error_message": message,
        }
    ]
    append_rows(path, rows)


def ensure_all_segments(raw_df: pd.DataFrame, categories: list[ShoppingCategory]) -> pd.DataFrame:
    existing_keys = set(
        zip(
            raw_df["category_code"].astype(str),
            raw_df["dimension"].astype(str),
            raw_df["segment"].astype(str),
        )
    )
    filler_rows: list[dict[str, Any]] = []

    for category in categories:
        for dimension, segments in EXPECTED_GROUPS.items():
            for segment in segments:
                key = (category.code, dimension, segment)
                if key in existing_keys:
                    continue
                filler_rows.append(
                    {
                        "year": "",
                        "period": "",
                        "dimension": dimension,
                        "segment": segment,
                        "segment_label": GROUP_LABELS.get(segment, segment),
                        "parent1_name": category.parent1_name,
                        "parent1_code": category.parent1_code,
                        "parent2_name": category.parent2_name,
                        "parent2_code": category.parent2_code,
                        "category_name": category.name,
                        "category_code": category.code,
                        "raw_ratio": 0.0,
                        "api_key_label": "",
                    }
                )

    if not filler_rows:
        return raw_df

    return pd.concat([raw_df, pd.DataFrame(filler_rows)], ignore_index=True)


def build_share_outputs(
    raw_path: Path,
    categories: list[ShoppingCategory],
    share_path: Path,
    wide_path: Path,
) -> None:
    raw_df = pd.read_csv(raw_path, dtype={"category_code": str, "segment": str})
    raw_df["raw_ratio"] = pd.to_numeric(raw_df["raw_ratio"], errors="coerce").fillna(0.0)
    raw_df["period"] = raw_df["period"].fillna("")
    raw_df = ensure_all_segments(raw_df, categories)

    yearly = (
        raw_df.groupby(
            [
                "dimension",
                "segment",
                "segment_label",
                "parent1_name",
                "parent1_code",
                "parent2_name",
                "parent2_code",
                "category_name",
                "category_code",
            ],
            dropna=False,
            as_index=False,
        )
        .agg(
            yearly_ratio_sum=("raw_ratio", "sum"),
            months_with_data=("period", lambda values: int(sum(str(value).strip() != "" for value in values))),
        )
        .sort_values(["parent1_name", "parent2_name", "category_name", "dimension", "segment"])
    )

    totals = yearly.groupby(["category_code", "dimension"])["yearly_ratio_sum"].transform("sum")
    yearly["share_percent"] = yearly["yearly_ratio_sum"].where(totals == 0, yearly["yearly_ratio_sum"] / totals * 100)
    yearly.loc[totals == 0, "share_percent"] = 0.0
    yearly["share_basis"] = "normalized_from_naver_relative_ratio"

    yearly.to_csv(share_path, index=False, encoding="utf-8-sig")

    wide = yearly.pivot_table(
        index=[
            "parent1_name",
            "parent1_code",
            "parent2_name",
            "parent2_code",
            "category_name",
            "category_code",
        ],
        columns=["dimension", "segment_label"],
        values="share_percent",
        aggfunc="first",
    )
    wide.columns = [f"{dimension}_{segment}_share_percent" for dimension, segment in wide.columns]
    wide = wide.reset_index()
    wide.to_csv(wide_path, index=False, encoding="utf-8-sig")


def save_api_usage(credentials: list[ApiCredential], output_dir: Path, year: int) -> Path:
    path = output_dir / f"naver_segment_api_key_usage_{year}.csv"
    usage_df = pd.DataFrame(
        [{"key_label": item.label, "used_calls_this_run": item.used_calls} for item in credentials]
    )
    usage_df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create 2025 device/gender/age share files for Naver Shopping 3rd-depth categories."
    )
    parser.add_argument(
        "--categories",
        type=Path,
        default=Path("outputs/naver_shopping_3depth_categories_2025.csv"),
        help="Category master CSV from the previous script.",
    )
    parser.add_argument("--credentials", type=Path, default=None)
    parser.add_argument(
        "--initial-usage",
        type=Path,
        default=None,
        help="Optional previous usage CSV with key_label/used_calls columns.",
    )
    parser.add_argument("--out-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument(
        "--dimensions",
        nargs="*",
        choices=["device", "gender", "age"],
        default=["device", "gender", "age"],
    )
    parser.add_argument("--daily-limit-per-key", type=int, default=1000)
    parser.add_argument("--sleep", type=float, default=1.0)
    parser.add_argument("--retries", type=int, default=6)
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop immediately when one category/dimension request fails after retries.",
    )
    parser.add_argument(
        "--max-consecutive-failures",
        type=int,
        default=10,
        help="Stop after this many consecutive failed requests, even without --stop-on-error.",
    )
    parser.add_argument(
        "--max-calls",
        type=int,
        default=0,
        help="Stop after this many successful API calls in this run. 0 means no extra run limit.",
    )
    parser.add_argument("--start-index", type=int, default=0, help="0-based category start index.")
    parser.add_argument("--limit", type=int, default=0, help="Category count limit for testing/subsets.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    categories = load_categories(args.categories)
    if args.start_index:
        categories = categories[args.start_index :]
    if args.limit:
        categories = categories[: args.limit]

    credentials = load_credentials(args.credentials)
    apply_initial_usage(credentials, args.initial_usage)

    raw_path = args.out_dir / f"naver_shopping_3depth_segment_raw_monthly_{args.year}.csv"
    share_path = args.out_dir / f"naver_shopping_3depth_segment_share_{args.year}.csv"
    wide_path = args.out_dir / f"naver_shopping_3depth_segment_share_wide_{args.year}.csv"
    failed_path = args.out_dir / f"naver_shopping_3depth_segment_failed_{args.year}.csv"

    completed = load_completed_pairs(raw_path)
    tasks = [
        (category, dimension)
        for category in categories
        for dimension in args.dimensions
        if (category.code, dimension) not in completed
    ]

    local_capacity = (
        len(credentials) * args.daily_limit_per_key
        if args.daily_limit_per_key > 0
        else len(tasks)
    )
    run_capacity = min(local_capacity, args.max_calls) if args.max_calls else local_capacity

    print(f"Categories loaded: {len(categories):,}")
    print(f"API keys loaded: {len(credentials):,}")
    print(f"Already completed category/dimension pairs: {len(completed):,}")
    print(f"Remaining API calls needed: {len(tasks):,}")
    print(f"This run capacity: {run_capacity:,}")

    calls_done = 0
    consecutive_failures = 0
    for idx, (category, dimension) in enumerate(tasks, start=1):
        if args.max_calls and calls_done >= args.max_calls:
            print("Reached --max-calls. Stop after rebuilding outputs from current raw data.")
            break

        credential = choose_credential(credentials, args.daily_limit_per_key)
        print(
            f"[{idx}/{len(tasks)}] {dimension} / {category.name} ({category.code}) "
            f"with {credential.label} used={credential.used_calls}/{args.daily_limit_per_key or 'unlimited'}"
        )

        try:
            response_json = request_breakdown(
                dimension=dimension,
                category=category,
                year=args.year,
                credential=credential,
                retries=args.retries,
            )
        except RuntimeError as exc:
            consecutive_failures += 1
            message = str(exc)
            append_failure(failed_path, category, dimension, message)
            print(f"  Failed after retries. Logged -> {failed_path}")

            if args.stop_on_error or consecutive_failures >= args.max_consecutive_failures:
                raise

            time.sleep(args.sleep)
            continue

        rows = response_to_rows(response_json, dimension, category, args.year, credential.label)
        append_rows(raw_path, rows)
        completed.add((category.code, dimension))
        calls_done += 1
        consecutive_failures = 0
        time.sleep(args.sleep)

    if raw_path.exists():
        build_share_outputs(raw_path, load_categories(args.categories), share_path, wide_path)
        print(f"Saved raw monthly ratios -> {raw_path}")
        print(f"Saved annual segment shares -> {share_path}")
        print(f"Saved annual segment shares wide -> {wide_path}")
    else:
        print("No raw data was saved, so share files were not created.")

    usage_path = save_api_usage(credentials, args.out_dir, args.year)
    print(f"Saved API usage -> {usage_path}")


if __name__ == "__main__":
    main()
