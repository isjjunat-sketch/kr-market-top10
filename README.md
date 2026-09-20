# 한국 주식시장 Top 10

KOSPI·KOSDAQ의 **보통주 기업 시가총액 Top 10** 구성이 어떻게 바뀌는지 누적하고, 종목보다 산업군의 진입·이탈과 비중 변화를 먼저 보여주는 개인용 대시보드입니다.

인증키, API Secret, 유료 서버가 필요하지 않습니다. GitHub Actions가 FinanceData/marcap 데이터를 확인하고 GitHub Pages를 자동 갱신합니다.

## 설치

1. GitHub에서 새 저장소를 만듭니다.
2. 이 프로젝트의 파일 전체를 `main` 브랜치에 업로드합니다.
3. 저장소의 **Actions** 탭에서 workflow 사용을 허용합니다.
4. **Settings → Pages → Source**를 `GitHub Actions`로 선택합니다.
5. Actions에서 **Update market snapshots**를 한 번 수동 실행합니다.
6. **Deploy dashboard to GitHub Pages** 완료 후 표시되는 Pages URL로 접속합니다.

이후에는 별도 조작이 필요 없습니다. 신규 Top 10 종목이 `sector_map.json`에 없을 때만 산업군을 확인해 추가하면 됩니다.

## iPhone 홈 화면에 설치

1. iPhone **Safari**에서 GitHub Pages 주소를 엽니다.
2. 하단의 **공유** 버튼을 누릅니다.
3. **홈 화면에 추가**를 선택하고 **추가**를 누릅니다.

설치 후에는 홈 화면의 `시장 Top 10` 아이콘으로 주소창 없는 앱 형태로 실행됩니다. App Store 등록, IPA 설치, 개발자 서명은 필요하지 않습니다.

PWA는 시장 데이터를 직접 백그라운드 수집하지 않습니다. GitHub Actions가 06:07·07:07·08:07 KST에 데이터를 갱신하고, PWA는 실행할 때 `history.json`과 `latest.json`의 최신 버전을 네트워크에서 먼저 확인합니다. 연결이 끊긴 경우에만 마지막으로 정상 수신한 데이터와 화면을 사용합니다.

## 운영 데이터

- 출처: [FinanceData/marcap](https://github.com/FinanceData/marcap)
- 접근 파일: `data/marcap-YYYY.parquet`
- 사용 필드: `Date`, `Rank`, `Code`, `Name`, `Close`, `Marcap`, `Stocks`, `Market`, `MarketId`
- KOSPI: `MarketId == STK`
- KOSDAQ: `MarketId == KSQ` (`KOSDAQ GLOBAL` 포함)
- marcap의 원본 `Rank`는 참고만 하고, 시장 분리와 필터링을 끝낸 뒤 `Marcap` 내림차순으로 1~10위를 다시 계산합니다.

수집기는 실행 연도의 Parquet를 내려받습니다. 연초에 새 연도 파일이 아직 없으면 직전 연도 파일을 확인합니다. 파일 안에 실제로 존재하는 가장 최근 `Date`가 기준 거래일입니다.

## 보통주 기업 필터

`scripts/filters.json`의 세 계층을 함께 사용합니다.

1. `MarketId`가 `STK` 또는 `KSQ`인 주식시장 데이터만 허용
2. 우선주 접미사, SPAC, ETF·ETN 성격 이름 규칙 제외
3. 삼성전자우·현대차2우B 등 알려진 우선주 코드를 명시적으로 제외

종목명에 단순히 `우`가 포함됐다는 이유만으로 제외하지 않습니다. `우진` 같은 일반 회사명이 잘못 제거되지 않도록 우선주 **접미사**를 판정합니다. 예외가 생기면 `include_codes`와 `exclude_codes`로 명시적으로 조정할 수 있습니다.

## 저장 전 검증과 장애 보호

새 스냅샷은 시장별로 다음 조건을 모두 통과해야 저장됩니다.

- 정확히 10개
- 종목코드 중복 없음
- 올바른 `MarketId`
- 시가총액 내림차순
- 시가총액·상장주식수 양수
- 우선주·SPAC·투자상품 필터 재검사
- 동일 기업의 중복 성격 종목 없음

다운로드 실패, timeout, 필드 변경, 빈 데이터, Top 10 검증 실패가 발생하면 프로그램은 오류로 종료하고 `history.json`과 `latest.json`을 건드리지 않습니다. 임시 파일 작성이 성공한 뒤에만 원자적으로 교체합니다.

## 자동 실행 시간

`.github/workflows/update-market.yml`은 GitHub Actions의 IANA timezone 기능을 사용합니다.

- 06:07 KST
- 07:07 KST
- 08:07 KST
- 월요일~금요일

첫 실행에서 이미 같은 거래일이 저장돼 있으면 아무 파일도 변경하지 않습니다. marcap 갱신이 늦으면 07:07과 08:07 실행이 다시 확인합니다. 주말·공휴일·휴장일에는 marcap의 최근 거래일과 기존 최신 거래일이 같으므로 중복 저장하지 않습니다.

데이터 커밋이 발생하면 `deploy-pages.yml`이 `dist/`를 GitHub Pages에 다시 배포합니다.

## 데이터 구조

- `dist/data/history.json`: 날짜별 KOSPI/KOSDAQ 스냅샷 누적
- `dist/data/latest.json`: 최신 거래일 두 시장 스냅샷
- 스냅샷: 날짜, 시장, 출처, Top 10 배열
- 종목: 최종 순위, 코드, 이름, 종가, 시가총액, 상장주식수, 산업군

산업군이 없는 신규 종목은 수집을 중단시키지 않습니다. `미분류`로 저장하고 실행 로그와 `meta.unmapped`에 코드·종목명을 기록합니다.

## 비교 정의

- 일간: 최신 거래일 ↔ 직전 거래일
- 주간: 최신 ↔ 직전 주 마지막 거래일
- 월간: 최신 ↔ 직전 월 마지막 거래일
- 분기: 최신 ↔ 직전 분기 마지막 거래일
- 연간: 최신 ↔ 직전 연도 마지막 거래일
- Sector NEW: 이전 0개 → 현재 1개 이상
- Sector OUT: 이전 1개 이상 → 현재 0개

## 로컬 실행

```bash
pip install -r requirements.txt
python scripts/fetch_market.py
python -m http.server 8000 -d dist
```

`http://localhost:8000`에서 확인합니다. 파일을 변경하지 않고 실제 최신 데이터를 검증하려면 다음을 사용합니다.

```bash
python scripts/fetch_market.py --dry-run
```

과거 실제 데이터를 초기 구축할 때는 marcap 연도별 Parquet 파일을 내려받은 뒤 다음처럼 실행할 수 있습니다.

```bash
python scripts/fetch_market.py \
  --source-file marcap-2025.parquet \
  --source-file marcap-2026.parquet \
  --backfill-start 2025-01-02
```

## 파일 구조

```text
dist/
  index.html, style.css, extra.css, app.js
  manifest.webmanifest, service-worker.js
  icons/icon-192.png, icon-512.png, apple-touch-icon.png
  data/history.json, data/latest.json
scripts/
  fetch_market.py
  sector_map.json
  filters.json
.github/workflows/
  update-market.yml
  deploy-pages.yml
requirements.txt
README.md
```

페이지 하단에는 데이터 출처, 실제 시장 거래일, Actions 갱신 시각을 각각 표시합니다.
