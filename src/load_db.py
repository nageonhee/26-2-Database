# =====================================================================
# 의료기관 데이터 적재
# 처리 흐름 · 설계 SQL 적용 → CSV 정제 및 적재 → 조회용 DB 생성
# 원본 · 건강보험심사평가원 의료기관 및 상병 CSV
# =====================================================================

import argparse
import csv
import os
import re
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date
from itertools import chain
from pathlib import Path
from tempfile import NamedTemporaryFile

ROOT = Path(__file__).resolve().parent
DATABASE = ROOT / "hira.sqlite3"
PROJECT = ROOT.parent
SCHEMA = PROJECT / "설계" / "schema.sql"
WEEKDAYS = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
GUIDE_EXCLUDED = set(
    "일반의 한방 응급의학과 진단검사의학과 영상의학과 병리과 핵의학과 "
    "방사선종양학과 예방의학과 직업환경의학과 보건기관의과 구강병리과 영상치의학과".split()
)


# ---------------------------------------------------------------------
# 1. 적재 공통 처리 · CSV 읽기, 스키마 변환, 원본 값 정제
# ---------------------------------------------------------------------
def csv_rows(pattern):
    # 원본 CSV를 열 이름 기준으로 읽기
    if isinstance(pattern, int):
        pattern = f"{pattern}.*.csv"
    path, = (PROJECT / "DB").glob(pattern)
    with path.open(encoding="cp949", newline="") as file:
        yield from csv.DictReader(file)


def schema_parts():
    # 설계 SQL의 테이블·뷰 생성 구문 추출
    source = SCHEMA.read_text(encoding="utf-8-sig")
    return re.findall(
        r"^CREATE (?:TABLE|VIEW) .+?(?=;[ \t]*$)",
        re.sub(r"--[^\n]*", "", source),
        re.M | re.S,
    )


def sqlite_schema(db):
    # SQLite용 테이블·뷰 생성
    indexes = []
    for statement in schema_parts():
        table = statement.split()[2]
        for index, columns in re.findall(r"^\s+KEY (\w+) (\([^\n]+\)),?$", statement, re.M):
            indexes.append(f"CREATE INDEX {index} ON {table} {columns}")
        statement = re.sub(r"^\s+KEY [^\n]+\n", "\n", statement, flags=re.M)
        statement = re.sub(r"\s+COMMENT\s*(?:=\s*)?'[^']*'", "", statement)
        statement = re.sub(r" ENGINE=InnoDB| CHARACTER SET ascii COLLATE ascii_bin| UNSIGNED", "", statement)
        statement = re.sub(r"UNIQUE KEY \w+ ", "UNIQUE ", statement)
        statement = statement.replace("LEFT(dis_cd, 3)", "substr(dis_cd, 1, 3)")
        statement = statement.replace(
            "REGEXP_LIKE(dis3_cd, '^[A-Z][0-9]{2}$', 'c')",
            "dis3_cd GLOB '[A-Z][0-9][0-9]'",
        )
        db.execute(statement)
    return indexes


def insert(db, table, rows):
    # 지정 테이블에 데이터 일괄 삽입
    rows = iter(rows)
    first = next(rows, None)
    if first is None:
        return
    placeholders = ", ".join(["?"] * len(first))
    db.executemany(f"INSERT INTO {table} VALUES ({placeholders})", chain([first], rows))


def integer(value):
    # CSV 숫자 문자열의 정수 변환
    return int(value.strip().replace(",", "") or 0)


def coordinate(value, low, high):
    # 허용 범위 내 좌표의 숫자 변환
    number = float(value) if value.strip() else None
    return number if number is not None and low <= number <= high else None


def opened_on(value):
    # 유효한 개설일의 날짜 문자열 변환
    if value and value != "1900-01-01":
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            pass
    return None


def clock(value):
    # 진료시간의 시·분·초 형식 변환
    value = value.strip()
    if not re.fullmatch(r"[0-9]{1,4}", value):
        return None
    hour, minute = divmod(int(value), 100)
    if hour < 24 and minute < 60 or (hour, minute) == (24, 0):
        return f"{hour:02d}:{minute:02d}:00"
    return None


