# 의료기관 조회

Flask와 MySQL을 사용하는 의료기관 조회 웹입니다. 조회 기능 8개를 제공합니다.

## 팀 MySQL DB로 실행

- [`app.py`](app.py)는 Flask 웹을 실행하고 팀의 MySQL `hira_db`를 조회합니다.
- [`schema.sql`](schema.sql)은 MySQL 테이블 16개와 조회용 뷰를 생성합니다.
- [`load_data.py`](load_data.py)는 기본 테이블 12개, [`load_disease.py`](load_disease.py)는 질병 테이블 4개를 적재합니다.
- [`templates/index.html`](templates/index.html)과 [`static/style.css`](static/style.css)는 검색 화면과 결과 표를 구성합니다.

```powershell
python -m pip install Flask "PyMySQL[rsa]"
```

팀 DB가 이미 준비되어 있으면 아래 Flask 실행 명령으로 진행합니다. 처음 구축하는 경우 프로젝트 루트에서 `cd src`로 이동한 뒤 다음 순서로 준비합니다.

1. 새 MySQL 환경에 이 폴더의 `schema.sql`을 적용합니다.
2. `python -m pip install pandas`로 적재 라이브러리를 설치합니다.
3. `python load_data.py --dir ../DB`로 기본 데이터를 적재합니다.
4. `python load_disease.py --stat "<통계 CSV 경로>" --master "<상병마스터 CSV 경로>"`로 질병 데이터를 적재합니다. 두 CSV는 상위 [`DB/`](../DB/) 폴더에 있습니다.

두 적재 명령에 실제 MySQL 접속 정보를 지정합니다. 아래 Flask 실행 명령은 프로젝트 루트에서 시작하는 기준입니다. 이미 `src`에 있으면 `cd src`를 건너뜁니다.

```powershell
cd src
$env:HIRA_MYSQL_HOST = '127.0.0.1'
$env:HIRA_MYSQL_USER = 'root'
$env:HIRA_MYSQL_DATABASE = 'hira_db'
$env:HIRA_MYSQL_PASSWORD = Read-Host 'MySQL 비밀번호' -MaskInput
python app.py
```

브라우저에서 `http://127.0.0.1:5000`을 엽니다.

## Firebase Spark 데모

공개 데모인 https://hira-search-261119.web.app 은 기존 스냅샷을 브라우저에서 조회합니다. 팀 MySQL에 연결하는 로컬 Flask와 별도로 배포됩니다.

## 데이터 사용 범위

기관 정보는 병원·약국·시설 CSV를 암호화요양기호로 연결합니다. 진료과목, 장비, 진료시간, 지정·참여 사업, 상병마스터와 2025년 상병 통계를 적재합니다. 현재 스키마에 따라 병상, 전문병원 분야, 의료인력·기타인력, 교통, 식대가산, 간호등급은 적재 대상에서 제외합니다.

④ 질병으로 진료과 찾기에서 질병명에 포함된 단어를 검색할 수 있습니다. 결과의 `기관 보기`를 누르면 해당 진료과와 선택한 지역을 유지한 채 ② 진료과목별 기관 조회로 이동합니다.

시도 또는 사업 코드에 원본 표기가 여러 개 있으면 코드별 최빈 표기를 사용합니다. 질병명 검색은 검색어를 포함하는 상병명과 해당 코드를 표시합니다. 진료과 순위는 상병코드 앞 3자리 통계와 설계의 안내 제외 진료과 목록을 적용합니다. 비율은 해당 3단 상병의 모든 통계 행에 있는 환자 수 합계를 기준으로 계산합니다. 시각 조회는 기관 단위 등록 시간을 사용합니다.
