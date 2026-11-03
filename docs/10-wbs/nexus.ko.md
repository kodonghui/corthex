# NEXUS: 작업 분해

[English](nexus.md)

CORTHEX 자신의 프로젝트 10단계입니다. 상태: 2026-11-03 계획 확인을 기다리는 초안입니다. 영어가 원본이고 Notion 데이터베이스는 읽기용 사본입니다(`truth: source`). 지금 `codex/nexus-0.2`에서 만드는 것은 승인되었으며 첫 시험과 이주를 진행하는 동안 관리자가 계획을 고칠 수 있습니다. main 병합·운영 배포·출시 태그는 C1 0.2.0과 관리자의 출시 확인 뒤입니다.

입력: [기능 명세](../04-functional-spec/nexus.ko.md), [스키마](../05-erd/nexus.ko.md), [API](../06-api/nexus.ko.md), [화면](../08-screens/nexus/README.ko.md), [목업](../09-mockup/nexus/README.ko.md)과 각각의 다음 단계 메모입니다. 01–09 확인 지점은 2026-11-03 통과했습니다. SPEC-134·142는 단계 ②이며 그 데이터 자리는 남깁니다.

## 이 파일을 읽는 법

`ID`는 TASK-201부터이며 바꾸지 않습니다. `작업`은 따로 시험할 한 조각입니다. `근거`는 SPEC/REQ, `건드리는 곳`은 인터페이스·저장 단위·화면입니다. `선행 작업`을 먼저 끝내고 C1·PR 이름은 외부 선행 조건입니다. `담당 agent`는 Codex이며 이 호스트의 계정 작업은 Aside에 맡깁니다. `크기`는 코드와 의미 있는 시험을 합해 S 약 300줄, M 약 800줄, L 약 2,000줄이며 넘으면 시작 전에 나눕니다. `끝났다고 볼 때`는 다른 사람이 확인할 근거입니다. `상태`는 todo, in progress, done (#N), removed (날짜)이며 번호와 행을 남깁니다.

요청의 모든 응답에 통과 사례가 있어야 완료입니다. 실제 개발 API·mock 화면·자동 페이지 검사·이미지 확인을 나누며 OS/실제 환경 검증이 남으면 진행 중입니다. 커밋마다 AGENTS.md 검사를 하고 묶음 PR은 통합 브랜치로 보내 all-checks와 코드·보안 리뷰 뒤 merge commit으로 합칩니다.

현재 작업 54개: S 7개·M 39개·L 8개입니다. [QA 계획](../12-qa/nexus.ko.md)은 679개 사례를 기능 수용 기준·이름 붙은 응답·명령 결과·화면 상태·통합 시나리오에서 뽑았습니다.

## 서버

| ID | 작업 | 근거 | 건드리는 곳 | 선행 작업 | 담당 | 크기 | 끝났다고 볼 때 | 상태 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-201 | Access 로그인 두 종류 시험 | SPEC-113, SPEC-116 | API-101–API-104 | none | agent | M | 실제 개발 Access의 사람·서비스 토큰에서 ctx.access·aud·sub·email·common_name의 있음/비어 있음을 기록하고 로그인 구현 전에 확인 방법을 정합니다. | done (#92) |
| TASK-202 | 1단계 DB를 보존하는 이주 1 | SPEC-114 | TBL-101, TBL-113 | none | agent | S | 빈 DB와 1단계 DB에 이주 1이 원자적으로 적용되고 기존 스냅샷 바이트와 revision이 그대로 남습니다. | done (#91) |
| TASK-203 | 설계 스키마로 옮기는 이주 2 | SPEC-114 | TBL-101–TBL-113 | TASK-202 | agent | M | 이주 결과와 nexus.sql의 표·열·키·색인·CHECK가 같으며 실패·동시 적용 뒤 부분 스키마가 남지 않습니다. | done (#91) |
| TASK-254 | 반영 보고를 구별할 메타데이터 보존 | SPEC-133 | TBL-109, API-126 | TASK-203 | agent | S | 변환 3이 스키마 2 데이터를 지키고 내부 마지막 보고만 더합니다. 쓰기 ID 만료 뒤에도 같은 PR의 closed 재보고와 유효하지 않은 첫 closed를 구별합니다. | in progress |
| TASK-204 | 스냅샷 0.2와 그림 자료 검증 | SPEC-104, SPEC-105, SPEC-109, SPEC-110, SPEC-114 | API-105, TBL-114 | TASK-203 | agent | M | 두 스냅샷 판과 그림 자료의 형식·UTF-8·한도를 검사하고 모르는 스냅샷 필드는 보존하며 그림 자료는 따로 저장합니다. | in progress |
| TASK-205 | 앞지른 밀기를 막고 보관 커밋 읽기 | SPEC-111, SPEC-112, SPEC-114, SPEC-117, SPEC-118, SPEC-140 | API-105, API-109, TBL-101–TBL-104, TBL-110 | TASK-204, TASK-206 | agent | L | API-105·109의 모든 응답, 겹친 밀기, 저장소 주소, 같은/이전 시각, 바뀌지 않은 그림과 확인 지점을 시험합니다. 앞질러진 밀기는 아무 행도 쓰지 않습니다. | in progress |
| TASK-206 | 그림 짝짓기와 불일치 정리 | SPEC-120, SPEC-121 | TBL-103, TBL-104 | TASK-204 | agent | M | 다섯 불일치 유형, 삭제된 용어, 명시적 none·예외, 기다리는 그림, 다시 생긴 불일치와 열린 항목 1,000개 한도를 시험합니다. | in progress |
| TASK-207 | 삭제 전 확인과 프로젝트 삭제 | SPEC-115 | API-108, API-110, TBL-101–TBL-112 | TASK-205 | agent | S | 모든 응답과 제한된 ID·합계를 확인하고 삭제 뒤 어떤 표에도 그 프로젝트 행이 남지 않습니다. | in progress |
| TASK-208 | 공간·그림·개요·개별 항목 읽기 | SPEC-119, SPEC-123, SPEC-127, SPEC-130, SPEC-133, SPEC-138, SPEC-140 | API-106, API-107, API-111, API-112, API-114–API-117 | TASK-205 | agent | L | 모든 응답과 HEAD, 합계·순서·목록 한도를 확인합니다. 제안 원문은 개별 읽기에만 나옵니다. | in progress |
| TASK-209 | Access 확인과 주소·역할별 요청 처리 | SPEC-113, SPEC-116 | API-101–API-132 | TASK-201 | agent | M | 실제 로그인 시험의 방법을 쓰고 앱·로그인 종류·주소·메서드·출처·세션 거절의 순서와 무변경을 확인합니다. | in progress |
| TASK-210 | Problem Details와 안전한 추적 로그 | SPEC-113 | API-101–API-132 | TASK-209 | agent | S | 서버 오류 코드는 계약 목록과 같고 상태·추가 필드·안전한 detail·traceId가 맞습니다. 로그에는 종류와 traceId만 남습니다. | in progress |
| TASK-211 | 항목·그림에 댓글 달기 | SPEC-126, SPEC-128 | API-118, TBL-105 | TASK-208, TASK-221 | agent | M | 모든 API-118 응답과 수용 기준, 없는 항목·인용문·그림 판·개수·UTF-8 글 바이트 한도를 시험합니다. | in progress |
| TASK-212 | 답글·답함·결정 요청과 다시 열기 | SPEC-127, SPEC-128, SPEC-132 | API-119, API-120, TBL-105, TBL-106 | TASK-211 | agent | M | 모든 응답을 시험합니다. 사용자만 닫힌 댓글을 다시 열거나 결정을 요청하며 waits·dismissed·클레임 갱신이 맞습니다. | in progress |
| TASK-213 | 결정 기록과 댓글 닫기 | SPEC-132 | API-121, TBL-105, TBL-107 | TASK-212 | agent | S | 모든 응답을 시험합니다. 에이전트가 사용자 결정을 안전한 HTTPS 링크로 기록하며 열린 댓글은 원자적으로 닫고 닫힌 댓글은 상태를 지킵니다. 세션에서 한 결정은 먼저 끝맺음 답글을 남길 필요가 없습니다. | in progress |
| TASK-214 | 제안 만들기와 철회 | SPEC-130 | API-122, API-123, TBL-108 | TASK-211, TASK-221 | agent | M | 모든 응답에서 대상·새 항목·원문·한 답변 대상·한도·클레임·반복 철회를 확인합니다. | in progress |
| TASK-215 | 제안 수락과 기각 | SPEC-131 | API-124, API-125, TBL-108, TBL-109 | TASK-214 | agent | M | 모든 응답에서 사용자 수락이 반영 하나만 만들고 한도가 원자적으로 적용되며 기각이 댓글의 기다림을 바꿉니다. | in progress |
| TASK-216 | 반영 보고와 취소 | SPEC-133 | API-126, API-127, TBL-109 | TASK-215, TASK-254 | agent | M | 상태·사건·PR 조합별 응답과 반복 보고·다른 PR·needs-user·클레임 해제를 모두 시험합니다. | in progress |
| TASK-217 | 순서가 있는 에이전트 할 일 읽기 | SPEC-135, SPEC-136, SPEC-140 | API-113 | TASK-208, TASK-216, TASK-220 | agent | M | 모든 응답, 묶음 순서·합계·기다림·mine/taken·검토 중 PR의 점유를 두 세션으로 확인합니다. | in progress |
| TASK-218 | 세션별 클레임과 해제 | SPEC-136 | API-131, API-132, TBL-111 | TASK-221 | agent | M | 두 세션·기한·갱신·닫힌 항목·보고된 PR의 모든 응답을 확인하며 실패한 클레임은 outbox에 두지 않습니다. | in progress |
| TASK-219 | 단계 확인 지점 통과와 철회 | SPEC-139 | API-128, API-129, TBL-110 | TASK-208, TASK-221 | agent | M | 모든 응답에서 기본 커밋 없음·없는 부분/단계·반복 철회·기록된 확인 지점을 확인합니다. | in progress |
| TASK-220 | 확인 지점 기록 PR과 경고 | SPEC-140 | API-130, TBL-110 | TASK-219 | agent | M | 모든 보고 응답을 확인합니다. 검토 중 철회와 잘못 병합된 기록은 고칠 때까지 할 일과 checkpoint-withdrawn에 남습니다. | in progress |
| TASK-221 | 7일 쓰기 기록과 원자적 재전송 | SPEC-126–SPEC-133, SPEC-136, SPEC-139, SPEC-140 | TBL-102, TBL-111, TBL-112 | TASK-203, TASK-209, TASK-210 | agent | L | 새 쓰기 ID와 클레임·상태·한도가 한 batch의 쓰기를 지킵니다. 재전송은 첫 상태/본문을 돌려주고 기한·동시 중복에도 한 번만 바뀝니다. | in progress |
| TASK-222 | HTML 거절 화면과 안전한 코드 제공 | SPEC-113, SPEC-119, SPEC-138 | API-101–API-104 | TASK-209, TASK-210 | agent | M | 브라우저 Accept는 서버 언어의 한 장 HTML을 받고 API·코드는 Problem Details를 받습니다. 헤더·HEAD·내용 해시 캐시를 확인합니다. | in progress |

## 먼저 하는 시험

| ID | 작업 | 근거 | 건드리는 곳 | 선행 작업 | 담당 | 크기 | 끝났다고 볼 때 | 상태 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-223 | 개발 서버의 가장 큰 밀기 측정 | SPEC-114, SPEC-118, SPEC-121 | REQ-081, REQ-124, API-105 | TASK-205 | agent | M | 가상 자료 1,000,000바이트·항목 3,000·검사 2,000·그림 셋을 개발 서버에서 보내 CPU·쿼리·쓴 행을 기록합니다. 10ms/50개 초과는 기준을 바꾸지 않고 판단을 받습니다. | in progress |
| TASK-224 | 모바일 편집기·CSP·Worker 크기 시험 | SPEC-119 | REQ-146–REQ-149, API-104 | TASK-222 | agent | L | 편집기/React 판·라이선스, 서버에서 주는 코드·글꼴, 압축 전후 크기와 현재 Worker 한도·CSP를 기록합니다. 모바일 4G에서 300요소를 20번 열어 P95 3초를 재며 초과는 판단을 받습니다. | in progress |

## 허브

| ID | 작업 | 근거 | 건드리는 곳 | 선행 작업 | 담당 | 크기 | 끝났다고 볼 때 | 상태 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-225 | 기본 브랜치 Git 객체와 부분별 문서 읽기 | SPEC-104, SPEC-105 | API-133, TBL-114 | none | agent | M | 작업 브랜치·미커밋 글은 그림에 들어가지 않습니다. 원격 주소·기본 커밋·시각·가장 긴 부분 이름·생략 검사를 훅/필터 실행 없이 확인합니다. | todo |
| TASK-226 | DDD 보드와 타임라인 읽기 | SPEC-106 | API-133, TBL-114 | TASK-225 | agent | M | 영어·한국어 틀과 NEXUS에서 맥락·명령/정책·애그리거트/읽기 모델/용어·의존·핫스팟·다섯 타임라인 흐름을 읽습니다. | todo |
| TASK-227 | ERD SQL 그림 자료 읽기 | SPEC-107 | API-133, TBL-114 | TASK-225 | agent | M | 틀과 nexus.sql의 열 형식/NULL·PK/UNIQUE/FK·부분 색인·맥락/용어·without_table 예외를 읽습니다. | todo |
| TASK-228 | 중첩 사이트맵 그림 자료 읽기 | SPEC-108 | API-133, TBL-114 | TASK-225 | agent | M | 표준 라이브러리로 부모·주소/권한/흐름/상태·맥락/용어/none·without_screen·일부만 읽은 검사를 보존합니다. | todo |
| TASK-229 | 기본 브랜치의 단계 기록 읽기 | SPEC-109 | API-133, TBL-115, TBL-116 | TASK-225 | agent | M | 부분별 저장소 기록이 기기 상태를 대신합니다. 잘못된 기록은 검사와 unknown으로 남고 대체 출처가 보이며 done은 날짜 있는 확인 지점이 필요합니다. | todo |
| TASK-230 | 설정·가림·스냅샷 한도 | SPEC-104, SPEC-110 | API-133, TBL-114 | TASK-226, TASK-227, TASK-228, TASK-229 | agent | M | 0.2 형식과 새 검사를 확인합니다. 기본 ask_before는 코어 예시와 같고 큰 그림 전체부터 뺀 뒤 항목/검사를 줄이며 경로/비밀은 보내지 않습니다. | todo |
| TASK-231 | status로 저장소 단계 기록 쓰기 | SPEC-109, SPEC-137, SPEC-140 | API-134, TBL-115 | TASK-229 | agent | M | 부분·대체 상태·확인 지점 목록·NEXUS 링크의 모든 결과를 시험합니다. LF JSON 원자적 쓰기는 다른 부분을 지키고 커밋·밀기를 하지 않습니다. | todo |
| TASK-232 | 조상 관계로 밀고 삭제 전 확인하기 | SPEC-111, SPEC-112, SPEC-115 | API-136, API-137 | TASK-230, TASK-233, TASK-234 | agent | M | 보관 스냅샷 없음·같음/자식/조상/갈라짐/커밋 없음·부모자식 같은 시각·replace-held·0.1 서버 거절의 명령 결과를 모두 확인합니다. | todo |
| TASK-233 | 안전한 HTTP·세션·JSON 결과 | SPEC-128, SPEC-135 | API-136–API-150 | none | agent | M | 리디렉션을 따라가지 않습니다. 설정된 주소/프로젝트에만 토큰을 보내며 세션·글·파일을 검사/가리고 문서의 결과·종료 코드를 냅니다. | todo |
| TASK-234 | 7일 outbox 저장과 전송 | SPEC-129 | API-150, TBL-117 | TASK-233 | agent | M | 재시도 상태·토큰/네트워크 실패·기한·영구 거절·오래된 순서·재실패 시 멈춤·두 허브의 잠금을 시험하고 파일에 인증값이 없습니다. | todo |
| TASK-235 | 에이전트 명령과 참조 문서 | SPEC-127–SPEC-133, SPEC-135, SPEC-136, SPEC-140 | API-138–API-149 | TASK-233, TASK-234 | agent | L | 모든 명령/결과를 시험하고 OutboxFile 요청 이름을 계약과 맞대며 snapshot.md·reading.md·허브 스킬을 0.2로 맞춥니다. | todo |

## 화면

| ID | 작업 | 근거 | 건드리는 곳 | 선행 작업 | 담당 | 크기 | 끝났다고 볼 때 | 상태 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-236 | 고정한 토큰으로 CSS 속성 만들기 | SPEC-119, SPEC-123, SPEC-138 | SCR-101, SCR-104–SCR-109 | none | agent | S | resolver 순서대로 기본과 테마를 적용합니다. 두 테마와 새 화면의 모든 색·길이를 덮고 대비를 다시 계산합니다. | todo |
| TASK-237 | 허브 페이지에 0.2 추가 | SPEC-123, SPEC-124, SPEC-125 | API-101, API-135, SCR-101, SCR-104 | TASK-236, TASK-208, TASK-230 | agent | M | 부분·그림·개수·기록 전/철회 확인 지점·ask_before·빈 서버가 각 상태대로 보입니다. 로컬은 오프라인이며 복사 HTML이 같습니다. | todo |
| TASK-238 | 읽기 전용 그림과 대체 항목 목록 | SPEC-119 | API-102, API-104, API-111, SCR-105 | TASK-224, TASK-236 | agent | L | Prism 상태로 그림 셋을 일정하게 그립니다. 편집기 실패에도 접근 가능한 목록과 크기 고정·이름 있는 표시가 남고 이동/확대가 틀 안에 있습니다. | todo |
| TASK-239 | DDD 보드의 다섯 스텝 | SPEC-141 | SCR-105 | TASK-238 | agent | M | 타임라인/맥락에서 다섯 배치를 만들고 처음/마지막·타임라인 없음·step 주소를 확인하며 배치를 저장하지 않습니다. | todo |
| TASK-240 | 항목·댓글 패널 | SPEC-126, SPEC-127, SPEC-132 | API-114, API-118–API-120, SCR-106, SCR-107 | TASK-238, TASK-243 | agent | M | 모든 상태가 mock 응답을 따르고 주소로 패널을 열고 닫습니다. 두 폭에서 답글/다시 열기/결정 요청이 동작하며 제안 원문을 미리 읽지 않습니다. | todo |
| TASK-241 | 제안·반영 패널 | SPEC-130, SPEC-131, SPEC-133 | API-115, API-116, API-124, API-125, API-127, SCR-108 | TASK-238, TASK-243 | agent | M | 모든 제안/반영 상태와 뒤늦은 변경을 Prism으로 시험합니다. 수락/기각 뒤 다시 읽고 PR/반영 상태와 글을 안전하게 보여 줍니다. | todo |
| TASK-242 | 단계 개요와 확인 지점 | SPEC-138, SPEC-139, SPEC-140 | API-103, API-112, API-128, API-129, SCR-109 | TASK-236, TASK-243 | agent | M | 개요의 모든 상태, 기록된 상태와 기록 전 확인 지점, 철회·경고가 두 폭에서 계약을 따릅니다. | todo |
| TASK-243 | 작성 중 글·쓰기 ID·요청 복구 | SPEC-126, SPEC-127, SPEC-131, SPEC-139 | SCR-105–SCR-109 | TASK-236 | agent | M | manual 리디렉션·30초 중단을 씁니다. 글+쓰기 ID가 재열기 뒤 남고 잃은 응답의 재시도는 하나만 만들며 opaqueredirect/401·상태 충돌 뒤 글을 지킵니다. | todo |

## C1 뒤 코어

| ID | 작업 | 근거 | 건드리는 곳 | 선행 작업 | 담당 | 크기 | 끝났다고 볼 때 | 상태 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-244 | 입구·단계 스킬에서 에이전트 할 일 읽기 | SPEC-112, SPEC-135, SPEC-136 | REQ-181, REQ-185, plugins/corthex | C1 0.2.0 tag, PR C, PR D (#83), TASK-235 | agent | M | 최신 main을 먼저 받습니다. 세션/프로젝트마다 한 번 할 일을 읽고 명시적 사용자 작업을 우선하며 토큰이 없어도 계속하고 클레임/PR 점유를 지킵니다. | todo |
| TASK-245 | 단계 기록·반영·타임라인 절차 | SPEC-106, SPEC-132, SPEC-133, SPEC-137, SPEC-140 | REQ-086, REQ-131, REQ-154, REQ-167, REQ-168, REQ-212 | TASK-244, TASK-231 | agent | M | 단계 참조·필요한 stage-contract·허브 단계 표·틀 시험을 함께 고칩니다. 작업/확인 지점을 PR로 기록하고 병합 전에 여전히 유효한지 확인합니다. | todo |
| TASK-246 | 프로젝트 parts·ask_before 문서 | SPEC-110, SPEC-137 | plugins/corthex, .corthex/project.json, TBL-115 | TASK-244 | agent | S | PR C 뒤 설정 참조/예시와 사이트맵 terms/status를 맞추고 memory/nexus 부분과 단계 기록에 최신 MEMORY 상태를 보존합니다. | todo |

## 통합

| ID | 작업 | 근거 | 건드리는 곳 | 선행 작업 | 담당 | 크기 | 끝났다고 볼 때 | 상태 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-247 | 버전·안내서·아키텍처 | SPEC-113, SPEC-137 | REQ-126, manifests, README pairs, NOTICE | TASK-245, TASK-246, TASK-237, TASK-242 | agent | M | NEXUS 0.2.0과 최신 main 다음 코어 판이 매니페스트·모든 스킬에서 같습니다. 두 언어 안내서에 개발·이주·서버 먼저 갱신을 쓰며 운영 배포/태그는 기다립니다. | todo |
| TASK-253 | 최신 main에 맞추고 출시 근거 넘기기 | SPEC-104–SPEC-141 | docs/10-wbs/nexus.md, docs/12-qa/nexus.md, draft PR | TASK-247, TASK-249, TASK-250, TASK-251, TASK-252 | agent | M | 작업/사례 원본과 Notion이 같고 최신 main의 실제 검사 트리를 적습니다. PR은 묶음·설계 변경·안 한 시험을 적고 출시/main 병합/배포/태그 확인을 기다립니다. | todo |

## QA

| ID | 작업 | 근거 | 건드리는 곳 | 선행 작업 | 담당 | 크기 | 끝났다고 볼 때 | 상태 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-248 | 고정 판 계약 검사와 mock 실행 | SPEC-113–SPEC-140 | API-101–API-132 | TASK-222 | agent | M | 저장소 밖 고정 판 validator 0.7.1·Prism 5.16.0·Schemathesis 3.39.16과 쿠키/경로/헤더 hook을 씁니다. 개발 계약 시험은 커밋을 적고 mock만의 결과를 나눕니다. | in progress |
| TASK-249 | 서버의 이름 붙은 응답 모두 보내기 | SPEC-104–SPEC-140 | API-101–API-132 | TASK-217, TASK-218, TASK-220, TASK-248 | agent | L | 가능한 모든 이름 붙은 예시를 개발 서버에서 보내 스키마·코드·데이터 효과를 확인합니다. default/internal의 mock 사례는 따로 셉니다. | in progress |
| TASK-250 | 세 운영체제의 허브 명령 검증 | SPEC-104–SPEC-140 | API-133–API-150 | TASK-231, TASK-232, TASK-235 | agent | M | Windows/macOS/Linux에서 Python 3.8과 최신 판의 모든 명령 결과가 통과하며 네트워크/토큰 없는 시험의 격리가 유지됩니다. | todo |
| TASK-251 | 흐름과 모든 화면 상태 걷기 | SPEC-119, SPEC-123–SPEC-141 | FL-101–FL-114, SCR-101–SCR-109 | TASK-237, TASK-239, TASK-240, TASK-241, TASK-242, TASK-249 | agent | L | 브라우저 시험자가 역할·경로·커밋과 320/1440·두 테마/언어의 근거를 남깁니다. 페이지 검사와 이미지 확인을 나누고 작동한 경로를 CI e2e로 만듭니다. | todo |
| TASK-252 | 성능과 NEXUS 자신의 그림 맞대기 | SPEC-106, SPEC-107, SPEC-108, SPEC-119, SPEC-120 | REQ-124, REQ-149 | TASK-223, TASK-224, TASK-251 | agent | M | 20번의 원래 값·P95, Worker/편집기 크기와 최대 밀기를 기록합니다. 가상 자료와 NEXUS 자신의 로컬 그림을 확인하며 저장소는 허락 없이 보내지 않습니다. | todo |

## 결과

서버 요청의 선언된 응답을 모두 적었습니다. QA는 각 응답의 이름 붙은 예시까지 나누며 mock만으로 보는 internal은 실제 서버 통과로 세지 않습니다.

| 인터페이스 | 요청 | 응답 | 시험 작성 작업 |
| --- | --- | --- | --- |
| API-101 | GET / | 200, 403, default | TASK-237 |
| API-102 | GET /pictures/{project}/{part}/{stage} | 200, 403, 404, default | TASK-238 |
| API-103 | GET /overview/{project}/{part}/{stage} | 200, 403, 404, default | TASK-242 |
| API-104 | GET /code/{file} | 200, 403, 404, default | TASK-222 |
| API-105 | POST /api/snapshots | 200, 400, 403, 409, 413, 415, default | TASK-205 |
| API-106 | GET /api/snapshots | 200, 403, default | TASK-208 |
| API-107 | GET /api/snapshots/{project} | 200, 403, 404, default | TASK-208 |
| API-108 | DELETE /api/snapshots/{project} | 200, 403, 404, default | TASK-207 |
| API-109 | GET /api/snapshots/{project}/held | 200, 403, 404, default | TASK-205 |
| API-110 | GET /api/snapshots/{project}/removal | 200, 403, 404, default | TASK-207 |
| API-111 | GET /api/spaces/{project}/pictures/{part}/{stage} | 200, 403, 404, default | TASK-208 |
| API-112 | GET /api/spaces/{project}/overview/{part}/{stage} | 200, 403, 404, default | TASK-208 |
| API-113 | GET /api/spaces/{project}/todo | 200, 400, 403, 404, default | TASK-217 |
| API-118 | POST /api/spaces/{project}/comments | 201, 400, 403, 404, 409, 413, 415, default | TASK-211 |
| API-114 | GET /api/spaces/{project}/comments/{comment} | 200, 403, 404, default | TASK-208 |
| API-119 | POST /api/spaces/{project}/comments/{comment}/replies | 201, 400, 403, 404, 409, 413, 415, default | TASK-212 |
| API-120 | POST /api/spaces/{project}/comments/{comment}/answered | 200, 400, 403, 404, 409, default | TASK-212 |
| API-121 | POST /api/spaces/{project}/comments/{comment}/decisions | 201, 400, 403, 404, 409, 413, 415, default | TASK-213 |
| API-122 | POST /api/spaces/{project}/proposals | 201, 400, 403, 404, 409, 413, 415, default | TASK-214 |
| API-115 | GET /api/spaces/{project}/proposals/{proposal} | 200, 403, 404, default | TASK-208 |
| API-123 | POST /api/spaces/{project}/proposals/{proposal}/withdraw | 200, 400, 403, 404, 409, default | TASK-214 |
| API-124 | POST /api/spaces/{project}/proposals/{proposal}/accept | 200, 400, 403, 404, 409, default | TASK-215 |
| API-125 | POST /api/spaces/{project}/proposals/{proposal}/dismiss | 200, 400, 403, 404, 409, default | TASK-215 |
| API-116 | GET /api/spaces/{project}/edits/{edit} | 200, 403, 404, default | TASK-208 |
| API-126 | POST /api/spaces/{project}/edits/{edit}/report | 200, 400, 403, 404, 409, 413, 415, default | TASK-216 |
| API-127 | POST /api/spaces/{project}/edits/{edit}/dismiss | 200, 400, 403, 404, 409, default | TASK-216 |
| API-128 | POST /api/spaces/{project}/checkpoints | 201, 400, 403, 404, 409, 413, 415, default | TASK-219 |
| API-117 | GET /api/spaces/{project}/checkpoints/{checkpoint} | 200, 403, 404, default | TASK-208 |
| API-129 | POST /api/spaces/{project}/checkpoints/{checkpoint}/withdraw | 200, 400, 403, 404, 409, default | TASK-219 |
| API-130 | POST /api/spaces/{project}/checkpoints/{checkpoint}/report | 200, 400, 403, 404, 409, 413, 415, default | TASK-220 |
| API-131 | POST /api/spaces/{project}/claims/{entry} | 200, 400, 403, 404, 409, default | TASK-218 |
| API-132 | DELETE /api/spaces/{project}/claims/{entry} | 200, 400, 403, 404, 409, default | TASK-218 |

| 인터페이스 | 명령 | 결과 | 시험 작성 작업 |
| --- | --- | --- | --- |
| API-133 | snapshot | done, 잘못된 명령줄, failed | TASK-230 |
| API-134 | status | done, 잘못된 명령줄, failed | TASK-231 |
| API-135 | build | done, 잘못된 명령줄, failed | TASK-237 |
| API-136 | push | done, 잘못된 명령줄, failed, refused | TASK-232 |
| API-137 | remove | done, 잘못된 명령줄, failed, refused | TASK-232 |
| API-138 | todo | done, 잘못된 명령줄, failed, refused | TASK-235 |
| API-139 | comment | done, 잘못된 명령줄, failed, refused, kept | TASK-235 |
| API-140 | reply | done, 잘못된 명령줄, failed, refused, kept | TASK-235 |
| API-141 | answered | done, 잘못된 명령줄, failed, refused, kept | TASK-235 |
| API-142 | decide | done, 잘못된 명령줄, failed, refused, kept | TASK-235 |
| API-143 | propose | done, 잘못된 명령줄, failed, refused, kept | TASK-235 |
| API-144 | withdraw | done, 잘못된 명령줄, failed, refused, kept | TASK-235 |
| API-145 | reflect | done, 잘못된 명령줄, failed, refused, kept | TASK-235 |
| API-146 | record | done, 잘못된 명령줄, failed, refused, kept | TASK-235 |
| API-147 | show | done, 잘못된 명령줄, failed, refused | TASK-235 |
| API-148 | claim | done, 잘못된 명령줄, failed, refused | TASK-235 |
| API-149 | release | done, 잘못된 명령줄, failed, refused | TASK-235 |
| API-150 | outbox | done, 잘못된 명령줄, failed, refused, kept | TASK-234 |

## 작업이 기다리는 결정

- TASK-209는 TASK-201의 실제 로그인 시험을 기다립니다. ctx.access와 검증한 JWT 모두 두 종류를 가르지 못하면 대안과 함께 관리자에게 돌려드립니다.
- TASK-238은 TASK-224의 모바일·편집기·크기 시험을 기다립니다. 추가 개발 의존·편집기 선택 변경·고정 토큰 변경·성능 초과는 판단을 받고 독립적인 서버/허브 작업을 계속합니다.
- TASK-244–247은 main의 corthex-memory--v0.2.0 태그·PR C·PR D(#83)를 기다립니다.
- TASK-253은 QA 전체 근거를 기다립니다. 출시·main 병합·운영 배포·태그와 저장소 첫 보내기는 관리자의 명시적 결정입니다.

## 이 단계가 고른 것

1. 원본은 nexus.md, 짝은 nexus.ko.md이며 Notion 한국어 사본은 작업·사례마다 한 DB 행입니다.
2. 서버·허브·화면·C1 뒤 코어·QA를 나누어 리뷰하고 크기를 넘으면 구현 전에 다시 나눕니다.
3. 가상 프로젝트를 쓰고 자신의 그림은 로컬에서 맞댑니다. 저장소 전송은 REQ-107을 기다립니다.
4. 인증값은 이 호스트의 환경변수·비밀 저장소에만 두고 Aside가 계정 작업을 합니다. 키·쿠키·인증파일은 다른 기기로 복사하지 않습니다.
5. 고정된 04 행·05 스키마·06 계약·09 토큰을 지킵니다. 뜻을 지키는 설명은 코드 전에 양쪽 문서를 고치고 깨는 변경은 관리자를 기다립니다.

## 확인할 것

2026-11-03 확인 대기: 작업 53개(S 6/M 39/L 8), 차례는 시험·이주 → 서버 → 허브 → 화면이며 코어는 C1·PR C·PR D 뒤입니다. 시험 셋은 실제 로그인 두 종류·최대 밀기의 CPU/쿼리·모바일 20번 열기입니다. 계정 단계는 Aside에 맡겼으므로 현재 관리자에게 요청한 계정 조작은 없습니다. 사본을 만든 뒤 Notion 링크를 보여 드립니다. 현재 지시는 확인 대기 중 시험과 이주 진행을 허용하며 침묵은 통과가 아닙니다.

## 다음 단계를 위한 메모

### 11단계: 개발

묶음별 브랜치는 codex/nexus-0.2에서 따고 TASK/SPEC·한 시험·안 한 시험·설계 변경을 PR에 적습니다. 통합 브랜치를 먼저 push하고 원본 변경이 생기면 main 쪽 draft를 엽니다. 완료 상태는 그 PR에서 Git을 먼저 고치고 보드가 따릅니다. 공용 파일과 인계 전에 origin/main을 merge commit으로 받습니다.

### 12단계: QA

개발 Access 뒤에서 [계획](../12-qa/nexus.ko.md)을 돌리고 통과마다 커밋·환경·근거를 적습니다. 브라우저 시험자가 단계 ① 흐름을 걷고 작동한 경로를 e2e로 고정합니다. 실제 응답·mock만의 응답·페이지 측정·이미지 검토를 나누고 출시는 기다립니다.

## 현재 서버 구현

TASK-204–TASK-224와 TASK-254는 진행 중입니다. 서버 요청 처리와 트랜잭션의 로컬 시험, 가상 프로젝트의 개발 서버 확인을 했으나 응답별 계약 전체·편집기 시험·화면은 남았습니다. QA 근거를 따르며 시험 개수로 API 제공이나 화면 인수를 추정하지 않습니다.