# ---------------------------------------------------------------------
# 2. 기관 데이터 · 기본 정보와 진료과·장비·운영시간 연결
# ---------------------------------------------------------------------
def load_institutions(db):
    # 의료기관 및 지역·종별·설립구분 데이터 적재
    # 암호화요양기호로 병원·약국 기본 정보와 시설 정보 연결
    base = {}
    for number in (1, 2):
        for row in csv_rows(number):
            key = row["암호화요양기호"]
            base[key] = (
                row["병원홈페이지"] or None if number == 1 else None,
                coordinate(row["좌표(X)"], 120, 135),
                coordinate(row["좌표(Y)"], 30, 40),
            )

    facilities = list(csv_rows(3))
    sido_names = defaultdict(Counter)
    districts, types, ownership = {}, {}, {}
    for row in facilities:
        sido, district = row["시도코드"], row["시군구코드"]
        sido_names[sido][row["시도코드명"]] += 1
        districts[district] = (district, row["시군구코드명"], sido)
        types[row["종별코드"]] = row["종별코드명"]
        ownership[row["설립구분코드"]] = row["설립구분코드명"]
    insert(db, "sido", ((code, names.most_common(1)[0][0]) for code, names in sido_names.items()))
    insert(db, "sigungu", districts.values())
    insert(db, "institution_type", types.items())
    insert(db, "ownership_type", ownership.items())

    identifiers, institutions = {}, []
    for inst_id, row in enumerate(facilities, 1):
        key = row["암호화요양기호"]
        identifiers[key] = inst_id
        homepage, longitude, latitude = base[key]
        zip_code = row["우편번호"].strip()
        institutions.append((
            inst_id, key, row["요양기관명"], row["종별코드"], row["설립구분코드"],
            row["시군구코드"], row["읍면동"] or None, zip_code if zip_code and zip_code != "00000" else None,
            row["주소"], row["전화번호"] or None, opened_on(row["개설일자"]),
            longitude, latitude, homepage,
        ))
    insert(db, "institution", institutions)
    return identifiers


def load_relation(db, ids, number, lookup, relation, code_col, name_col, count_col=None):
    # 분류 코드와 기관별 연결 데이터 적재
    names = defaultdict(Counter)
    links = {}
    for row in csv_rows(number):
        code = row[code_col]
        names[code][row[name_col]] += 1
        inst_id = ids.get(row["암호화요양기호"])
        if inst_id is not None:
            links[inst_id, code] = integer(row[count_col]) if count_col else None
    labels = {code: counts.most_common(1)[0][0] for code, counts in names.items()}
    if lookup == "dept":
        insert(db, lookup, ((code, name, int(name not in GUIDE_EXCLUDED)) for code, name in labels.items()))
    else:
        insert(db, lookup, labels.items())
    insert(db, relation, ((inst, code, count) if count_col else (inst, code)
                          for (inst, code), count in links.items()))
    return labels


def load_hours(db, ids):
    # 기관별 요일 및 진료시간 추출
    for row in csv_rows(4):
        inst_id = ids.get(row["암호화요양기호"])
        if inst_id is None:
            continue
        for day, weekday in enumerate(WEEKDAYS, 1):
            start = clock(row[f"진료시작시간_{weekday}"])
            end = clock(row[f"진료종료시간_{weekday}"])
            if start and end and start < end:
                yield inst_id, day, start, end


