-- =====================================================================
-- 지역·진료과목별 의료기관(병의원·약국) 조회 + 질병별 진료과목·병원 안내 시스템  --  MySQL 8.0 스키마
-- 버전: v3 (조회 기능 8개 기준 16개 테이블 + 뷰 1개, 전국 데이터)   관리: B(설계)
--   v2 대비: 기능에서 쓰지 않는 병상·전문병원·의료인력·기타인력 테이블 7개 제거
-- 원본: 건강보험심사평가원 「전국 병의원 및 약국 현황」 (2026.9 기준 CSV 12종 중 조회 기능에 필요한 파일만 사용)
--   ※ 식사료(06)·간호등급(07)·교통정보(04)·전문병원(09)·병상·기타인력은 조회 기능과 무관하여 제외 (보고서에 사유 기재)
--   추가 원본: 심평원 「상병마스터」(47,798행), 「병원급이상 진료과목별 상병 통계」(30,331행, 2025년 진료분)
-- 문자셋: utf8mb4 / 요양기호(암호화값)는 대소문자 구분이 필요하여 ascii_bin 사용
-- =====================================================================
CREATE DATABASE IF NOT EXISTS hira_db DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE hira_db;

SET FOREIGN_KEY_CHECKS = 0;
DROP VIEW  IF EXISTS v_institution;
-- v2에 있던 테이블(병상·전문병원·의료인력·기타인력)도 함께 지워 v2 DB 위에 다시 실행해도 깨끗하게 생성
DROP TABLE IF EXISTS dept_disease_stat, disease_name, disease, disease3,
                     business_hours, institution_other_staff, staff_type,
                     institution_specialty, specialty_field,
                     institution_program, program,
                     institution_equip, equipment_type,
                     institution_dept, dept,
                     institution_bed, bed_type,
                     institution_staff, institution,
                     ownership_type, institution_type, sigungu, sido;
SET FOREIGN_KEY_CHECKS = 1;

-- ---------------------------------------------------------------------
-- 1. 코드(참조) 테이블 : 코드 -> 명칭 종속성을 분리 (이행·부분 종속 제거)
-- ---------------------------------------------------------------------
CREATE TABLE sido (
  sido_cd  CHAR(6)     NOT NULL COMMENT '시도코드',
  sido_nm  VARCHAR(10) NOT NULL COMMENT '시도명',
  PRIMARY KEY (sido_cd),
  UNIQUE KEY uq_sido_nm (sido_nm)
) ENGINE=InnoDB COMMENT='시도';

CREATE TABLE sigungu (
  sigungu_cd CHAR(6)     NOT NULL COMMENT '시군구코드',
  sigungu_nm VARCHAR(20) NOT NULL COMMENT '시군구명',
  sido_cd    CHAR(6)     NOT NULL COMMENT '소속 시도코드',
  PRIMARY KEY (sigungu_cd),
  UNIQUE KEY uq_sigungu_sido_nm (sido_cd, sigungu_nm),   -- 시군구명은 시도 안에서만 유일(예: 고성군)
  CONSTRAINT fk_sigungu_sido FOREIGN KEY (sido_cd) REFERENCES sido (sido_cd)
) ENGINE=InnoDB COMMENT='시군구';

CREATE TABLE institution_type (
  type_cd CHAR(2)     NOT NULL COMMENT '종별코드',
  type_nm VARCHAR(20) NOT NULL COMMENT '종별명(상급종합,의원,약국 등)',
  PRIMARY KEY (type_cd),
  UNIQUE KEY uq_type_nm (type_nm)
) ENGINE=InnoDB COMMENT='요양기관 종별';

CREATE TABLE ownership_type (
  ownership_cd CHAR(2)     NOT NULL COMMENT '설립구분코드',
  ownership_nm VARCHAR(20) NOT NULL COMMENT '설립구분명(국립,공립,개인 등)',
  PRIMARY KEY (ownership_cd),
  UNIQUE KEY uq_ownership_nm (ownership_nm)
) ENGINE=InnoDB COMMENT='설립구분';

