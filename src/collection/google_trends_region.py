import pandas as pd
from pytrends.request import TrendReq
import time

# pytrends 객체 생성
pytrends = TrendReq(hl='ko-KR', tz=540)
# 검색어 설정 (최대 5개)
keywords = ["에어컨", "선풍기", "전기장판"]

# 2021년부터 2025년까지 연도 리스트 설정
years = [2021, 2022, 2023, 2024, 2025]
all_years_data = pd.DataFrame()

for keyword in keywords:
    print(f"--- '{keyword}' 추출 진행 중 ---")
    keyword_data = pd.DataFrame()
    
    for year in years:
        try:
            # timeframe 및 Payload 세팅
            timeframe = f'{year}-01-01 {year}-12-31'
            pytrends.build_payload(kw_list=[keyword], cat=0, timeframe=timeframe, geo='KR')
            
            # 지역별 관심도 데이터 추출
            region_df = pytrends.interest_by_region(resolution='REGION', inc_low_vol=True, inc_geo_code=False)
            
            if not region_df.empty:
                # 컬럼명을 '키워드_연도' 형태로 변경
                region_df = region_df.rename(columns={keyword: f"{keyword}_{year}"})
                
                # 최초 빈 데이터프레임에 병합
                if keyword_data.empty:
                    keyword_data = region_df
                else:
                    keyword_data = keyword_data.join(region_df)
                    
            time.sleep(2)

        except Exception as e:
            print(f"{year}년 데이터 추출 중 오류 발생: {e}")
            
    if all_years_data.empty:
        all_years_data = keyword_data
    else:
        all_years_data = all_years_data.join(keyword_data)
        
# 최종 결과 출력
if not all_years_data.empty:
    print("✅ 2021-2025 연도별 지역 데이터 추출 완료:\n")
    print(all_years_data.head(17))
    
    # CSV 저장
    all_years_data.to_csv("google_trends_region_2021_2025.csv", encoding='utf-8-sig')
else:
    print("추출된 데이터가 없습니다.")