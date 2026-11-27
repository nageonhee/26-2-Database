# 26-2-Database

데이터베이스 기말 대체 프로젝트 — 건강보험심사평가원(HIRA) 공공데이터로 병원·진료과·질병 정보를 조회하는 Python + MySQL 서비스

## 프로젝트 개요

- 병원 정보, 진료과목, 의료장비, 운영 시간 등 의료기관 데이터를 MySQL에 정규화해 적재
- 상병마스터와 진료과목별 상병 통계를 연결해 **질병명 → 진료과 → 해당 기관** 조회 기능 제공
- 과제 요구사항과 진행 정리는 `DB_기말대체프로젝트_정리.pdf` 참고

## Flask 웹앱 로컬 실행

### 팀 MySQL DB 준비

`hira_db`가 이미 준비되어 있으면 Flask 실행 단계로 넘어갑니다. 새로 구축하는 경우 프로젝트 루트에서 `cd src`로 이동한 뒤 MySQL 8.0의 빈 환경에서 아래 순서대로 실행합니다.

1. [`schema.sql`](src/schema.sql)을 MySQL에서 실행해 테이블 16개와 뷰 1개를 생성합니다.
2. [`load_data.py`](src/load_data.py)에 `--dir ../DB`를 지정해 기본 테이블 12개를 적재합니다.
3. [`load_disease.py`](src/load_disease.py)에 `--master`와 `--stat`으로 두 상병 CSV 파일을 지정해 질병 테이블 4개를 적재합니다.

적재에는 `pandas`와 `PyMySQL`이 필요합니다. 두 적재 스크립트와 Flask에 같은 MySQL 호스트·계정·데이터베이스를 지정합니다.

### Flask 실행

프로젝트 루트의 PowerShell에서 실행합니다. 이미 `src`에 있으면 `cd src`를 건너뜁니다.

```powershell
python -m pip install Flask "PyMySQL[rsa]"
cd src
$env:HIRA_MYSQL_USER = 'root'
$env:HIRA_MYSQL_PASSWORD = Read-Host 'MySQL 비밀번호' -MaskInput
python app.py
```

브라우저에서 [http://127.0.0.1:5000](http://127.0.0.1:5000)을 엽니다. Flask는 기본적으로 `127.0.0.1:3306`의 `hira_db`를 조회합니다. 필요한 경우 `HIRA_MYSQL_HOST`, `HIRA_MYSQL_PORT`, `HIRA_MYSQL_DATABASE`를 설정할 수 있습니다.

## 폴더 구성

| 경로 | 내용 |
|---|---|
| [`src/`](src/) | Flask 웹앱 소스 · [`app.py`](src/app.py), [`index.html`](src/templates/index.html), [`style.css`](src/static/style.css) |
| [`설계/`](%EC%84%A4%EA%B3%84/) | 설계 자료와 ER 다이어그램 |
| [`load_data.py`](src/load_data.py), [`load_disease.py`](src/load_disease.py) | 팀 데이터 적재 코드 |
| [`DB/`](DB/) | 설계에서 사용하는 원본 CSV 9개 (병원·약국정보, 상세정보 01 시설·02 세부·03 진료과목·05 의료장비·08 특수진료, 상병마스터, 진료과목별 상병 통계) |
| [`설계/schema.sql`](%EC%84%A4%EA%B3%84/schema.sql) | 초기 설계 참고용 스키마 |
| [`설계/ER_full.png`](%EC%84%A4%EA%B3%84/ER_full.png), [`설계/hira_ER_chen_full.drawio`](%EC%84%A4%EA%B3%84/hira_ER_chen_full.drawio) | ER 다이어그램 |
| [`DB_기말대체프로젝트_정리.pdf`](DB_%EA%B8%B0%EB%A7%90%EB%8C%80%EC%B2%B4%ED%94%84%EB%A1%9C%EC%A0%9D%ED%8A%B8_%EC%A0%95%EB%A6%AC.pdf) | 과제 요구사항·진행 정리 |

주요 테이블: `sido`, `sigungu`, `institution`, `institution_type`, `ownership_type`, `dept`, `institution_dept`, `equipment_type`, `institution_equip`, `program`, `institution_program`, `business_hours`, `disease3`, `disease`, `disease_name`, `dept_disease_stat`

## 조회 기능

| # | 기능 | 내용 |
|---|---|---|
| ① | 의료기관 검색 | 기관명·종별·설립구분·지역으로 기관 찾기 |
| ② | 진료과목별 기관 | 진료과목을 고르면 해당 기관을 전문의 수 순으로 보여줌 |
| ③ | 지역별 기관 수 | 종별로 시도별 기관 수·비율·순위 집계 |
| ④ | 질병으로 진료과 찾기 | 질병명·상병코드 → 환자 수 상위 진료과 → 지역 기관 수 |
| ⑤ | 의료장비 보유 기관 | 장비 종류·최소 대수로 기관 찾기 |
| ⑥ | 요일·시각별 진료 | 요일·시각·진료과목으로 진료 중인 기관 찾기 |
| ⑦ | 지정·시범사업 참여 | 특수진료·시범사업 참여 기관 찾기 |
| ⑧ | 진료과목 다양성 순위 | 진료과목 수 순으로 상위 N개 기관 표시 |

## 진행해야 할 일

### [다 같이] 질병 안내에서 뺄 진료과목 정하기

후보: 일반의, 응급의학과, 진단검사의학과, 영상의학과, 병리과, 핵의학과, 방사선종양학과, 예방의학과, 직업환경의학과, 보건기관의과, 구강병리과, 영상치의학과

- [ ] 빼면 안 될 과목이 있으면 의견 내기 (없으면 위 목록대로 진행)

### [승인님] 데이터 적재 — 11/24까지

- [ ] 통계의 3단 상병코드(1,663개)가 상병마스터에 모두 있는지 **가장 먼저** 확인 (없는 코드가 있으면 FK 에러 → 처리 방법 함께 결정)
- [ ] 통계 진료과목 이름 중 `dept`와 안 맞는 3개 처리 (매핑 또는 제외)
- [ ] 상병마스터 완전 중복 158건 제거, 숫자 값 뒤 공백 제거
- [ ] `load_data.py`에서 뺀 테이블 7개 적재 코드 삭제 + 질병 테이블 4개 적재 추가
- [ ] 적재 후 덤프 파일 크기와 적재 시간 공유

### [건희님·상현님] app.py

- [x] 병상 현황 기능(`q_bed`) 삭제
- [x] ④ 질병으로 진료과 찾기 추가 (질병명 → 상위 진료과 → [기관 보기] → ②번 기능으로 연결)