-- ---------------------------------------------------------------------
-- 2. 핵심 개체 : 의료기관(병원급·의원·약국 통합)
--    원본의 '병원 기본', '약국 기본', '시설정보' 3개 파일에 중복 저장되던 공통 12개 컬럼을 1개로 통합
-- ---------------------------------------------------------------------
CREATE TABLE institution (
  inst_id      INT UNSIGNED NOT NULL COMMENT '기관 대리키(조인용 정수키)',
  ykiho        VARCHAR(100) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT '암호화요양기호(자연키)',
  inst_nm      VARCHAR(80)  NOT NULL COMMENT '요양기관명',
  type_cd      CHAR(2)      NOT NULL COMMENT '종별코드',
  ownership_cd CHAR(2)      NOT NULL COMMENT '설립구분코드',
  sigungu_cd   CHAR(6)      NOT NULL COMMENT '시군구코드',
  emd_nm       VARCHAR(20)  NULL     COMMENT '읍면동',
  zip_cd       CHAR(5)      NULL     COMMENT '우편번호(00000은 NULL 처리)',
  address      VARCHAR(200) NOT NULL COMMENT '도로명주소(표기용 문자열)',
  phone        VARCHAR(20)  NULL     COMMENT '전화번호',
  opened_on    DATE         NULL     COMMENT '개설일자(1900-01-01 미상값은 NULL)',
  longitude    DECIMAL(10,7) NULL    COMMENT '경도(X)',
  latitude     DECIMAL(9,7)  NULL    COMMENT '위도(Y)',
  homepage     VARCHAR(300) NULL     COMMENT '병원 홈페이지',
  PRIMARY KEY (inst_id),
  UNIQUE KEY uq_institution_ykiho (ykiho),
  KEY ix_inst_region_type (sigungu_cd, type_cd),          -- 지역+종별 검색
  KEY ix_inst_type (type_cd),
  KEY ix_inst_name (inst_nm),                              -- 기관명 접두 검색
  KEY ix_inst_opened (opened_on),                          -- 개설 연도 집계
  CONSTRAINT fk_inst_type      FOREIGN KEY (type_cd)      REFERENCES institution_type (type_cd),
  CONSTRAINT fk_inst_ownership FOREIGN KEY (ownership_cd) REFERENCES ownership_type (ownership_cd),
  CONSTRAINT fk_inst_sigungu   FOREIGN KEY (sigungu_cd)   REFERENCES sigungu (sigungu_cd),
  CONSTRAINT ck_inst_lat CHECK (latitude  IS NULL OR latitude  BETWEEN 30 AND 40),
  CONSTRAINT ck_inst_lon CHECK (longitude IS NULL OR longitude BETWEEN 120 AND 135)
) ENGINE=InnoDB COMMENT='의료기관(병원급·의원·약국)';

-- ---------------------------------------------------------------------
-- 3. 진료과목 (기관 N : M 진료과목)
--    원본의 '선택진료 의사수'는 435,675행 전부 0 이므로 정보가 없어 제외
-- ---------------------------------------------------------------------
CREATE TABLE dept (
  dept_cd CHAR(2)     NOT NULL COMMENT '진료과목코드',
  dept_nm VARCHAR(30) NOT NULL COMMENT '진료과목명',
  is_guide TINYINT(1) NOT NULL DEFAULT 1 COMMENT '질병별 안내 대상 여부(1=안내, 0=제외: 응급의학과·영상의학과 등)',
  PRIMARY KEY (dept_cd),
  UNIQUE KEY uq_dept_nm (dept_nm),
  CONSTRAINT ck_dept_guide CHECK (is_guide IN (0, 1))
) ENGINE=InnoDB COMMENT='진료과목';

CREATE TABLE institution_dept (
  inst_id        INT UNSIGNED NOT NULL,
  dept_cd        CHAR(2)      NOT NULL,
  specialist_cnt SMALLINT UNSIGNED NOT NULL COMMENT '과목별 전문의수',
  PRIMARY KEY (inst_id, dept_cd),
  KEY ix_dept_inst (dept_cd, inst_id),                     -- 진료과목 -> 기관 방향 조회
  CONSTRAINT fk_idept_inst FOREIGN KEY (inst_id) REFERENCES institution (inst_id) ON DELETE CASCADE,
  CONSTRAINT fk_idept_dept FOREIGN KEY (dept_cd) REFERENCES dept (dept_cd)
) ENGINE=InnoDB COMMENT='기관별 진료과목(N:M)';

-- ---------------------------------------------------------------------
-- 4. 의료장비
-- ---------------------------------------------------------------------
CREATE TABLE equipment_type (
  equip_cd CHAR(4)     NOT NULL COMMENT '장비코드',
  equip_nm VARCHAR(40) NOT NULL COMMENT '장비명',
  PRIMARY KEY (equip_cd),
  UNIQUE KEY uq_equip_nm (equip_nm)
) ENGINE=InnoDB COMMENT='의료장비 종류';

