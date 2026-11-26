# =====================================================================
# 의료기관 조회 Flask 응용프로그램
# 처리 흐름 · 검색 조건 검증 → SQL 조회 → 결과 표 표시
# SQLite 파일이 없는 첫 실행에서 load_db.py의 DB 생성 함수 호출
# =====================================================================

import os
import sqlite3
from datetime import timedelta

from flask import Flask, abort, g, render_template, request

from load_db import DATABASE, WEEKDAYS, build_sqlite, mysql_connect

# ---------------------------------------------------------------------
# 1. 화면 구성 · 조회 메뉴, 입력 항목, 결과 열 정의
# ---------------------------------------------------------------------
app = Flask(__name__)
PAGE_SIZE = 30
REGION = ["sido", "district"]
AREA = [*REGION, "type"]

VIEWS = {
    "institutions": ("의료기관 검색", ["name", "type", "ownership", *REGION],
                     ["기관명", "종별", "설립구분", "시도", "시군구", "주소", "전화번호", "개설일"]),
    "departments": ("진료과목별 기관", ["dept", *AREA, "specialists"],
                    ["기관명", "종별", "시도", "시군구", "진료과목", "전문의 수", "주소", "전화번호"]),
    "regions": ("지역별 기관 수", ["group", "sido", "type", "year_from", "year_to"],
                ["시도", "시군구", "종별", "기관 수"]),
    "diseases": ("질병으로 진료과 찾기", ["disease", "top", *REGION],
                 ["상병코드", "상병명", "진료과목", "순위", "환자 수", "비율", "지역 기관 수", "기관 목록"]),
    "equipment": ("의료장비 보유 기관", ["equipment", *AREA, "quantity"],
                  ["기관명", "종별", "시도", "시군구", "장비", "대수", "주소"]),
    "hours": ("요일·시각별 진료", ["weekday", "dept", "time", *AREA],
              ["기관명", "종별", "시군구", "진료과목", "시작", "종료", "주소", "전화번호"]),
    "programs": ("지정·시범사업 참여", ["program", *AREA],
                 ["기관명", "종별", "시도", "시군구", "사업", "주소", "전화번호"]),
    "rankings": ("진료과목 다양성 순위", ["minimum", "type", "sido"],
                 ["기관명", "종별", "시도", "시군구", "진료과목 수", "전문의 합계", "주소"]),
}

# 라벨, 입력 유형, 필수 여부, 기본값, 최솟값, 최댓값
FIELDS = {
    "name": ("기관명", "text", False, "", None, None),
    "type": ("종별", "select", False, "", None, None),
    "ownership": ("설립구분", "select", False, "", None, None),
    "sido": ("시도", "select", False, "", None, None),
    "district": ("시군구", "select", False, "", None, None),
    "dept": ("진료과목", "select", True, "", None, None),
    "specialists": ("최소 전문의 수", "number", False, "", 0, 9999),
    "group": ("집계 단위", "select", False, "sido", None, None),
    "year_from": ("개설 연도 시작", "number", False, "", 1900, 9999),
    "year_to": ("개설 연도 종료", "number", False, "", 1900, 9999),
    "disease": ("질병명 또는 상병코드", "text", True, "", None, None),
    "top": ("상위 진료과 수", "number", False, "5", 1, 50),
    "equipment": ("장비", "select", True, "", None, None),
    "quantity": ("최소 대수", "number", False, "", 1, 9999),
    "weekday": ("요일", "select", True, "", None, None),
    "time": ("시각", "time", False, "", None, None),
    "program": ("지정·시범사업", "select", True, "", None, None),
    "minimum": ("최소 진료과목 수", "number", False, "1", 1, 99),
}

BASE = "i.inst_nm, i.type_nm, i.sido_nm, i.sigungu_nm"
CONTACT = "i.address, i.phone"

