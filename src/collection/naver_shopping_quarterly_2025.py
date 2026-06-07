"""
Create quarterly Naver Shopping Insight CSV files for every 3rd-depth category.

Important:
  Naver Shopping Insight returns a relative click index named "ratio", not raw
  click counts. This script therefore creates quarterly average click ratios.

Prerequisites:
  pip install -r requirements.txt

Environment variables:
  NAVER_CLIENT_ID_1
  NAVER_CLIENT_SECRET_1
  NAVER_CLIENT_ID_2
  NAVER_CLIENT_SECRET_2
  NAVER_CLIENT_ID_3
  NAVER_CLIENT_SECRET_3
  NAVER_CLIENT_ID_4
  NAVER_CLIENT_SECRET_4
  NAVER_CLIENT_ID_5
  NAVER_CLIENT_SECRET_5
  NAVER_CLIENT_ID_6
  NAVER_CLIENT_SECRET_6

  NAVER_CLIENT_ID / NAVER_CLIENT_SECRET is also supported for a single key.

Typical usage:
  python naver_shopping_quarterly_2025.py --out-dir outputs --year 2025

Usage with a credential file:
  python naver_shopping_quarterly_2025.py --credentials naver_credentials.csv --out-dir outputs --year 2025

If automatic category discovery is blocked by Naver, pass a full category file:
  python naver_shopping_quarterly_2025.py --categories my_categories.xlsx --out-dir outputs
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import requests


SHOPPING_INSIGHT_API_URL = "https://openapi.naver.com/v1/datalab/shopping/categories"
DATALAB_CATEGORY_PAGE_URL = "https://datalab.naver.com/shoppingInsight/sCategory.naver"
MAX_CATEGORIES_PER_REQUEST = 3

TOP_LEVEL_CATEGORIES = [
    ("패션의류", "50000000"),
    ("패션잡화", "50000001"),
    ("화장품/미용", "50000002"),
    ("디지털/가전", "50000003"),
    ("가구/인테리어", "50000004"),
    ("출산/육아", "50000005"),
    ("식품", "50000006"),
    ("스포츠/레저", "50000007"),
    ("생활/건강", "50000008"),
]


@dataclass(frozen=True)
class ShoppingCategory:
    name: str
    code: str
    depth: int = 3
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


def chunked(items: list[ShoppingCategory], size: int) -> Iterable[list[ShoppingCategory]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


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

    credentials.append(
        ApiCredential(
            label=label,
            client_id=client_id,
            client_secret=client_secret,
        )
    )


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


def load_credentials(credentials_path: Path | None = None) -> list[ApiCredential]:
    credentials: list[ApiCredential] = []

    if credentials_path:
        df = read_table(credentials_path)
        id_col = find_column(df, {"clientid", "naverclientid", "id"})
        secret_col = find_column(df, {"clientsecret", "naverclientsecret", "secret"})
        label_col = find_column(df, {"label", "name", "keyname"})

        if not id_col or not secret_col:
            raise ValueError(
                "Credential file must contain client_id/client_secret columns."
            )

        for idx, row in enumerate(df.itertuples(index=False), start=1):
            row_dict = dict(zip(df.columns, row))
            label = (
                str(row_dict.get(label_col, "")).strip()
                if label_col
                else f"file_key_{idx}"
            )
            add_credential(
                credentials,
                label or f"file_key_{idx}",
                str(row_dict[id_col]).strip(),
                str(row_dict[secret_col]).strip(),
            )

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


def choose_credential(
    credentials: list[ApiCredential],
    daily_limit_per_key: int,
) -> ApiCredential:
    available = [
        credential
        for credential in credentials
        if daily_limit_per_key <= 0 or credential.used_calls < daily_limit_per_key
    ]

    if not available:
        usage = ", ".join(
            f"{credential.label}={credential.used_calls}" for credential in credentials
        )
        raise RuntimeError(
            f"All API keys reached the configured daily limit. Usage: {usage}"
        )

    return min(available, key=lambda credential: credential.used_calls)


def normalize_column_name(column: str) -> str:
    return re.sub(r"[\s_\-()/]+", "", str(column).strip().lower())


def find_column(df: pd.DataFrame, candidates: set[str]) -> str | None:
    normalized = {normalize_column_name(col): col for col in df.columns}
    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate]
    return None


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path, dtype=str).fillna("")
    if suffix == ".csv":
        return pd.read_csv(path, dtype=str).fillna("")
    raise ValueError(f"Unsupported category file type: {path.suffix}")


def load_categories(path: Path) -> list[ShoppingCategory]:
    """Load 3rd-depth categories from a flexible CSV/XLSX category file."""
    df = read_table(path)
    if df.empty:
        raise ValueError(f"No rows found in {path}.")

    simple_name_col = find_column(df, {"categoryname", "name", "카테고리명", "분류명"})
    simple_code_col = find_column(df, {"categorycode", "code", "cid", "catid", "카테고리코드", "카테고리id"})
    depth_col = find_column(df, {"depth", "level", "단계", "분류단계", "카테고리단계"})

    third_name_col = find_column(
        df,
        {"category3", "category3name", "thirdcategory", "thirdcategoryname", "소분류", "3분류", "제3분류"},
    )
    third_code_col = find_column(
        df,
        {
            "category3code",
            "thirdcategorycode",
            "category3id",
            "thirdcategoryid",
            "소분류코드",
            "3분류코드",
            "제3분류코드",
        },
    )
    first_name_col = find_column(
        df, {"category1", "category1name", "parent1name", "대분류", "1분류", "제1분류"}
    )
    first_code_col = find_column(
        df, {"category1code", "category1id", "parent1code", "대분류코드", "1분류코드", "제1분류코드"}
    )
    second_name_col = find_column(
        df, {"category2", "category2name", "parent2name", "중분류", "2분류", "제2분류"}
    )
    second_code_col = find_column(
        df, {"category2code", "category2id", "parent2code", "중분류코드", "2분류코드", "제2분류코드"}
    )

    categories: list[ShoppingCategory] = []

    if third_name_col and third_code_col:
        for row in df.itertuples(index=False):
            row_dict = dict(zip(df.columns, row))
            name = str(row_dict[third_name_col]).strip()
            code = str(row_dict[third_code_col]).strip()
            if name and code:
                categories.append(
                    ShoppingCategory(
                        name=name,
                        code=code,
                        depth=3,
                        parent1_name=str(row_dict.get(first_name_col, "")).strip() if first_name_col else "",
                        parent1_code=str(row_dict.get(first_code_col, "")).strip() if first_code_col else "",
                        parent2_name=str(row_dict.get(second_name_col, "")).strip() if second_name_col else "",
                        parent2_code=str(row_dict.get(second_code_col, "")).strip() if second_code_col else "",
                    )
                )
    elif simple_name_col and simple_code_col:
        if depth_col:
            depth_values = df[depth_col].astype(str).str.extract(r"(\d+)")[0]
            df = df[depth_values == "3"]

        for row in df.itertuples(index=False):
            row_dict = dict(zip(df.columns, row))
            name = str(row_dict[simple_name_col]).strip()
            code = str(row_dict[simple_code_col]).strip()
            if name and code:
                categories.append(
                    ShoppingCategory(
                        name=name,
                        code=code,
                        depth=3,
                        parent1_name=str(row_dict.get(first_name_col, "")).strip() if first_name_col else "",
                        parent1_code=str(row_dict.get(first_code_col, "")).strip() if first_code_col else "",
                        parent2_name=str(row_dict.get(second_name_col, "")).strip() if second_name_col else "",
                        parent2_code=str(row_dict.get(second_code_col, "")).strip() if second_code_col else "",
                    )
                )
    else:
        raise ValueError(
            "Category file must contain either category_name/category_code columns "
            "or 3rd-depth columns such as 제3분류/제3분류코드."
        )

    unique: dict[str, ShoppingCategory] = {}
    for category in categories:
        unique[category.code] = category

    if not unique:
        raise ValueError(f"No 3rd-depth categories found in {path}.")

    return sorted(unique.values(), key=lambda item: (item.parent1_name, item.parent2_name, item.name, item.code))


def datalab_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": DATALAB_CATEGORY_PAGE_URL,
        }
    )
    return session


def parse_category_json_node(node: Any, path: list[ShoppingCategory]) -> list[ShoppingCategory]:
    """Parse common category tree shapes used by web UIs."""
    if isinstance(node, list):
        rows: list[ShoppingCategory] = []
        for item in node:
            rows.extend(parse_category_json_node(item, path))
        return rows

    if not isinstance(node, dict):
        return []

    code = str(
        node.get("cid")
        or node.get("id")
        or node.get("code")
        or node.get("categoryId")
        or node.get("categoryCode")
        or ""
    ).strip()
    name = str(
        node.get("name")
        or node.get("categoryName")
        or node.get("text")
        or node.get("title")
        or ""
    ).strip()

    current_path = path
    if code and name:
        current_path = path + [ShoppingCategory(name=name, code=code, depth=len(path) + 1)]

    children = (
        node.get("children")
        or node.get("child")
        or node.get("childList")
        or node.get("categories")
        or node.get("list")
        or node.get("data")
        or []
    )

    if len(current_path) == 3:
        first, second, third = current_path
        return [
            ShoppingCategory(
                name=third.name,
                code=third.code,
                depth=3,
                parent1_name=first.name,
                parent1_code=first.code,
                parent2_name=second.name,
                parent2_code=second.code,
            )
        ]

    return parse_category_json_node(children, current_path)


def try_parse_json_response(response: requests.Response) -> Any | None:
    content_type = response.headers.get("Content-Type", "")
    text = response.text.strip()
    if "json" in content_type or text.startswith(("{", "[")):
        return response.json()
    return None


def fetch_child_categories(session: requests.Session, parent_code: str) -> list[dict[str, Any]]:
    """Try likely DataLab category endpoints. These are UI endpoints and may change."""
    endpoint_candidates = [
        "https://datalab.naver.com/shoppingInsight/getCategory.naver",
        "https://datalab.naver.com/shoppingInsight/getCategoryList.naver",
        "https://datalab.naver.com/shoppingInsight/getChildCategory.naver",
    ]
    payload_candidates = [
        {"cid": parent_code},
        {"parentCid": parent_code},
        {"parentCode": parent_code},
    ]

    for endpoint in endpoint_candidates:
        for payload in payload_candidates:
            try:
                response = session.post(
                    endpoint,
                    data=payload,
                    headers={"X-Requested-With": "XMLHttpRequest"},
                    timeout=20,
                )
                if response.status_code != 200:
                    continue
                data = try_parse_json_response(response)
                if data is None:
                    continue
                categories = parse_category_json_node(data, [])
                if categories:
                    return [
                        {"name": item.name, "code": item.code, "children": []}
                        for item in categories
                    ]
                if isinstance(data, dict):
                    for key in ("children", "childList", "categories", "list", "data"):
                        value = data.get(key)
                        if isinstance(value, list):
                            return value
                if isinstance(data, list):
                    return data
            except (requests.RequestException, json.JSONDecodeError):
                continue

    return []


def discover_categories_from_datalab() -> list[ShoppingCategory]:
    """
    Discover every 3rd-depth category from the DataLab UI.

    The official OpenAPI does not expose category enumeration. This function uses
    the public DataLab page/UI calls as a best effort. If Naver blocks automated
    access, use --categories with a SmartStore full category file instead.
    """
    session = datalab_session()
    discovered: list[ShoppingCategory] = []

    try:
        page = session.get(DATALAB_CATEGORY_PAGE_URL, timeout=20)
        page.raise_for_status()
        embedded_categories = parse_embedded_categories(page.text)
        if embedded_categories:
            return embedded_categories
    except requests.RequestException:
        pass

    for first_name, first_code in TOP_LEVEL_CATEGORIES:
        second_level = fetch_child_categories(session, first_code)
        for second in second_level:
            second_name = str(second.get("name") or second.get("categoryName") or second.get("text") or "").strip()
            second_code = str(second.get("cid") or second.get("id") or second.get("code") or second.get("categoryId") or "").strip()
            if not second_name or not second_code:
                continue

            third_level = fetch_child_categories(session, second_code)
            for third in third_level:
                third_name = str(third.get("name") or third.get("categoryName") or third.get("text") or "").strip()
                third_code = str(third.get("cid") or third.get("id") or third.get("code") or third.get("categoryId") or "").strip()
                if third_name and third_code:
                    discovered.append(
                        ShoppingCategory(
                            name=third_name,
                            code=third_code,
                            depth=3,
                            parent1_name=first_name,
                            parent1_code=first_code,
                            parent2_name=second_name,
                            parent2_code=second_code,
                        )
                    )
            time.sleep(0.3)

    unique = {item.code: item for item in discovered}
    return sorted(unique.values(), key=lambda item: (item.parent1_name, item.parent2_name, item.name, item.code))


def parse_embedded_categories(html: str) -> list[ShoppingCategory]:
    candidates: list[ShoppingCategory] = []
    for match in re.finditer(r"(\{[^<>]{0,200000}5000000\d[^<>]{0,200000}\}|\[[^<>]{0,200000}5000000\d[^<>]{0,200000}\])", html):
        text = match.group(0)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        candidates.extend(parse_category_json_node(data, []))

    unique = {item.code: item for item in candidates}
    return sorted(unique.values(), key=lambda item: (item.parent1_name, item.parent2_name, item.name, item.code))


def save_category_master(categories: list[ShoppingCategory], output_dir: Path, year: int) -> Path:
    path = output_dir / f"naver_shopping_3depth_categories_{year}.csv"
    df = pd.DataFrame([category.__dict__ for category in categories])
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def save_api_usage(credentials: list[ApiCredential], output_dir: Path, year: int) -> Path:
    path = output_dir / f"naver_api_key_usage_{year}.csv"
    usage_df = pd.DataFrame(
        [
            {
                "key_label": credential.label,
                "used_calls": credential.used_calls,
            }
            for credential in credentials
        ]
    )
    usage_df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def request_category_trend(
    categories: list[ShoppingCategory],
    year: int,
    credential: ApiCredential,
    device: str = "",
    gender: str = "",
    ages: list[str] | None = None,
    retries: int = 3,
) -> dict:
    headers = {
        "X-Naver-Client-Id": credential.client_id,
        "X-Naver-Client-Secret": credential.client_secret,
        "Content-Type": "application/json",
    }
    payload = {
        "startDate": f"{year}-01-01",
        "endDate": f"{year}-12-31",
        "timeUnit": "month",
        "category": [
            {"name": category.name, "param": [category.code]} for category in categories
        ],
        "device": device,
        "gender": gender,
        "ages": ages or [],
    }

    for attempt in range(1, retries + 1):
        response = requests.post(SHOPPING_INSIGHT_API_URL, headers=headers, json=payload, timeout=30)
        if response.status_code == 200:
            credential.used_calls += 1
            return response.json()

        if attempt == retries:
            raise RuntimeError(
                f"Naver API request failed with {credential.label}: "
                f"HTTP {response.status_code} / {response.text}"
            )

        wait_seconds = 1.5 * attempt
        print(f"  API error HTTP {response.status_code}. Retrying in {wait_seconds:.1f}s...")
        time.sleep(wait_seconds)

    raise RuntimeError("Naver API request failed.")


def flatten_response(
    response_json: dict,
    requested_categories: list[ShoppingCategory],
    year: int,
    device: str,
    gender: str,
    ages: list[str],
) -> list[dict]:
    by_name = {category.name: category for category in requested_categories}
    by_code = {category.code: category for category in requested_categories}
    rows: list[dict] = []

    for result in response_json.get("results", []):
        category_name = str(result.get("title", "")).strip()
        category_code = ""
        category_value = result.get("category", [])
        if isinstance(category_value, list) and category_value:
            category_code = str(category_value[0])

        category = by_code.get(category_code) or by_name.get(category_name)
        if category:
            category_name = category.name
            category_code = category.code

        for point in result.get("data", []):
            period = pd.to_datetime(point["period"])
            month = int(period.month)
            rows.append(
                {
                    "year": year,
                    "period": period.date().isoformat(),
                    "month": month,
                    "quarter": f"Q{((month - 1) // 3) + 1}",
                    "parent1_name": category.parent1_name if category else "",
                    "parent1_code": category.parent1_code if category else "",
                    "parent2_name": category.parent2_name if category else "",
                    "parent2_code": category.parent2_code if category else "",
                    "category_name": category_name,
                    "category_code": category_code,
                    "click_ratio": float(point["ratio"]),
                    "device": device or "all",
                    "gender": gender or "all",
                    "ages": ",".join(ages) if ages else "all",
                }
            )

    return rows


def build_quarterly_dataframe(monthly_df: pd.DataFrame) -> pd.DataFrame:
    quarter_bounds = {
        "Q1": ("01-01", "03-31"),
        "Q2": ("04-01", "06-30"),
        "Q3": ("07-01", "09-30"),
        "Q4": ("10-01", "12-31"),
    }

    quarterly = (
        monthly_df.groupby(
            [
                "year",
                "quarter",
                "parent1_name",
                "parent1_code",
                "parent2_name",
                "parent2_code",
                "category_name",
                "category_code",
                "device",
                "gender",
                "ages",
            ],
            as_index=False,
        )
        .agg(
            months_in_quarter=("period", "nunique"),
            quarterly_avg_click_ratio=("click_ratio", "mean"),
            quarterly_sum_click_ratio=("click_ratio", "sum"),
            quarterly_max_click_ratio=("click_ratio", "max"),
        )
        .sort_values(["parent1_name", "parent2_name", "category_name", "quarter"])
    )

    quarterly["quarter_start"] = quarterly.apply(
        lambda row: f"{row.year}-{quarter_bounds[row.quarter][0]}", axis=1
    )
    quarterly["quarter_end"] = quarterly.apply(
        lambda row: f"{row.year}-{quarter_bounds[row.quarter][1]}", axis=1
    )

    return quarterly[
        [
            "year",
            "quarter",
            "quarter_start",
            "quarter_end",
            "parent1_name",
            "parent1_code",
            "parent2_name",
            "parent2_code",
            "category_name",
            "category_code",
            "device",
            "gender",
            "ages",
            "months_in_quarter",
            "quarterly_avg_click_ratio",
            "quarterly_sum_click_ratio",
            "quarterly_max_click_ratio",
        ]
    ]


def save_outputs(
    monthly_df: pd.DataFrame,
    quarterly_df: pd.DataFrame,
    output_dir: Path,
    year: int,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    monthly_path = output_dir / f"naver_shopping_3depth_monthly_{year}.csv"
    quarterly_path = output_dir / f"naver_shopping_3depth_quarterly_{year}.csv"
    pivot_path = output_dir / f"naver_shopping_3depth_quarterly_pivot_{year}.csv"

    monthly_df.to_csv(monthly_path, index=False, encoding="utf-8-sig")
    quarterly_df.to_csv(quarterly_path, index=False, encoding="utf-8-sig")

    pivot_df = quarterly_df.pivot_table(
        index=["year", "quarter", "quarter_start", "quarter_end"],
        columns="category_name",
        values="quarterly_avg_click_ratio",
        aggfunc="mean",
    ).reset_index()
    pivot_df.to_csv(pivot_path, index=False, encoding="utf-8-sig")

    print(f"Saved monthly rows: {len(monthly_df):,} -> {monthly_path}")
    print(f"Saved quarterly rows: {len(quarterly_df):,} -> {quarterly_path}")
    print(f"Saved quarterly pivot -> {pivot_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download Naver Shopping Insight ratios for every 3rd-depth category and aggregate by quarter."
    )
    parser.add_argument(
        "--categories",
        type=Path,
        default=None,
        help="Optional CSV/XLSX with all 3rd-depth categories. If omitted, the script tries DataLab auto-discovery.",
    )
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--out-dir", type=Path, default=Path("."))
    parser.add_argument(
        "--credentials",
        type=Path,
        default=None,
        help=(
            "Optional CSV/XLSX with client_id,client_secret columns. "
            "Environment variables are also supported."
        ),
    )
    parser.add_argument(
        "--daily-limit-per-key",
        type=int,
        default=1000,
        help="Configured daily API call limit per key. Use 0 to disable local limit tracking.",
    )
    parser.add_argument(
        "--device",
        choices=["", "pc", "mo"],
        default="",
        help="Blank means all devices.",
    )
    parser.add_argument(
        "--gender",
        choices=["", "m", "f"],
        default="",
        help="Blank means all genders.",
    )
    parser.add_argument(
        "--ages",
        nargs="*",
        default=[],
        help="Optional age codes, for example: --ages 20 30. Blank means all ages.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=1.0,
        help="Seconds to wait between API requests. Increase this if Naver rate-limits you.",
    )
    parser.add_argument(
        "--categories-per-request",
        type=int,
        default=1,
        choices=[1, 2, 3],
        help=(
            "Naver allows up to 3. Default 1 keeps each category's ratio normalized "
            "within itself, which is better for per-category quarterly averages."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="For testing only. 0 means no limit.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    credentials = load_credentials(args.credentials)
    total_local_limit = (
        len(credentials) * args.daily_limit_per_key
        if args.daily_limit_per_key > 0
        else "unlimited"
    )
    print(f"Loaded API keys: {len(credentials):,}")
    print(f"Configured local call capacity: {total_local_limit}")

    if args.categories:
        categories = load_categories(args.categories)
    else:
        print("Discovering every 3rd-depth category from Naver DataLab...")
        categories = discover_categories_from_datalab()
        if not categories:
            raise RuntimeError(
                "Automatic category discovery failed. "
                "Download the full Naver SmartStore category code Excel/CSV and rerun with --categories."
            )

    if args.limit:
        categories = categories[: args.limit]

    category_master_path = save_category_master(categories, args.out_dir, args.year)
    print(f"Loaded 3rd-depth categories: {len(categories):,}")
    print(f"Saved category master -> {category_master_path}")

    all_rows: list[dict] = []
    total_chunks = (
        len(categories) + args.categories_per_request - 1
    ) // args.categories_per_request
    if args.daily_limit_per_key > 0 and total_chunks > len(credentials) * args.daily_limit_per_key:
        raise RuntimeError(
            f"Not enough API call capacity for this run. Need {total_chunks:,} calls, "
            f"but {len(credentials):,} keys x {args.daily_limit_per_key:,} calls = "
            f"{len(credentials) * args.daily_limit_per_key:,} calls. "
            "Add more keys, increase --categories-per-request, or split the run."
        )

    for idx, category_chunk in enumerate(
        chunked(categories, args.categories_per_request), start=1
    ):
        credential = choose_credential(credentials, args.daily_limit_per_key)
        names = ", ".join(category.name for category in category_chunk)
        print(
            f"[{idx}/{total_chunks}] Requesting with {credential.label} "
            f"(used {credential.used_calls}/{args.daily_limit_per_key or 'unlimited'}): {names}"
        )

        response_json = request_category_trend(
            categories=category_chunk,
            year=args.year,
            credential=credential,
            device=args.device,
            gender=args.gender,
            ages=args.ages,
        )
        all_rows.extend(
            flatten_response(
                response_json=response_json,
                requested_categories=category_chunk,
                year=args.year,
                device=args.device,
                gender=args.gender,
                ages=args.ages,
            )
        )
        time.sleep(args.sleep)

    monthly_df = pd.DataFrame(all_rows)
    if monthly_df.empty:
        raise RuntimeError("Naver API returned no data.")

    monthly_df = monthly_df.sort_values(
        ["parent1_name", "parent2_name", "category_name", "category_code", "period"]
    )
    quarterly_df = build_quarterly_dataframe(monthly_df)

    print("\nQuarterly dataframe preview:")
    print(quarterly_df.head(20).to_string(index=False))

    save_outputs(monthly_df, quarterly_df, args.out_dir, args.year)
    usage_path = save_api_usage(credentials, args.out_dir, args.year)
    print(f"Saved API usage -> {usage_path}")


if __name__ == "__main__":
    main()
