# 26-2-Database

데이터베이스 기말 대체 프로젝트 — 건강보험심사평가원(HIRA) 공공데이터로 병원·진료과·질병 정보를 조회하는 Python + MySQL 서비스

## 프로젝트 개요

- 병원 정보, 진료과목, 의료장비, 운영 시간 등 의료기관 데이터를 MySQL에 정규화해 적재
- 상병마스터와 진료과목별 상병 통계를 연결해 **질병명 → 진료과 → 해당 기관** 조회 기능 제공
- 과제 요구사항과 진행 정리는 `DB_기말대체프로젝트_정리.pdf` 참고

## Flask 웹앱 로컬 실행

프로젝트 루트에서 PowerShell로 실행합니다. Flask가 이미 설치되어 있으면 첫 줄은 건너뛰어도 됩니다.

```powershell
python -m pip install Flask
cd src
python app.py
```

서버가 켜지면 브라우저에서 [http://127.0.0.1:5000](http://127.0.0.1:5000)을 엽니다. 기본 실행은 SQLite를 사용합니다. `src/hira.sqlite3` 파일이 없으면 첫 실행 때 `DB/`의 CSV와 `설계/schema.sql`로 자동 생성합니다. 첫 실행은 몇 초 더 걸릴 수 있습니다.

### 파일 역할과 DB 갱신

- [`src/app.py`](src/app.py)는 Flask 웹을 실행하고, 검색 조건으로 DB를 조회해 결과를 화면에 표시합니다.
- [`src/load_db.py`](src/load_db.py)는 `DB/`의 CSV와 `설계/schema.sql`을 읽어 조회용 SQLite DB를 만듭니다. 첫 실행에서 DB 파일이 없으면 `app.py`가 이 생성 함수를 호출합니다.
- [`src/templates/index.html`](src/templates/index.html)과 [`src/static/style.css`](src/static/style.css)는 로컬 Flask 화면의 구조와 스타일을 담당합니다.

CSV 또는 스키마가 바뀌면 `src`에서 `python load_db.py`를 실행한 뒤 `python app.py`로 서버를 다시 시작합니다. GitHub에는 원본 CSV와 설계 SQL을 두고, 생성된 SQLite 파일은 실행할 컴퓨터에서 만듭니다.

과제용 MySQL은 [팀 DB 공유 안내](HIRA_DB_GUIDE.md)의 덤프를 복원해 사용합니다. 공유 덤프가 UTF-16이면 UTF-8 복사본을 만든 뒤 MySQL로 가져옵니다. Flask 연결에는 `python -m pip install "PyMySQL[rsa]"`와 `HIRA_DB=mysql`, `HIRA_MYSQL_USER`, `HIRA_MYSQL_PASSWORD` 설정이 필요합니다.

## 폴더 구성

| 경로 | 내용 |
|---|---|
| [`src/`](src/) | Flask 웹앱 소스 · [`app.py`](src/app.py), [`load_db.py`](src/load_db.py), [`index.html`](src/templates/index.html), [`style.css`](src/static/style.css) |
| [`설계/`](%EC%84%A4%EA%B3%84/) | DB 스키마와 ER 다이어그램 |
| [`DB/`](DB/) | 설계에서 사용하는 원본 CSV 9개 (병원·약국정보, 상세정보 01 시설·02 세부·03 진료과목·05 의료장비·08 특수진료, 상병마스터, 진료과목별 상병 통계) |
| [`설계/schema.sql`](%EC%84%A4%EA%B3%84/schema.sql) | 테이블 생성 스크립트 |
| [`설계/ER_full.png`](%EC%84%A4%EA%B3%84/ER_full.png), [`설계/hira_ER_chen_full.drawio`](%EC%84%A4%EA%B3%84/hira_ER_chen_full.drawio) | ER 다이어그램 |
| [`DB_기말대체프로젝트_정리.pdf`](DB_%EA%B8%B0%EB%A7%90%EB%8C%80%EC%B2%B4%ED%94%84%EB%A1%9C%EC%A0%9D%ED%8A%B8_%EC%A0%95%EB%A6%AC.pdf) | 과제 요구사항·진행 정리 |

주요 테이블: `sido`, `sigungu`, `institution`, `institution_type`, `ownership_type`, `dept`, `institution_dept`, `equipment_type`, `institution_equip`, `program`, `institution_program`, `business_hours`, `disease3`, `disease`, `disease_name`, `dept_disease_stat`

## 조회 기능

| # | 기능 | 내용 |
|---|---|---|
| ① | 의료기관 검색 | 기관명·종별·설립구분·지역으로 기관 찾기 |
| ② | 진료과목별 기관 | 진료과목을 고르면 해당 기관을 전문의 수 순으로 보여줌 |
| ③ | 지역별 기관 수 | 시도/시군구·종별·개설 연도별 기관 수 집계 |
| ④ | 질병으로 진료과 찾기 | 질병명·상병코드 → 환자 수 상위 진료과 → 지역 기관 수 |
| ⑤ | 의료장비 보유 기관 | 장비 종류·최소 대수로 기관 찾기 |
| ⑥ | 요일·시각별 진료 | 요일·시각·진료과목으로 진료 중인 기관 찾기 |
| ⑦ | 지정·시범사업 참여 | 특수진료·시범사업 참여 기관 찾기 |
| ⑧ | 진료과목 다양성 순위 | 진료과목 수·전문의 합계가 많은 기관 순위 |

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