OPTION_SQL = {
    "type": "SELECT type_nm AS value, type_nm AS label FROM institution_type ORDER BY label",
    "ownership": "SELECT ownership_nm AS value, ownership_nm AS label FROM ownership_type ORDER BY label",
    "sido": "SELECT sido_nm AS value, sido_nm AS label FROM sido ORDER BY label",
    "district": """SELECT g.sigungu_cd AS value, g.sigungu_nm AS label, s.sido_nm AS region
                   FROM sigungu g JOIN sido s ON g.sido_cd = s.sido_cd ORDER BY region, label""",
    "dept": """SELECT d.dept_cd AS value, d.dept_nm AS label FROM dept d
               WHERE EXISTS (SELECT 1 FROM institution_dept j WHERE j.dept_cd = d.dept_cd) ORDER BY label""",
    "equipment": "SELECT equip_cd AS value, equip_nm AS label FROM equipment_type ORDER BY label",
    "program": "SELECT program_cd AS value, program_nm AS label FROM program ORDER BY label",
}


# ---------------------------------------------------------------------
# 2. DB 처리 · 요청별 연결 관리 및 검색 조건 구성
# ---------------------------------------------------------------------
def query(sql, params=()):
    # 요청별 SQL 실행 및 결과 반환
    # 같은 요청에서 연결 재사용, MySQL 실행 시 자리표시자만 변환
    mysql = os.getenv("HIRA_DB") == "mysql"
    if "db" not in g:
        g.db = mysql_connect() if mysql else sqlite3.connect(DATABASE.as_uri() + "?mode=ro", uri=True)
        if not mysql:
            g.db.row_factory = sqlite3.Row
    if mysql:
        with g.db.cursor() as cursor:
            cursor.execute(sql.replace("?", "%s"), params)
            return cursor.fetchall()
    return [dict(row) for row in g.db.execute(sql, params)]


@app.teardown_appcontext
def close_db(_error):
    # 요청 종료 시 DB 연결 해제
    if db := g.pop("db", None):
        db.close()


def options_for(fields):
    # 조회 화면의 선택 목록 구성
    options = {field: query(OPTION_SQL[field]) for field in fields if field in OPTION_SQL}
    options["group"] = [{"value": "sido", "label": "시도별"}, {"value": "district", "label": "시군구별"}]
    options["weekday"] = [{"value": str(i), "label": label} for i, label in enumerate(WEEKDAYS, 1)]
    return options


def region_filters(values):
    # 시도·시군구·종별 SQL 필터 생성
    columns = {"sido": "sido_nm", "district": "sigungu_cd", "type": "type_nm"}
    return [(f"i.{col} = ?", values[key]) for key, col in columns.items() if values.get(key)]


def where(filters):
    # WHERE 절과 바인딩 값 조합
    return (" WHERE " + " AND ".join(clause for clause, _ in filters) if filters else "",
            [value for _, value in filters])