# ---------------------------------------------------------------------
# 3. 질병 데이터 · 상병마스터와 진료과별 환자 통계 연결
# ---------------------------------------------------------------------
def load_diseases(db, departments):
    # 상병마스터 및 진료과별 환자 통계 적재
    # 세부 상병코드 앞 3자리로 통계와 연결하고 중복 상병명 제거
    groups, names, codes, titles = {}, {}, {}, {}
    for row in csv_rows("*상병마스터*.csv"):
        code = row["상병기호"].strip().upper()
        group = code[:3]
        if not re.fullmatch(r"[A-Z][0-9]{2}", group):
            continue
        name = row["한글명"].strip()
        groups.setdefault(group, name)
        if group == code:
            titles.setdefault(group, name)
        codes[code] = group
        names.setdefault((code, name), row["영문명"].strip() or None)
    groups.update(titles)
    insert(db, "disease3", groups.items())
    insert(db, "disease", codes.items())
    insert(db, "disease_name", ((code, name, english) for (code, name), english in names.items()))

    dept_codes = {name: code for code, name in departments.items()}
    stats = []
    for row in csv_rows("*상병 통계*.csv"):
        dept = row["진료과목"].strip()
        if dept in {"일반의", "보건기관의과", "한방"}:
            continue
        stats.append((
            dept_codes[dept], row["주상병코드"].strip(),
            *(integer(value) for value in list(row.values())[3:]),
        ))
    insert(db, "dept_disease_stat", stats)


# ---------------------------------------------------------------------
# 4. DB 구축 · SQLite 생성 및 선택적 MySQL 적재
# ---------------------------------------------------------------------
def build_sqlite():
    # 원본 데이터로 SQLite DB 파일 생성
    # 임시 DB 적재가 성공한 뒤 기존 파일 교체
    with NamedTemporaryFile(dir=ROOT, suffix=".sqlite3.tmp", delete=False) as temporary:
        path = Path(temporary.name)
    try:
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("PRAGMA foreign_keys = ON")
            indexes = sqlite_schema(db)
            ids = load_institutions(db)
            departments = load_relation(db, ids, 5, "dept", "institution_dept",
                                        "진료과목코드", "진료과목코드명", "과목별 전문의수")
            load_relation(db, ids, 7, "equipment_type", "institution_equip", "장비코드", "장비코드명", "장비대수")
            load_relation(db, ids, 10, "program", "institution_program", "검색코드", "검색코드명")
            insert(db, "business_hours", load_hours(db, ids))
            load_diseases(db, departments)
            for statement in indexes:
                db.execute(statement)
            db.execute("ANALYZE")
        path.replace(DATABASE)
    finally:
        path.unlink(missing_ok=True)


def mysql_connect():
    # 환경 변수에 지정된 MySQL DB 연결
    import pymysql
    return pymysql.connect(
        host=os.getenv("HIRA_MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("HIRA_MYSQL_PORT", "3306")),
        user=os.getenv("HIRA_MYSQL_USER", "root"),
        password=os.getenv("HIRA_MYSQL_PASSWORD", ""),
        database=os.getenv("HIRA_MYSQL_DATABASE", "hira_db"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def load_mysql():
    # SQLite 데이터를 MySQL의 빈 테이블로 복사
    with closing(sqlite3.connect(DATABASE)) as source, mysql_connect() as target:
        with target.cursor() as cursor:
            cursor.execute("SHOW TABLES")
            existing = {next(iter(row.values())) for row in cursor.fetchall()}
            for statement in schema_parts():
                name = statement.split()[2]
                if name not in existing:
                    cursor.execute(statement)
            tables = [statement.split()[2] for statement in schema_parts() if statement.startswith("CREATE TABLE")]
            for name in tables:
                cursor.execute(f"SELECT 1 FROM {name} LIMIT 1")
                if cursor.fetchone():
                    raise RuntimeError(f"MySQL의 {name} 테이블에 데이터가 있습니다. 빈 DB를 지정하세요.")
            for name in tables:
                records = source.execute(f"SELECT * FROM {name}")
                values = ", ".join(["%s"] * len(records.description))
                while batch := records.fetchmany(2000):
                    cursor.executemany(f"INSERT INTO {name} VALUES ({values})", batch)
        target.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="원본 CSV를 의료기관 조회 DB에 적재합니다.")
    parser.add_argument("--mysql", action="store_true", help="빈 MySQL 데이터베이스에도 적재")
    args = parser.parse_args()
    build_sqlite()
    print(f"SQLite 적재 완료 {DATABASE}")
    if args.mysql:
        load_mysql()
        print("MySQL 적재 완료")