CREATE TABLE institution_equip (
  inst_id  INT UNSIGNED NOT NULL,
  equip_cd CHAR(4)      NOT NULL,
  qty      SMALLINT UNSIGNED NOT NULL COMMENT '장비대수',
  PRIMARY KEY (inst_id, equip_cd),
  KEY ix_equip_inst (equip_cd, inst_id),
  CONSTRAINT fk_ieq_inst  FOREIGN KEY (inst_id)  REFERENCES institution (inst_id) ON DELETE CASCADE,
  CONSTRAINT fk_ieq_equip FOREIGN KEY (equip_cd) REFERENCES equipment_type (equip_cd)
) ENGINE=InnoDB COMMENT='기관별 보유 장비(N:M)';

-- ---------------------------------------------------------------------
-- 5. 특수진료·시범사업·참여기관 지정 (원본 '08 검색코드')
-- ---------------------------------------------------------------------
CREATE TABLE program (
  program_cd CHAR(2)     NOT NULL COMMENT '검색코드',
  program_nm VARCHAR(60) NOT NULL COMMENT '지정/시범사업명',
  PRIMARY KEY (program_cd),
  UNIQUE KEY uq_program_nm (program_nm)
) ENGINE=InnoDB COMMENT='특수진료·시범사업·참여기관 구분';

CREATE TABLE institution_program (
  inst_id    INT UNSIGNED NOT NULL,
  program_cd CHAR(2)      NOT NULL,
  PRIMARY KEY (inst_id, program_cd),
  KEY ix_program_inst (program_cd, inst_id),
  CONSTRAINT fk_iprog_inst FOREIGN KEY (inst_id)    REFERENCES institution (inst_id) ON DELETE CASCADE,
  CONSTRAINT fk_iprog_prog FOREIGN KEY (program_cd) REFERENCES program (program_cd)
) ENGINE=InnoDB COMMENT='기관별 지정·참여 사업(N:M)';

-- ---------------------------------------------------------------------
-- 6. 요일별 진료시간 : 원본 '진료시작/종료시간_요일' 14개 반복 컬럼 -> 요일별 행
-- ---------------------------------------------------------------------
CREATE TABLE business_hours (
  inst_id    INT UNSIGNED NOT NULL,
  weekday    TINYINT UNSIGNED NOT NULL COMMENT '1=월 2=화 3=수 4=목 5=금 6=토 7=일',
  open_time  TIME NOT NULL COMMENT '진료시작',
  close_time TIME NOT NULL COMMENT '진료종료',
  PRIMARY KEY (inst_id, weekday),
  KEY ix_hours_day_time (weekday, open_time, close_time),
  CONSTRAINT fk_hours_inst FOREIGN KEY (inst_id) REFERENCES institution (inst_id) ON DELETE CASCADE,
  CONSTRAINT ck_hours_day  CHECK (weekday BETWEEN 1 AND 7),
  CONSTRAINT ck_hours_time CHECK (open_time < close_time)
) ENGINE=InnoDB COMMENT='요일별 진료시간';


-- ---------------------------------------------------------------------
-- 7. 질병 안내 : 상병명 -> 상병기호 -> 3단 상병 -> 진료과목별 통계 -> 진료과목 -> 의료기관
-- ---------------------------------------------------------------------
-- 3단 상병 (통계와 연결되는 단위) 예) J00 급성 비인두염[감기]
CREATE TABLE disease3 (
  dis3_cd CHAR(3)      NOT NULL COMMENT '3단 상병코드(KCD 앞 3자리)',
  dis3_nm VARCHAR(200) NOT NULL COMMENT '3단 상병명',
  PRIMARY KEY (dis3_cd),
  CONSTRAINT ck_dis3_cd CHECK (REGEXP_LIKE(dis3_cd, '^[A-Z][0-9]{2}$', 'c'))
) ENGINE=InnoDB COMMENT='3단 상병';

