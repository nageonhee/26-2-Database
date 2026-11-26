"""
건강보험심사평가원 「전국 병의원 및 약국 현황」 CSV -> MySQL(hira_db) 적재 스크립트

사용법:
    python load_data.py --dir <CSV가 들어있는 폴더> [--host localhost --user hira --password hira1234 --db hira_db]

- 파일 이름이 깨져 있어도 되도록 '헤더(컬럼명)'로 파일 종류를 자동 판별한다.
- 원본은 CP949 인코딩이다.
- 정제 내용은 실행 끝에 '정제 보고'로 출력된다 (보고서의 '데이터 정제' 절에 그대로 쓸 수 있음).
"""
import argparse, csv, glob, os, sys
from collections import Counter
import pandas as pd
import pymysql

K = '암호화요양기호'

# ---------------------------------------------------------------- 파일 판별
def read_csv(path):
    return pd.read_csv(path, encoding='cp949', dtype=str, keep_default_na=False)

def detect(folder):
    found = {}
    code_files = []                                   # 헤더가 같은 '검색코드' 파일(08, 09)
    for p in sorted(glob.glob(os.path.join(folder, '*.csv'))):
        with open(p, encoding='cp949', newline='') as f:
            h = next(csv.reader(f))
        cols = set(h)
        if '총의사수' in cols:                 found['hosp'] = p
        elif '설립구분코드' in cols:           found['fac'] = p
        elif '좌표(X)' in cols and '종별코드' in cols: found['pharm'] = p
        elif '진료시작시간_월요일' in cols:    found['detail'] = p
        elif '진료과목코드' in cols:           found['dept'] = p
        elif '장비코드' in cols:               found['equip'] = p
        elif '검색코드' in cols:               code_files.append(p)
        # 식사료(06)·간호등급(07)·교통(04)은 사용하지 않는다
    if code_files:                                    # 08(특수진료)이 09(전문병원)보다 크다. 09는 사용하지 않는다
        code_files.sort(key=os.path.getsize, reverse=True)
        found['program'] = code_files[0]
    need = {'hosp','pharm','fac','detail','dept','equip','program'}
    miss = need - set(found)
    if miss:
        sys.exit(f'필요한 파일을 찾지 못함: {sorted(miss)}  (폴더: {folder})')
    return found

# ---------------------------------------------------------------- 보조
def nul(v):
    return None if v is None or v == '' else v

def to_int(v):
    return int(v) if v not in ('', None) else 0

def parse_hhmm(v):
    """'900'->09:00:00, '1930'->19:30:00. 해석 불가/0 이면 None"""
    if not v or not v.isdigit() or len(v) < 3:
        return None
    v = v.zfill(4); hh, mm = int(v[:2]), int(v[2:])
    if hh > 24 or mm > 59 or (hh == 24 and mm > 0) or v == '0000':
        return None
    return f'{hh:02d}:{mm:02d}:00'

def insert(cur, table, cols, rows, chunk=5000):
    if not rows:
        return 0
    sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join(['%s']*len(cols))})"
    for i in range(0, len(rows), chunk):
        cur.executemany(sql, rows[i:i+chunk])
    return len(rows)

