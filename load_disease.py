"""질병 안내용 4개 테이블 적재 (disease3, disease, disease_name, dept_disease_stat) + dept.is_guide 표시.
사용:  python load_disease.py --stat <진료과목별 상병 통계 CSV> --master <상병마스터 CSV>
선행:  schema.sql 실행 -> load_data.py 실행 (dept 테이블이 채워져 있어야 함)
다시 실행해도 안전(질병 4개 테이블만 비우고 다시 채움)."""
import argparse, csv, re
import pymysql

ap = argparse.ArgumentParser()
ap.add_argument('--stat', required=True); ap.add_argument('--master', required=True)
ap.add_argument('--host', default='localhost'); ap.add_argument('--port', type=int, default=3306)
ap.add_argument('--user', default='hira'); ap.add_argument('--password', default='hira1234')
ap.add_argument('--db', default='hira_db')
ap.add_argument('--no-guide', action='store_true', help='is_guide(안내 제외 진료과목) 표시를 하지 않음')
a = ap.parse_args()

# 질병 안내에서 제외할 진료과목 후보 (팀 확정 전 후보 12개)
NOT_GUIDE = ['일반의', '응급의학과', '진단검사의학과', '영상의학과', '병리과', '핵의학과',
             '방사선종양학과', '예방의학과', '직업환경의학과', '보건기관의과', '구강병리과', '영상치의학과']

def read(path):
    raw = open(path, 'rb').read()
    for enc in ('utf-8-sig', 'cp949'):
        try:
            return list(csv.reader(raw.decode(enc).splitlines()))
        except UnicodeDecodeError:
            pass
    raise SystemExit(f'인코딩을 읽을 수 없습니다: {path}')

stat, master = read(a.stat), read(a.master)
assert stat[0][1] == '진료과목' and stat[0][2] == '주상병코드', f'진료과목별 상병 통계 파일이 아닙니다: {stat[0]}'
assert master[0][0] == '상병기호' and master[0][1] == '한글명', f'상병마스터 파일이 아닙니다: {master[0]}'
stat, master = stat[1:], master[1:]

pat3 = re.compile(r'^[A-Z][0-9]{2}$')
rep = {}                                      # 정제 보고

# ---- 상병마스터 -> disease3 / disease / disease_name
dis3, disease, names = {}, {}, {}
seen_name = set(); dup = bad = 0
for r in master:
    cd, nm, en = r[0].strip(), r[1].strip(), r[2].strip() or None
    if not cd or not nm:
        bad += 1; continue
    if len(cd) == 3:
        if pat3.match(cd):
            dis3.setdefault(cd, nm)           # 3단 상병명 = 그 코드가 처음 나오는 행
        else:
            bad += 1; continue
    disease[cd] = cd[:3]
    key = (cd, nm.casefold())                 # 정렬규칙이 대소문자 무시이므로 같은 취급으로 중복 판정
    if key in seen_name:
        dup += 1; continue
    seen_name.add(key); names[key] = (cd, nm, en)
no_parent = [c for c, p in disease.items() if p not in dis3]
for c in no_parent: disease.pop(c)
names = {k: v for k, v in names.items() if v[0] in disease}
rep['상병마스터 완전 중복 행 제거'] = dup
rep['형식 불량·빈 행 제외'] = bad
rep['3단 상병이 없어 제외한 상병기호'] = len(no_parent)

con = pymysql.connect(host=a.host, port=a.port, user=a.user, password=a.password, database=a.db, charset='utf8mb4')
cur = con.cursor()
cur.execute('SELECT dept_nm, dept_cd FROM dept'); dept = dict(cur.fetchall())

# ---- 통계
num = lambda s: int(s.strip())
good, skipped, no3 = [], {}, set()
for r in stat:
    nm, cd = r[1].strip(), r[2].strip()
    if nm not in dept:                        # 일반의 / 보건기관의과 / 한방 : 진료과목 코드 체계(dept)에 없음
        skipped[nm] = skipped.get(nm, 0) + 1; continue
    if cd not in dis3:
        no3.add(cd); continue
    good.append((dept[nm], cd, num(r[3]), num(r[4]), num(r[5]), num(r[6]), num(r[7])))

cur.execute('SET FOREIGN_KEY_CHECKS=0')
for t in ('dept_disease_stat', 'disease_name', 'disease', 'disease3'):
    cur.execute(f'DELETE FROM {t}')
cur.execute('SET FOREIGN_KEY_CHECKS=1')
cur.executemany('INSERT INTO disease3 VALUES (%s,%s)', sorted(dis3.items()))
cur.executemany('INSERT INTO disease VALUES (%s,%s)', sorted(disease.items()))
cur.executemany('INSERT INTO disease_name VALUES (%s,%s,%s)', sorted(names.values()))
cur.executemany('INSERT INTO dept_disease_stat VALUES (%s,%s,%s,%s,%s,%s,%s)', good)

miss = []
if not a.no_guide:
    cur.execute('UPDATE dept SET is_guide = 1')
    for d in NOT_GUIDE:
        if cur.execute('UPDATE dept SET is_guide = 0 WHERE dept_nm = %s', (d,)) == 0: miss.append(d)
con.commit()

print(f'disease3 {len(dis3):,} / disease {len(disease):,} / disease_name {len(names):,} / dept_disease_stat {len(good):,}행 적재')
print('통계에서 진료과목 코드 체계에 없어 제외:', skipped)
print('통계 3단 코드가 상병마스터에 없어 제외:', sorted(no3) or '없음')
for k, v in rep.items(): print(f'{k}: {v:,}')
if not a.no_guide:
    cur.execute('SELECT COUNT(*) FROM dept WHERE is_guide=0'); print('안내 제외 진료과목:', cur.fetchone()[0], '개', ('(dept에 없는 이름: %s)' % miss) if miss else '')
