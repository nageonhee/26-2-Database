[hira_db 구축 완료 및 SQL 덤프 파일 공유]
1. 완료한 작업 내역
- 통계 3단 상병코드(1,663개)가 상병마스터에 모두 존재하는지 확인 완료(누락 0건)
- 상병마스터 완전 중복 158건 제거 및 숫자 뒤 공백 정제 반영
- disease_name.dis_en 컬럼 길이를 VARCHAR(500)으로 확장(영문명 최대 223자 대응)
- 통계 진료과목 이름 중 dept 코드 체계와 맞지 않는 항목(일반의, 보건기관의과, 한방) 제외 처리
- 기본 12개 테이블 및 질병 관련 4개 테이블(disease3 2,085행, disease 21,266행, disease_name 47,604행, dept_disease_stat 29,797행)과 v_institution 뷰 적재 완료
2. 덤프 파일 크기 및 적재 소요 시간
- 파일명: hira_db_dump.sql
- 파일 크기: 83.42 MB (2026-11-24 14:56:36 생성)
- 적재 소요 시간: 약 7.50초 (00분 07.50초)
3. 덤프 파일 다운로드 링크는 크기가 커서 구글 드라이브에 올려놨습니다.
- https://drive.google.com/file/d/1Oc85dG7ss2x4FwChX3TMZ6TcNr8dtfwY/view?usp=sharing
4. 로컬 MySQL 복원 방법
->위 링크에서 hira_db_dump.sql을 다운로드합니다.
->MySQL에 hira_db 데이터베이스를 생성합니다.
SQL
CREATE DATABASE IF NOT EXISTS hira_db DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
->PowerShell에서 덤프 파일을 복원합니다(C:\경로\hira_db_dump.sql 부분을 실제 받은 파일 경로로 변경).
PowerShell
& "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -u root -p hira_db < "C:\경로\hira_db_dump.sql