-- 상병 (상병기호 1개당 1행) : 상병기호 -> 3단코드
--   원본 상병마스터는 같은 상병기호에 이름이 여러 개라 상병기호만으로 PK가 안 됨
--   -> 상병기호 -> 3단코드 종속이 이름 행마다 반복되지 않도록 disease / disease_name 으로 분해
CREATE TABLE disease (
  dis_cd  VARCHAR(10) NOT NULL COMMENT '상병기호(예: J00, A000)',
  dis3_cd CHAR(3)     NOT NULL COMMENT '소속 3단 상병코드 = 상병기호 앞 3자리',
  PRIMARY KEY (dis_cd),
  KEY ix_disease_dis3 (dis3_cd),
  CONSTRAINT fk_disease_dis3 FOREIGN KEY (dis3_cd) REFERENCES disease3 (dis3_cd),
  CONSTRAINT ck_disease_prefix CHECK (dis3_cd = LEFT(dis_cd, 3))
) ENGINE=InnoDB COMMENT='상병(상병기호)';

-- 상병명 (상병기호 1 : N 이름) : 다중값 속성 -> 별도 릴레이션 (사상 7단계)
CREATE TABLE disease_name (
  dis_cd VARCHAR(10)  NOT NULL COMMENT '상병기호',
  dis_nm VARCHAR(200) NOT NULL COMMENT '상병 한글명',
  dis_en VARCHAR(200) NULL     COMMENT '상병 영문명',
  PRIMARY KEY (dis_cd, dis_nm),
  KEY ix_disease_name_nm (dis_nm),
  CONSTRAINT fk_dname_disease FOREIGN KEY (dis_cd) REFERENCES disease (dis_cd) ON DELETE CASCADE
) ENGINE=InnoDB COMMENT='상병명(한 상병기호에 여러 이름)';

-- 진료과목별 상병 통계 (진료과목 N : M 3단 상병, 교차 테이블 + 관계 속성)
--   원본은 진료과목을 '이름'으로만 가짐 -> 적재 시 dept_nm으로 dept_cd를 찾아 저장
--   진료년도는 2025 한 값뿐이라 열로 두지 않음 / 비율(%)은 유도 속성이라 저장하지 않음(조회 때 계산)
CREATE TABLE dept_disease_stat (
  dept_cd     CHAR(2)         NOT NULL COMMENT '진료과목코드',
  dis3_cd     CHAR(3)         NOT NULL COMMENT '3단 상병코드(주상병)',
  patient_cnt INT UNSIGNED    NOT NULL COMMENT '환자수',
  claim_cnt   INT UNSIGNED    NOT NULL COMMENT '명세서청구건수',
  visit_days  INT UNSIGNED    NOT NULL COMMENT '입내원일수',
  insurer_amt BIGINT UNSIGNED NOT NULL COMMENT '보험자부담금(원)',
  total_amt   BIGINT UNSIGNED NOT NULL COMMENT '요양급여비용총액(원)',
  PRIMARY KEY (dept_cd, dis3_cd),
  KEY ix_stat_dis3_patient (dis3_cd, patient_cnt),
  CONSTRAINT fk_stat_dept FOREIGN KEY (dept_cd) REFERENCES dept (dept_cd),
  CONSTRAINT fk_stat_dis3 FOREIGN KEY (dis3_cd) REFERENCES disease3 (dis3_cd),
  CONSTRAINT ck_stat_amt  CHECK (insurer_amt <= total_amt)
) ENGINE=InnoDB COMMENT='병원급 이상 진료과목별 3단 상병 통계(2025년 진료분)';

-- ---------------------------------------------------------------------
-- 편의용 뷰 (조회 프로그램에서 코드 테이블 조인을 반복하지 않도록)
-- ---------------------------------------------------------------------
CREATE VIEW v_institution AS
SELECT i.inst_id, i.inst_nm, t.type_nm, o.ownership_nm,
       sd.sido_nm, sg.sigungu_nm, i.emd_nm, i.address, i.phone, i.opened_on,
       i.longitude, i.latitude, i.sigungu_cd, i.type_cd
FROM institution i
JOIN institution_type t  ON t.type_cd = i.type_cd
JOIN ownership_type  o   ON o.ownership_cd = i.ownership_cd
JOIN sigungu         sg  ON sg.sigungu_cd = i.sigungu_cd
JOIN sido            sd  ON sd.sido_cd = sg.sido_cd;


-- =====================================================================
-- [데이터 적재 후 실행] 안내 제외 진료과목 표시 (목록은 팀 확정 필요)
-- =====================================================================
-- UPDATE dept SET is_guide = 0
-- WHERE dept_nm IN ('일반의','응급의학과','진단검사의학과','영상의학과','병리과','핵의학과',
--                   '방사선종양학과','예방의학과','직업환경의학과','보건기관의과','구강병리과','영상치의학과');
