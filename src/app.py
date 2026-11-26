# =====================================================================
# 의료기관 조회 Flask 응용프로그램
# 처리 흐름 · 검색 조건 검증 → SQL 조회 → 결과 표 표시
# SQLite 파일이 없는 첫 실행에서 load_db.py의 DB 생성 함수 호출
# =====================================================================

import os
import sqlite3
from collections import defaultdict
from datetime import timedelta
from itertools import islice

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
                     ["기관명", "종별", "설립구분", "주소", "전화번호"]),
    "departments": ("진료과목별 기관", ["dept", *AREA, "dept_equipment", "dept_weekday", "time"],
                    ["기관명", "진료과목", "전문의 수", "주소"]),
    "regions": ("시도별 의료기관 수 집계", ["type"],
                ["시도", "기관 수", "비율", "순위"]),
    "diseases": ("질병으로 진료과 찾기", ["disease", "sido"],
                 ["상병코드", "상병명", "진료과목", "순위", "환자 수", "비율", "지역 기관 수", "기관 목록"]),
    "equipment": ("의료장비 보유 기관", ["equipment", "sido", "type", "quantity"],
                  ["기관명", "장비명", "보유 대수"]),
    "hours": ("요일·시각별 진료", ["weekday", "time", "sido", "dept"],
              ["기관명", "진료 시작", "진료 종료"]),
    "programs": ("지정·시범사업 참여", ["program", "sido"],
                 ["기관명", "참여 사업", "주소"]),
    "rankings": ("진료과목 다양성 순위", ["sido", "type", "top_n"],
                 ["기관명", "진료과목 수", "순위"]),
}

# 라벨, 입력 유형, 필수 여부, 기본값, 최솟값, 최댓값
FIELDS = {
    "name": ("기관명", "text", False, "", None, None),
    "type": ("종별", "select", False, "", None, None),
    "ownership": ("설립구분", "select", False, "", None, None),
    "sido": ("시도", "select", False, "", None, None),
    "district": ("시군구", "select", False, "", None, None),
    "dept": ("진료과목", "select", True, "", None, None),
    "dept_equipment": ("보유 장비", "select", False, "", None, None),
    "dept_weekday": ("요일", "select", False, "", None, None),
    "disease": ("질병명 또는 상병코드", "text", True, "", None, None),
    "equipment": ("장비", "select", True, "", None, None),
    "quantity": ("최소 대수", "number", False, "", 1, 9999),
    "weekday": ("요일", "select", True, "", None, None),
    "time": ("시각", "time", False, "", None, None),
    "program": ("지정·시범사업", "select", True, "", None, None),
    "top_n": ("상위 기관 수", "number", False, "10", 1, 9999),
}

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
    if "dept_equipment" in fields:
        options["dept_equipment"] = query(OPTION_SQL["equipment"])
    for field in ("weekday", "dept_weekday"):
        if field in fields:
            options[field] = [{"value": str(i), "label": label} for i, label in enumerate(WEEKDAYS, 1)]
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

    if view == "regions":
        condition, params = where(filters)
        return f"""
            SELECT i.sido_nm, COUNT(*) AS total
            FROM v_institution i{condition}
            GROUP BY i.sido_nm ORDER BY total DESC, i.sido_nm
        """, params

    if view == "rankings":
        condition, params = where(filters)
        return f"""
            SELECT i.inst_nm, COUNT(*) AS dept_count
            FROM v_institution i JOIN institution_dept j ON j.inst_id = i.inst_id
            {condition} GROUP BY i.inst_id, i.inst_nm
            ORDER BY dept_count DESC, i.inst_nm, i.inst_id
        """, params

    if view == "institutions":
        columns = "i.inst_nm, i.type_nm, i.ownership_nm, i.address, i.phone"
        if values["name"]:
            filters.append(("LOWER(i.inst_nm) LIKE LOWER(?) ESCAPE '!'", f"%{escape_like(values['name'])}%"))
        if values["ownership"]:
            filters.append(("i.ownership_nm = ?", values["ownership"]))
    elif view in {"departments", "hours"}:
        source += " JOIN institution_dept j ON j.inst_id = i.inst_id"
        filters.append(("j.dept_cd = ?", values["dept"]))
        if view == "departments":
            source += " JOIN dept d ON d.dept_cd = j.dept_cd"
            columns = "i.inst_nm, d.dept_nm, j.specialist_cnt, i.address"
            order = f"j.specialist_cnt DESC, {order}"
            if values["dept_equipment"]:
                filters.append((
                    "EXISTS (SELECT 1 FROM institution_equip e WHERE e.inst_id = i.inst_id AND e.equip_cd = ? AND e.qty > 0)",
                    values["dept_equipment"],
                ))
            weekday = values["dept_weekday"]
        else:
            columns = "i.inst_nm, h.open_time, h.close_time"
            weekday = values["weekday"]
        if weekday:
            source += " JOIN business_hours h ON h.inst_id = i.inst_id"
            filters.append(("h.weekday = ?", int(weekday)))
            if values["time"]:
                time = values["time"] + ":00"
                filters += [("h.open_time <= ?", time), ("h.close_time > ?", time)]
    elif view == "equipment":
        source += " JOIN institution_equip j ON j.inst_id = i.inst_id JOIN equipment_type e ON e.equip_cd = j.equip_cd"
        columns = "i.inst_nm, e.equip_nm, j.qty"
        filters += [("j.equip_cd = ?", values["equipment"]), ("j.qty >= ?", int(values["quantity"] or 1))]
        order = f"j.qty DESC, {order}"
    elif view == "programs":
        source += " JOIN institution_program j ON j.inst_id = i.inst_id JOIN program p ON p.program_cd = j.program_cd"
        columns = "i.inst_nm, p.program_nm, i.address"
        filters.append(("j.program_cd = ?", values["program"]))

    condition, params = where(filters)
    return f"SELECT {columns}{source}{condition} ORDER BY {order}", params