# ---------------------------------------------------------------- 메인
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--host', default='localhost'); ap.add_argument('--port', type=int, default=3306)
    ap.add_argument('--user', default='hira');     ap.add_argument('--password', default='hira1234')
    ap.add_argument('--db', default='hira_db')
    a = ap.parse_args()

    files = detect(a.dir)
    print('[파일 판별]'); [print(f'  {k:9s} <- {os.path.basename(v)}') for k, v in files.items()]
    D = {k: read_csv(v) for k, v in files.items()}
    rep = []                                          # 정제 보고

    hosp, pharm, fac = D['hosp'], D['pharm'], D['fac']

    # ---- (1) 의료기관 통합: 병원 + 약국 (공통 속성이 시설정보 파일과 100% 일치함을 확인)
    common = [K, '요양기관명', '종별코드', '종별코드명', '시도코드', '시도코드명', '시군구코드',
              '시군구코드명', '읍면동', '우편번호', '주소', '전화번호', '개설일자', '좌표(X)', '좌표(Y)']
    inst = pd.concat([hosp[common + ['병원홈페이지']], pharm[common].assign(병원홈페이지='')], ignore_index=True)
    assert inst[K].is_unique, '요양기호 중복'
    inst = inst.merge(fac[[K, '설립구분코드', '설립구분코드명']], on=K, how='left', validate='1:1')
    assert inst['설립구분코드'].notna().all()
    ids = {y: i + 1 for i, y in enumerate(sorted(inst[K]))}          # 대리키 부여(정렬 순)

    # ---- (2) 코드 테이블
    #  시도: 코드당 명칭이 2개인 경우(360000: 전남광주 6,531 / 전남 3) -> 최빈값으로 통일
    cnt = inst.groupby(['시도코드', '시도코드명']).size().reset_index(name='n').sort_values('n', ascending=False)
    sido = cnt.drop_duplicates('시도코드').set_index('시도코드')['시도코드명'].to_dict()
    fixed = int(len(inst) - sum(inst['시도코드명'].eq(inst['시도코드'].map(sido))))
    rep.append(f'시도명 통일: 시도코드 1개에 명칭이 2개(전남/전남광주)인 {fixed}건을 최빈 명칭으로 통일')
    sigungu = inst.drop_duplicates('시군구코드').set_index('시군구코드')[['시군구코드명', '시도코드']]
    types = inst.drop_duplicates('종별코드').set_index('종별코드')['종별코드명'].to_dict()
    owners = inst.drop_duplicates('설립구분코드').set_index('설립구분코드')['설립구분코드명'].to_dict()

    # ---- (3) institution 행
    inst_rows = []
    zip_bad, date_unknown = 0, 0
    cols = list(inst.columns)
    ix = {c: i for i, c in enumerate(cols)}
    for r in inst.itertuples(index=False, name=None):
        z = r[ix['우편번호']]
        if not (len(z) == 5 and z.isdigit()) or z == '00000':      # 00000(placeholder), 6자리 등 비정상값
            zip_bad += 1; z = ''
        od = r[ix['개설일자']]
        if od == '1900-01-01':                                     # 미상 placeholder로 추정
            date_unknown += 1; od = ''
        inst_rows.append((ids[r[ix[K]]], r[ix[K]], r[ix['요양기관명']], r[ix['종별코드']], r[ix['설립구분코드']],
                          r[ix['시군구코드']], nul(r[ix['읍면동']]), nul(z), r[ix['주소']], nul(r[ix['전화번호']]),
                          nul(od), nul(r[ix['좌표(X)']]), nul(r[ix['좌표(Y)']]), nul(r[ix['병원홈페이지']])))
    rep.append(f'우편번호: 00000(placeholder)·5자리 아님 {zip_bad}건 -> NULL')
    rep.append(f'개설일자: 1900-01-01(미상 placeholder로 추정) {date_unknown}건 -> NULL')
    rep.append(f"좌표 공란 {int((inst['좌표(X)']=='').sum())}건 -> NULL")

    # ---- (6) 진료과목  (선택진료 의사수: 전부 0 -> 제외)
    dept = D['dept']
    assert (dept['선택진료 의사수'].astype(int) == 0).all()
    rep.append(f"진료과목: '선택진료 의사수' {len(dept):,}행 전부 0 -> 컬럼 제외")
    dept_code = dept.drop_duplicates('진료과목코드').set_index('진료과목코드')['진료과목코드명'].to_dict()
    dept_rows = [(ids[r[0]], r[1], to_int(r[2])) for r in dept[[K, '진료과목코드', '과목별 전문의수']].itertuples(index=False, name=None)]

    # ---- (7) 장비
    eq = D['equip']
    equip_code = eq.drop_duplicates('장비코드').set_index('장비코드')['장비코드명'].to_dict()
    equip_rows = [(ids[r[0]], r[1], to_int(r[2])) for r in eq[[K, '장비코드', '장비대수']].itertuples(index=False, name=None)]

    # ---- (8) 특수진료·시범사업: 코드명 불일치 통일 + 완전중복 제거
    pg = D['program'].copy()
    names = pg.groupby('검색코드')['검색코드명'].unique()
    multi = names[names.apply(len) > 1]
    canon = {}
    for code, ns in multi.items():
        canon[code] = sorted(ns)[-1]          # 사전순 마지막(= 'TG': '...재택의료 시범기관') 채택
        rep.append(f"검색코드 {code}: 명칭 2개 {list(ns)} -> '{canon[code]}'로 통일")
    pg['검색코드명'] = [canon.get(c, n) for c, n in zip(pg['검색코드'], pg['검색코드명'])]
    before = len(pg)
    pg = pg.drop_duplicates([K, '검색코드'])
    rep.append(f'특수진료·시범사업: 중복행 {before-len(pg):,}건 제거 ({before:,} -> {len(pg):,})')
    prog_code = pg.drop_duplicates('검색코드').set_index('검색코드')['검색코드명'].to_dict()
    prog_rows = [(ids[r[0]], r[1]) for r in pg[[K, '검색코드']].itertuples(index=False, name=None)]

    # ---- (11) 요일별 진료시간
    dt = D['detail']
    days = [('월', 1), ('화', 2), ('수', 3), ('목', 4), ('금', 5), ('토', 6), ('일', 7)]
    hours_rows, bad_fmt, bad_order = [], 0, 0
    for r in dt.to_dict('records'):
        for nm, no in days:
            s_raw, e_raw = r[f'진료시작시간_{nm}요일'], r[f'진료종료시간_{nm}요일']
            if s_raw == '' and e_raw == '':
                continue
            s, e = parse_hhmm(s_raw), parse_hhmm(e_raw)
            if s is None or e is None:
                bad_fmt += 1; continue
            if s >= e:
                bad_order += 1; continue
            hours_rows.append((ids[r[K]], no, s, e))
    rep.append(f'진료시간: 형식 오류/0값 {bad_fmt:,}건, 시작>=종료 {bad_order:,}건 제외(종료시각을 12시간제로 입력한 오기가 대부분이라 보정하지 않고 제외) -> {len(hours_rows):,}건 적재')

    # ---------------------------------------------------------------- 적재
    con = pymysql.connect(host=a.host, port=a.port, user=a.user, password=a.password, database=a.db,
                          charset='utf8mb4', autocommit=False)
    cur = con.cursor()
    try:
        n = {}
        n['sido']             = insert(cur, 'sido', ['sido_cd', 'sido_nm'], sorted(sido.items()))
        n['sigungu']          = insert(cur, 'sigungu', ['sigungu_cd', 'sigungu_nm', 'sido_cd'],
                                       [(c, r['시군구코드명'], r['시도코드']) for c, r in sigungu.iterrows()])
        n['institution_type'] = insert(cur, 'institution_type', ['type_cd', 'type_nm'], sorted(types.items()))
        n['ownership_type']   = insert(cur, 'ownership_type', ['ownership_cd', 'ownership_nm'], sorted(owners.items()))
        n['dept']             = insert(cur, 'dept', ['dept_cd', 'dept_nm'], sorted(dept_code.items()))
        n['equipment_type']   = insert(cur, 'equipment_type', ['equip_cd', 'equip_nm'], sorted(equip_code.items()))
        n['program']          = insert(cur, 'program', ['program_cd', 'program_nm'], sorted(prog_code.items()))
        n['institution']      = insert(cur, 'institution',
            ['inst_id', 'ykiho', 'inst_nm', 'type_cd', 'ownership_cd', 'sigungu_cd', 'emd_nm', 'zip_cd', 'address',
             'phone', 'opened_on', 'longitude', 'latitude', 'homepage'], inst_rows)
        n['institution_dept']  = insert(cur, 'institution_dept', ['inst_id', 'dept_cd', 'specialist_cnt'], dept_rows)
        n['institution_equip'] = insert(cur, 'institution_equip', ['inst_id', 'equip_cd', 'qty'], equip_rows)
        n['institution_program']   = insert(cur, 'institution_program', ['inst_id', 'program_cd'], prog_rows)
        n['business_hours']    = insert(cur, 'business_hours', ['inst_id', 'weekday', 'open_time', 'close_time'], hours_rows)
        con.commit()
    except Exception:
        con.rollback(); raise
    finally:
        con.close()

    print('\n[적재 행 수]')
    for k, v in n.items(): print(f'  {k:26s} {v:>9,}')
    print('\n[정제 보고]'); [print('  -', x) for x in rep]

if __name__ == '__main__':
    main()
