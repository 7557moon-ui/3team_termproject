# 2025 Online Shopping Insight Analysis

네이버 쇼핑인사이트 클릭 지수와 온라인 쇼핑 판매액, 이용자 세그먼트,
기온 및 지역별 검색 데이터를 결합해 상품군별 수요 특성을 분석한 프로젝트입니다.

## 주요 분석 주제

- 상품별 분기 및 월별 클릭 지수 변화와 계절성
- 스키/보드 상품 클릭 지수와 월평균 기온의 상관관계
- 출산/육아 상품군의 연령대 및 성별 이용 특성
- 판매 매체별 상품군 거래액과 해외 직접판매액 비교
- 상품군별 소비자 타깃 포지셔닝

> 네이버 쇼핑인사이트의 클릭 지수는 절대 클릭 수가 아니라 분석 기간 내
> 상대적 관심도를 나타내는 정규화 지수입니다.

## 프로젝트 구조

```text
shopping-insight-analysis/
├── data/
│   ├── raw/          # 외부 기관에서 받은 원본 데이터
│   ├── interim/      # 병합 등 중간 처리 데이터
│   └── processed/    # 분석에 바로 사용하는 최종 데이터
├── notebooks/        # 주제별 분석 및 시각화 노트북
├── src/
│   ├── collection/   # 네이버 API 및 Google Trends 수집 코드
│   └── processing/   # 데이터 전처리 및 병합 코드
├── docs/             # 프로젝트 제안서
├── requirements.txt
└── README.md
```

## 분석코드 실행 순서
-꼭 이 파일 순서대로 분석 결과가 이어지는 것은 아니지만, 분석 파일이 많아서 이러한 순서대로 읽어주시면 이해에 도움되실겁니다.

1. `01_google_trends_region_analysis.ipynb`
2. `02_sales_by_channel_analysis.ipynb`
3. `03_overseas_direct_sales_analysis.ipynb`
4. `04_naver_quarterly_click_analysis.ipynb`
5. `05_naver_segment_analysis.ipynb`
6. `06_consumer_target_positioning.ipynb`
7. `07_quarterly_sales_volatility.ipynb`
8. `08_integrated_visualizations.ipynb`


## 데이터 수집 코드

네이버 API 수집 코드를 실행하려면 환경 변수에 API 키를 등록해야 합니다.

```text
NAVER_CLIENT_ID
NAVER_CLIENT_SECRET
```

여러 API 키를 사용하는 경우 `NAVER_CLIENT_ID_1`,
`NAVER_CLIENT_SECRET_1` 형식으로 등록할 수 있습니다. API 키와 인증 파일은
GitHub에 올리지 마세요.

## 분석 시 주의사항

- 클릭 지수와 세그먼트 비율은 절대 사용자 수를 의미하지 않습니다.
- 결측값 또는 비율 합계가 비정상적인 상품은 분석 전에 제외해야 합니다.
- 일부 원본 CSV는 `cp949` 인코딩이므로 읽을 때 인코딩 지정이 필요합니다.