def escape_like(value):
    # 입력에 포함된 SQL 패턴 문자를 일반 문자로 검색
    return value.replace("!", "!!").replace("%", "!%").replace("_", "!_")


def disease_matches(term):
    # 질병명 포함 검색 후, 일치한 이름이 없으면 상병코드 검색
    matches = query("""
        SELECT d.dis3_cd, d.dis_cd, n.dis_nm
        FROM disease d JOIN disease_name n ON n.dis_cd = d.dis_cd
        WHERE LOWER(n.dis_nm) LIKE LOWER(?) ESCAPE '!'
        ORDER BY d.dis3_cd, d.dis_cd, n.dis_nm
    """, [f"%{escape_like(term)}%"])
    if matches:
        return matches
    code = term.upper().replace(".", "")
    if not code:
        return []
    return query("""
        SELECT DISTINCT b.dis3_cd, b.dis3_cd AS dis_cd, b.dis3_nm AS dis_nm
        FROM disease3 b JOIN disease d ON d.dis3_cd = b.dis3_cd
        WHERE d.dis_cd LIKE ? ESCAPE '!' ORDER BY b.dis3_cd
    """, [f"{escape_like(code)}%"])


def disease_results(values):
    # 이름은 세부 코드로 표시하고 진료과 순위는 앞 3자리 통계로 계산
    matches = disease_matches(values["disease"])
    if not matches:
        return
    groups = sorted({row["dis3_cd"] for row in matches})
    placeholders = ", ".join("?" for _ in groups)
    stats = query(f"""
        SELECT s.dis3_cd, d.dept_cd, d.dept_nm, d.is_guide, s.patient_cnt
        FROM dept_disease_stat s JOIN dept d ON d.dept_cd = s.dept_cd
        WHERE s.dis3_cd IN ({placeholders})
        ORDER BY s.dis3_cd, s.patient_cnt DESC, d.dept_cd
    """, groups)

    # 비율의 분모는 전체 과목의 환자 수, 표시 대상은 안내 과목 상위 5개
    totals = defaultdict(int)
    guides = defaultdict(list)
    for row in stats:
        group = row["dis3_cd"]
        totals[group] += row["patient_cnt"]
        if row["is_guide"] and len(guides[group]) < 5:
            guides[group].append(row)

    condition, params = where(region_filters(values))
    local_counts = {row["dept_cd"]: row["total"] for row in query(f"""
        SELECT j.dept_cd, COUNT(*) AS total
        FROM institution_dept j JOIN v_institution i ON i.inst_id = j.inst_id
        {condition} GROUP BY j.dept_cd
    """, params)}

    for match in matches:
        group = match["dis3_cd"]
        for rank, row in enumerate(guides[group] or [{}], 1):
            patients = row.get("patient_cnt")
            dept = row.get("dept_cd")
            yield {
                "dis_cd": match["dis_cd"], "dis_nm": match["dis_nm"], "dept_nm": row.get("dept_nm"),
                "rank_no": rank if dept else None, "patient_cnt": patients,
                "share": 100 * patients / totals[group] if patients is not None and totals[group] else None,
                "local_count": local_counts.get(dept, 0) if dept else None, "dept_cd": dept,
            }


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
    if "dept_weekday" in values and values["time"] and not values["dept_weekday"]:
        return "진료 시각을 입력하려면 요일을 선택해 주세요."
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
        offset = (page - 1) * PAGE_SIZE
        if view == "diseases":
            rows = list(islice(disease_results(values), offset, offset + PAGE_SIZE + 1))
        else:
            sql, params = institution_query(view, values)
            if view == "regions":
                counts = query(sql, params)
                total = sum(row["total"] for row in counts)
                previous_count, rank = None, 0
                for position, row in enumerate(counts, 1):
                    if row["total"] != previous_count:
                        previous_count, rank = row["total"], position
                    row["share"] = 100 * row["total"] / total
                    row["rank_no"] = rank
                rows = counts[offset:offset + PAGE_SIZE + 1]
            else:
                # 상위 N 범위 안에서만 다음 페이지에 필요한 한 행을 추가 조회
                limit = PAGE_SIZE + 1
                if view == "rankings":
                    limit = max(0, min(limit, int(values["top_n"]) - offset))
                rows = query(sql + " LIMIT ? OFFSET ?", [*params, limit, offset])
                if view == "rankings":
                    for position, row in enumerate(rows, offset + 1):
                        row["rank_no"] = position
    if view == "diseases":
        values["district"] = ""  # 기존 기관 보기 링크에 필요한 기본값
    return render_template("index.html", view=view, views=VIEWS, title=title, fields=fields,
                           field_specs=FIELDS, values=values, options=options, headings=headings,
                           rows=rows[:PAGE_SIZE], next_page=len(rows) > PAGE_SIZE, page=page,
                           submitted=submitted, error=error)


if __name__ == "__main__":
    if os.getenv("HIRA_DB") != "mysql" and not DATABASE.exists():
        build_sqlite()
    app.run()
