# SCR-109 단계 현황

[English](SCR-109-stage-overview.md)

목적: 사용자는 한 부분의 단계에 남은 것, 곧 그 열린 어긋남, 의견, 반영 대기를 한데 모아 그 기록된 상태, 확인 지점, 점검과 함께 보고, 단계의 확인 지점을 통과시키거나, NEXUS에서 통과시킨 확인 지점을 기록되기 전에 철회합니다. (FL-113)

경로 `/overview/{project}/{part}/{stage}`. NEXUS 서버에만 있고(API-103), 단계 자세히 보기(SCR-104), 허브 페이지(SCR-101), 그림 보기(SCR-105)가 잇습니다. 볼 수 있는 사람: Cloudflare Access가 들여보낸 누구나. 통과와 철회에는 사람 본인의 로그인이 필요합니다. NEXUS 0.2에서 새로 생깁니다(SPEC-138, SPEC-139). [모든 화면](README.ko.md#모든-화면)의 규칙을 따릅니다.

## 자료

| 자료 | 출처 |
| --- | --- |
| 페이지: 프로젝트, 부분, 단계, 그리고 `view-data`에 API-112의 답 | API-103(`corthex-view-page/0.2`) |
| 보기의 핵심 파일, 그림 보기의 것과 같음 | API-104 |
| 그 부분의 단계 기록: 그 상태, 확인 지점, 다음 행동, 갱신된 때, 그리고 저장소에서 왔는지 기기의 상태 파일에서 왔는지 | API-112(`record`), 처음에는 페이지의 자료에서 |
| 프로젝트가 그 단계를 읽는지, 그리고 그 텍스트 원본의 상태 | API-112(`read`, `source_state`) |
| 그 점검 | API-112(`checks`) |
| 그 어긋남이 걸린 그림, 저마다 그 커밋과 최신인지 | API-112(`pictures`) |
| 그 열린 어긋남, 열린 의견, 반영 대기를 저마다 50개까지 그 전체 수와 함께, 그리고 마지막 교차 점검이 열지 못한 어긋남의 수 | API-112(`discrepancies`, `comments`, `reflections`, `not_opened`) |
| NEXUS에서 통과시켰으나 아직 어느 기록도 적지 않은 확인 지점, 그리고 기록이 적은 철회된 확인 지점과 그 `checkpoint-withdrawn` 경고 | API-112(`checkpoints`, `warnings`) |
| 쓰고 있는 말과 그 쓰기 ID | 말 칸과, 그 부분과 단계의 브라우저 저장소([규칙 5](README.ko.md#모든-화면)) |

## 동작

| 동작 | 결과 | 실패 |
| --- | --- | --- |
| 말을 붙이거나 붙이지 않고 확인 지점 통과시키기 | 기록된 상태 옆에 "{date}에 NEXUS에서 통과, 기록을 기다림". AI 할 일이 그것을 늘어놓습니다(SPEC-139) | 통과되지 않음: 말은 그대로 두고 SCR-109#error나 SCR-109#permission |
| NEXUS에서 통과시킨 확인 지점 철회하기 | "{date}에 철회함", 그리고 AI 할 일에서 빠집니다. 다만 보고된 PR이 그것을 쓰면 그렇지 않습니다(SPEC-139) | 그사이 기록됨: SCR-109#stale. 그 밖에는 SCR-109#error나 SCR-109#permission |
| 항목 열기 | 그 패널을 연 그림 보기: `#comment=`, `#proposal=`, 또는 어긋남의 항목을 단 `#item=` | SCR-106#gone, SCR-107#gone, SCR-108#gone |
| 그림이나 허브 페이지 열기 | 그 부분과 단계의 SCR-105, 또는 SCR-101 | 그 페이지 자신의 거절 |
| 다시 불러오기 | 서버에서 다시 받은 페이지 | SCR-109#error |

## 상태

| 상태 | 사용자가 보는 것과 할 수 있는 것 | 이어지는 응답 |
| --- | --- | --- |
| SCR-109#loading | 보기의 코드가 돌기 전에는 페이지가 고정 문구 "단계 현황을 불러오는 중입니다. 나타나지 않으면 페이지를 다시 불러와 주세요."와 다시 불러오는 링크만 보입니다. 그다음 페이지의 자료가 곧바로 그려집니다 | API-103#200, API-104#200 |
| SCR-109#normal | 위 막대: 허브 페이지, 프로젝트·부분·단계, 그리고 그림이 있는 단계면 그림. 기록된 상태와 그 확인 지점, 다음 행동, 갱신된 때, 그리고 "저장소에서"나 "기기의 상태 파일에서". "남은 것": 열린 어긋남, 열린 의견, 반영 대기를 저마다 그 전체 수와 함께, 항목마다 그 패널로 가는 링크. 점검, 또는 "점검에서 찾은 것이 없습니다." "확인 지점 통과시키기": 붙이지 않아도 되는 2,000자까지의 말 칸과 통과. 프로젝트가 읽지 않는 단계는 그 텍스트 원본의 상태로 까닭을 알리고 그래도 통과를 둡니다(SPEC-138). 그림이 없는 단계는 그 기록과 점검만 보입니다 | API-103#200, API-112#200, API-128#201, `changed: true`인 API-129#200 |
| SCR-109#empty | 열린 것 없음: 목록 자리에 "이 단계에 남은 것이 없습니다.", 그리고 기록, 점검, 통과 | 항목이 없는 API-112#200 |
| SCR-109#stale | NEXUS에서 통과시켰으나 어느 기록도 적지 않은 확인 지점: 기록된 상태 옆에 "{date}에 NEXUS에서 통과, 기록을 기다림"과 그 말, 에이전트가 보고하면 그 PR, 그리고 철회. 두 번째 통과는 두 번째 확인 지점을 만들므로 이때 통과는 "다시 통과"라고 적힙니다. `checkpoint-withdrawn` 경고: 기록된 상태 옆에 "기록에 NEXUS에서 철회한 확인 지점이 적혀 있습니다. 에이전트가 기록을 고칩니다."(SPEC-140). 그사이 기록된 확인 지점의 철회: "이 확인 지점은 이미 기록되어 여기서 철회할 수 없습니다. 바꾸려면 새로 결정해야 합니다.", 그리고 현황이 다시 읽어 기록을 보입니다. 이미 철회된 것의 철회: "이 확인 지점은 이미 철회되어 있었습니다." 최신이 아닌 그림: 그 링크 옆에 "최신 아님"과 까닭 | API-112#200, API-129#409(`checkpoint_recorded`), `changed: false`인 API-129#200 |
| SCR-109#error | 페이지의 요청: [규칙 9](README.ko.md#모든-화면)의 메시지 페이지에 코드의 메시지, 추적 ID, 허브 페이지 링크. `internal`이면 다시 불러오기. 핵심 파일을 불러오지 못함: 페이지의 고정 문구와 그 링크만 남습니다. 다시 읽기: 현황은 그대로 두고 그 위 막대에 같은 메시지, 또는 "새로 읽지 못했습니다"와 다시 시도. 통과: 말 칸 위에 메시지, 말은 그대로 두고 같은 쓰기 ID로 보내는 다시 통과: 가리킨 칸 옆의 `invalid_request`, 서버 자체 주소의 이 페이지로 가는 링크를 단 `cross_site`, `part_not_found`와 `space_not_found`, 다시 통과가 새 쓰기 ID를 만드는 `write_id_reused`, 칸 옆의 `text_too_long`, 그리고 `body_too_large`, `json_required`, `internal`, `method_not_allowed`. 철회: `invalid_request`, `cross_site`, 현황이 다시 읽게 하는 `checkpoint_not_found`와 `project_not_found`, `write_id_reused`, 그리고 `internal`과 `method_not_allowed`. 연결 없음, 30초 안에 답 없음, `429`나 `503`: 규칙 8 | API-103#404(`part_not_found`, `project_not_found`, `not_found`), API-103#default(`internal`, `method_not_allowed`), API-104#403(`access_missing`, `access_other_app`), API-104#404(`not_found`), API-104#default(`internal`, `method_not_allowed`), API-112#404(`part_not_found`, `project_not_found`, `not_found`), API-112#default(`internal`, `method_not_allowed`), API-128#400(`invalid_request`), API-128#403(`cross_site`), API-128#404(`part_not_found`, `space_not_found`), API-128#409(`write_id_reused`), API-128#413(`text_too_long`, `body_too_large`), API-128#415(`json_required`), API-128#default(`internal`, `method_not_allowed`), API-129#400(`invalid_request`), API-129#403(`cross_site`), API-129#404(`checkpoint_not_found`, `project_not_found`), API-129#409(`write_id_reused`), API-129#default(`internal`, `method_not_allowed`) |
| SCR-109#permission | 페이지의 요청: 코드의 메시지를 담은 메시지 페이지. 다시 읽기, 통과, 철회: 말은 그대로 두고 코드의 메시지: 사람 본인의 로그인만 확인 지점을 통과시키거나 철회하므로(SPEC-139) `user_only`의 "본인이 직접 로그인해야 할 수 있습니다.", 그리고 `access_missing`과 `access_other_app`. 끝난 로그인: [규칙 7](README.ko.md#모든-화면) | API-103#403(`access_missing`, `access_other_app`), API-112#403(`access_missing`, `access_other_app`), API-128#403(`user_only`, `access_missing`, `access_other_app`), API-129#403(`user_only`, `access_missing`, `access_other_app`), `opaqueredirect` 응답이나 `401` |

단계의 모든 상태가 해당합니다. 현황에는 편집기가 없으므로, 핵심 파일의 실패는 그림 보기에서처럼 자기 상태가 아니라 여기서는 오류입니다.

## 경우의 수

| 종류 | 사용자가 보는 것 |
| --- | --- |
| 접근 | 사람 본인의 로그인만 통과시키고 철회합니다(SPEC-139): `user_only`, Worker의 `403`, 끝난 로그인은 SCR-109#permission |
| 입력 | 말은 붙이지 않아도 되고 2,000자까지입니다: 비었거나 공백뿐인 말은 요청에서 빠지고 확인 지점은 말 없이 통과하며, 한도를 넘으면 칸이 남은 글자 수를 세며 통과가 기다리고, `invalid_request`와 `text_too_long`은 칸 옆에 보입니다. 말은 그대로 있습니다 |
| 대상 | 스냅샷에 없는 프로젝트나 부분, 또는 13단계에 없는 단계: SCR-109#error. 현황을 읽은 뒤 없어진 항목: 그 패널이 그렇다고 알립니다(SCR-106#gone, SCR-107#gone, SCR-108#gone) |
| 상태 변화 | 기록을 기다리는 확인 지점, 또는 그사이 기록되거나 철회된 확인 지점: SCR-109#stale |
| 되풀이 | 통과와 철회는 도는 동안 막힙니다. 쓰기 ID를 실어 다시 보낸 통과는 확인 지점 하나를 남기고, 나중의 다시 통과는 두 번째 확인 지점을 만들며 둘 다 보입니다(SPEC-139) |
| 동시성 | 올라온 기록이나 다른 탭에서 한 철회는 현황이 다시 읽을 때 보입니다. 기록이 앞지른 철회: `checkpoint_recorded`, SCR-109#stale |
| 상한 | 목록마다 50개와 그 전체 수, 그림 보기는 500개를 늘어놓습니다. 말은 2,000자. 공간에 열린 어긋남이 1,000개였을 때의 "공간에 열린 어긋남이 1,000개라 {n}개를 열지 못했습니다."(`not_opened`) |
| 바깥 서비스 | 없음: 현황은 요청을 서버에만 보냅니다. PR의 링크는 따로 열립니다 |
| 자료 노출 | 단계의 기록, 점검, 항목뿐입니다. 확인 지점은 사용자가 통과시켰다는 것만 보이고 누구인지 이름은 절대 보이지 않습니다 |
| 빈 응답과 스트림 | 남은 것 없음: SCR-109#empty. 점검 없음: "점검에서 찾은 것이 없습니다." 스트림은 없습니다 |
| 화면 상태 | 모든 상태를 320과 1440픽셀에서, [와이어프레임](wireframes.html#scr-109)에 |
| AI 응답 | 없음: NEXUS는 AI 모델을 부르지 않습니다(REQ-121) |

## 배치

| 영역 | 320픽셀에서 | 1440픽셀에서 |
| --- | --- | --- |
| 위 막대 | 허브 페이지, 그다음 줄에 프로젝트·부분·단계, 그리고 그림 | 가운데의 너비 1,200픽셀 열에 한 줄로 |
| 기록 | 맨 먼저: 기록된 상태, 그 확인 지점과 다음 행동, 그다음 철회를 단 NEXUS에서 통과시킨 확인 지점 | 너비 400픽셀의 오른쪽 열 |
| 남은 것 | 기록 다음: 어긋남, 의견, 반영 대기를 저마다 그 전체 수를 단 목록으로 | 왼쪽 열 |
| 통과 | 남은 것 다음: 말 칸과 통과 | 오른쪽 열, 기록 아래 |
| 점검 | 맨 끝에 줄로 | 오른쪽 열, 통과 아래 |