# ---------------------------------------------------------------------
# 3. 조회 SQL · 기관 검색, 지역 집계 및 질병 안내
# ---------------------------------------------------------------------
def institution_query(view, values):
    # 조회 메뉴별 의료기관 검색 SQL 생성
    filters = region_filters(values)
    source = " FROM v_institution i"
    order = "i.inst_nm, i.inst_id"
    group = ""
    columns = f"{BASE}, {CONTACT}"

    if view == "institutions":
        columns = f"i.inst_nm, i.type_nm, i.ownership_nm, i.sido_nm, i.sigungu_nm, {CONTACT}, i.opened_on"
        if values["name"]:
            filters.append(("INSTR(LOWER(i.inst_nm), LOWER(?)) > 0", values["name"]))
        if values["ownership"]:
            filters.append(("i.ownership_nm = ?", values["ownership"]))
    elif view in {"departments", "hours", "rankings"}:
        source += " JOIN institution_dept j ON j.inst_id = i.inst_id"
        if view == "rankings":
            columns = f"{BASE}, COUNT(*) AS dept_count, SUM(j.specialist_cnt) AS specialists, i.address"
            group = f" GROUP BY i.inst_id, {BASE}, i.address HAVING COUNT(*) >= ?"
            order = f"dept_count DESC, specialists DESC, {order}"
        else:
            source += " JOIN dept d ON d.dept_cd = j.dept_cd"
            filters.append(("j.dept_cd = ?", values["dept"]))
            if view == "departments":
                columns = f"{BASE}, d.dept_nm, j.specialist_cnt, {CONTACT}"
                order = f"j.specialist_cnt DESC, {order}"
                if values["specialists"]:
                    filters.append(("j.specialist_cnt >= ?", int(values["specialists"])))
            else:
                source += " JOIN business_hours h ON h.inst_id = i.inst_id"
                columns = f"i.inst_nm, i.type_nm, i.sigungu_nm, d.dept_nm, h.open_time, h.close_time, {CONTACT}"
                filters.append(("h.weekday = ?", int(values["weekday"])))
                if values["time"]:
                    time = values["time"] + ":00"
                    filters += [("h.open_time <= ?", time), ("h.close_time > ?", time)]
    elif view == "regions":
        district = values["group"] == "district"
        columns = f"i.sido_nm, {'i.sigungu_nm' if district else 'NULL AS sigungu_nm'}, i.type_nm, COUNT(*) AS total"
        group = " GROUP BY i.sido_nm, i.type_nm" + (", i.sigungu_nm, i.sigungu_cd" if district else "")
        order = "total DESC, i.sido_nm, sigungu_nm, i.type_nm"
        if values["year_from"]:
            filters.append(("i.opened_on >= ?", values["year_from"].zfill(4) + "-01-01"))
        if values["year_to"]:
            filters.append(("i.opened_on <= ?", values["year_to"].zfill(4) + "-12-31"))
    elif view == "equipment":
        source += " JOIN institution_equip j ON j.inst_id = i.inst_id JOIN equipment_type e ON e.equip_cd = j.equip_cd"
        columns = f"{BASE}, e.equip_nm, j.qty, i.address"
        filters += [("j.equip_cd = ?", values["equipment"]), ("j.qty >= ?", int(values["quantity"] or 1))]
        order = f"j.qty DESC, {order}"
    elif view == "programs":
        source += " JOIN institution_program j ON j.inst_id = i.inst_id JOIN program p ON p.program_cd = j.program_cd"
        columns = f"{BASE}, p.program_nm, {CONTACT}"
        filters.append(("j.program_cd = ?", values["program"]))

    condition, params = where(filters)
    if view == "rankings":
        params.append(int(values["minimum"]))
    return f"SELECT {columns}{source}{condition}{group} ORDER BY {order}", params


def disease_query(values):
    # 질병명 포함 검색과 진료과 순위·지역별 기관 수 조회
    # 상병명은 세부 코드로 표시하고 진료과 순위는 앞 3자리 통계로 계산
    # 지역 조건은 진료과별 기관 수 집계에만 적용
    condition, params = where(region_filters(values))
    search = values["disease"]
    code = search.upper().replace(".", "")
    return f"""
        WITH name_matches AS (
            SELECT DISTINCT d.dis3_cd, d.dis_cd, n.dis_nm
            FROM disease d JOIN disease_name n ON n.dis_cd = d.dis_cd
            WHERE INSTR(LOWER(n.dis_nm), LOWER(?)) > 0
        ), matches AS (
            SELECT dis3_cd, dis_cd, dis_nm FROM name_matches
            UNION ALL
            SELECT b.dis3_cd, b.dis3_cd, b.dis3_nm
            FROM disease3 b
            WHERE NOT EXISTS (SELECT 1 FROM name_matches)
              AND EXISTS (SELECT 1 FROM disease d WHERE d.dis3_cd = b.dis3_cd AND INSTR(d.dis_cd, ?) = 1)
        ), matched AS (
            SELECT DISTINCT dis3_cd FROM matches
        ), ranked AS (
            SELECT s.dis3_cd, d.dept_cd, d.dept_nm, d.is_guide, s.patient_cnt,
                   ROUND(100.0 * s.patient_cnt / NULLIF(SUM(s.patient_cnt) OVER (PARTITION BY s.dis3_cd), 0), 1) AS share
            FROM dept_disease_stat s JOIN dept d ON d.dept_cd = s.dept_cd
            JOIN matched m ON m.dis3_cd = s.dis3_cd
        ), guide AS (
            SELECT ranked.*,
                   ROW_NUMBER() OVER (PARTITION BY dis3_cd ORDER BY patient_cnt DESC, dept_cd) AS rank_no
            FROM ranked WHERE is_guide = 1
        ), local_counts AS (
            SELECT j.dept_cd, COUNT(*) AS total FROM institution_dept j
            JOIN v_institution i ON i.inst_id = j.inst_id{condition} GROUP BY j.dept_cd
        )
        SELECT m.dis_cd, m.dis_nm, r.dept_nm, r.rank_no, r.patient_cnt, r.share,
               CASE WHEN r.dept_cd IS NOT NULL THEN COALESCE(c.total, 0) END AS local_count, r.dept_cd
        FROM matches m LEFT JOIN guide r ON r.dis3_cd = m.dis3_cd AND r.rank_no <= ?
        LEFT JOIN local_counts c ON c.dept_cd = r.dept_cd
        ORDER BY CASE WHEN m.dis3_cd = ? THEN 0 ELSE 1 END, m.dis3_cd, m.dis_cd, m.dis_nm, r.rank_no
    """, [search, code or search, *params, int(values["top"]), code[:3]]


# ---------------------------------------------------------------------
# 4. 화면 처리 · 입력 검증, 결과 표, 페이지 이동
# ---------------------------------------------------------------------
def validate(fields, values, options):
    # 검색 조건의 필수값·선택값·입력 범위 검증
    for field in fields:
        label, kind, required, _, minimum, maximum = FIELDS[field]
        value = values[field]
        if required and not value:
            return f"{label} 항목을 입력해 주세요."
        if not value:
            continue
        if kind == "select" and not any(item["value"] == value for item in options[field]):
            return f"{label} 항목을 목록에서 선택해 주세요."
        if kind == "number" and (not value.isascii() or not value.isdecimal()
                                 or len(value) > 4 or not minimum <= int(value) <= maximum):
            return f"{label} 항목은 {minimum}~{maximum} 범위에서 입력해 주세요."
        if kind == "time" and (len(value) != 5 or value[2] != ":" or
                               not (value[:2].isdigit() and value[3:].isdigit()) or
                               not (value.isascii() and int(value[:2]) < 24 and int(value[3:]) < 60)):
            return "시각을 올바르게 입력해 주세요."
    if values.get("year_from") and values.get("year_to") and int(values["year_from"]) > int(values["year_to"]):
        return "개설 연도 끝은 시작 연도와 같거나 이후여야 합니다."
    return None


@app.template_filter("cell")
def format_cell(value):
    # 빈 값과 시간 값의 표시 형식 변환
    if value is None or value == "":
        return "—"
    if isinstance(value, timedelta):
        hours, remainder = divmod(int(value.total_seconds()), 3600)
        return f"{hours:02d}:{remainder // 60:02d}"
    if isinstance(value, str) and len(value) == 8 and value[2] == value[5] == ":":
        return value[:5]
    return value


@app.get("/")
@app.get("/<view>")
def search(view="institutions"):
    # 조회 요청 검증 및 페이지별 결과 표시
    if view not in VIEWS:
        abort(404)
    title, fields, headings = VIEWS[view]
    options = options_for(fields)
    values = {field: request.args.get(field, FIELDS[field][3]).strip() or FIELDS[field][3] for field in fields}
    submitted = bool(request.args)
    page = max(1, min(100000, request.args.get("page", 1, type=int)))
    error = validate(fields, values, options) if submitted else None
    rows = []
    if submitted and not error:
        # 한 행을 더 조회해 다음 페이지가 있는지 판단
        sql, params = disease_query(values) if view == "diseases" else institution_query(view, values)
        rows = query(sql + " LIMIT ? OFFSET ?", [*params, PAGE_SIZE + 1, (page - 1) * PAGE_SIZE])
    return render_template("index.html", view=view, views=VIEWS, title=title, fields=fields,
                           field_specs=FIELDS, values=values, options=options, headings=headings,
                           rows=rows[:PAGE_SIZE], next_page=len(rows) > PAGE_SIZE, page=page,
                           submitted=submitted, error=error)


if __name__ == "__main__":
    if os.getenv("HIRA_DB") != "mysql" and not DATABASE.exists():
        build_sqlite()
    app.run()
