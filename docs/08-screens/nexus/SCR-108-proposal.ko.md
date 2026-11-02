# SCR-108 제안

[English](SCR-108-proposal.md)

목적: 사용자는 제안 하나를 그 까닭과 그것이 바꾸는 단계 원본의 글과 함께 읽고, 받거나 버립니다. 받은 뒤에는 그 반영을 지켜보고, 반영이 사용자를 필요로 하면 그 반영을 버립니다. (FL-110)

경로 `/pictures/{project}/{part}/{stage}#proposal={proposal}`. 그림 보기(SCR-105)의 패널이고 NEXUS 서버에만 있으며, 그 표시, 항목이나 의견의 패널, 단계 현황, 세션 속 링크에서 열립니다. 볼 수 있는 사람: Cloudflare Access가 들여보낸 누구나. 받기와 버리기에는 사람 본인의 로그인이 필요합니다. NEXUS 0.2에서 새로 생깁니다(SPEC-131, SPEC-133). [모든 화면](README.ko.md#모든-화면)의 규칙을 따릅니다.

## 자료

| 자료 | 출처 |
| --- | --- |
| 제안: 그 항목, 까닭, 바꿀 것, 그것이 답한 의견이나 어긋남, 그것을 낸 그림의 커밋, 열림·받음·버림·철회됨 가운데 어느 것인지, 닫힌 때 | 먼저 API-111(`proposals`, 또는 반영의 제안), 그다음 API-115 |
| 그것이 바꾸는 단계 원본의 글, 20,000자까지 | API-115(`source_text`) |
| 받은 제안의 반영: 반영 전, PR과 함께 검토 중, 사용자를 기다림, PR과 커밋과 함께 반영됨, 버림 | 닫히지 않은 동안은 API-111(`reflections`), 그림이 더는 늘어놓지 않으면 API-116([변경 3](README.ko.md#앞-단계의-변경)) |

## 동작

| 동작 | 결과 | 실패 |
| --- | --- | --- |
| 받기 | "받음, 아직 반영 전": 그림의 문서 판에 묶인 반영 대기가 생기고, 그림은 그 항목에 표시를 답니다. 그림 자체는 바뀌지 않습니다(SPEC-131) | 이미 열려 있지 않음: SCR-108#stale. 그 밖에는 SCR-108#error나 SCR-108#permission |
| 버리기 | "버림": 그것이 답한 의견은 버린 제안이 있다는 표시와 함께 열린 채로 남고, "까닭을 답글로 달기"가 보입니다 | 위와 같음 |
| 버린 뒤 까닭을 답글로 달기 | 칸이 준비된 의견 패널 SCR-107 | SCR-107과 같음 |
| 반영이 사용자를 필요로 할 때 반영 버리기 | "반영을 버렸습니다."와 함께 반영이 닫힙니다(SPEC-133) | 다른 상태: SCR-108#stale. 그 밖에는 SCR-108#error나 SCR-108#permission |
| 의견, 어긋남의 항목, PR 열기 | SCR-107, SCR-106, 또는 따로 열리는 PR | SCR-107#gone, SCR-106#gone |
| 닫기, Escape, 브라우저의 뒤로 단추 | `#proposal=`이 빠진 주소의 그림 | 없음 |

## 상태

| 상태 | 사용자가 보는 것과 할 수 있는 것 | 이어지는 응답 |
| --- | --- | --- |
| SCR-108#loading | 그림의 자료가 담은 제안, 곧 그 항목, 까닭, 바꿀 것, 상태가 보이고, 단계 원본 글의 자리에 그 길이를 적은 회색 상자가 있습니다. 받기와 버리기는 제안을 기다립니다 | API-115를 보낸 뒤, 그 답이 오기 전 |
| SCR-108#normal | 제목으로 "{items}에 대한 제안"이 포커스를 받고 닫기가 함께 있습니다. 그 까닭, 바꿀 것, 따로 스크롤되는 상자 속 단계 원본의 글, 그것을 낸 커밋, 그것이 답한 의견이나 어긋남. 열림: 받기와 버리기. 받음: 그 반영, 곧 "받음, 아직 반영 전", "검토 중: {pull request}", 반영 버리기를 단 "단계 원본이 바뀌어 이 변경이 더는 맞지 않습니다. 에이전트가 의견에서 묻습니다.", "{pull request}로 반영됨", "반영을 버렸습니다." 버림: "{date}에 버림. 의견은 열린 채로 남습니다." 철회됨: "{date}에 에이전트가 철회함." | API-115#200, API-116#200, API-124#200, API-125#200, `changed: true`인 API-127#200 |
| SCR-108#stale | 그사이 바뀐 것을 제안을 다시 읽어 보입니다: `proposal_not_open`의 "이 제안은 이제 열려 있지 않습니다. 상태: {받음, 버림, 철회됨}", `edit_state`의 "이 반영은 그사이 바뀌었습니다. 지금 상태: {state}", 반영 버리기 뒤의 "이 반영은 이미 버려져 있었습니다." 그린 그림보다 앞 그림에서 낸 제안: "커밋 {commit}의 그림에서 낸 제안입니다. 그 뒤 단계 원본이 바뀌었을 수 있습니다." 에이전트가 최신 단계 원본에 견주어 확인하므로 받기는 그대로 있습니다(SPEC-133) | API-124#409(`proposal_not_open`), API-125#409(`proposal_not_open`), API-127#409(`edit_state`), `changed: false`인 API-127#200 |
| SCR-108#error | 읽기: "이 제안을 불러오지 못했습니다."와 다시 시도, 그리고 그림의 자료가 담은 제안. 쓰기: 단추 위에 메시지와 같은 쓰기 ID로 보내는 다시 시도: `invalid_request`, 서버 자체 주소의 이 페이지로 가는 링크를 단 `cross_site`, `reflection_limit`의 "이 프로젝트의 반영 대기가 한도(500개)에 닿았습니다. 제안은 열린 채로 둡니다.", 다시 시도가 새 쓰기 ID를 만드는 `write_id_reused`, 그리고 `internal`과 `method_not_allowed`. 연결 없음, 30초 안에 답 없음, `429`나 `503`: 규칙 8 | API-115#default(`internal`, `method_not_allowed`), API-116#default(`internal`, `method_not_allowed`), API-124#400(`invalid_request`), API-124#403(`cross_site`), API-124#409(`reflection_limit`, `write_id_reused`), API-124#default(`internal`, `method_not_allowed`), API-125#400(`invalid_request`), API-125#403(`cross_site`), API-125#409(`write_id_reused`), API-125#default(`internal`, `method_not_allowed`), API-127#400(`invalid_request`), API-127#403(`cross_site`), API-127#409(`write_id_reused`), API-127#default(`internal`, `method_not_allowed`) |
| SCR-108#permission | 단추 위에 코드의 메시지: 사람 본인의 로그인만 받고 버리므로(SPEC-116) `user_only`의 "본인이 직접 로그인해야 할 수 있습니다.", 그리고 `access_missing`과 `access_other_app`. 끝난 로그인: [규칙 7](README.ko.md#모든-화면) | API-115#403(`access_missing`, `access_other_app`), API-116#403(`access_missing`, `access_other_app`), API-124#403(`user_only`, `access_missing`, `access_other_app`), API-125#403(`user_only`, `access_missing`, `access_other_app`), API-127#403(`user_only`, `access_missing`, `access_other_app`), `opaqueredirect` 응답이나 `401` |
| SCR-108#gone | "이 제안은 서버에 없습니다."나 "이 반영은 서버에 없습니다."와 그림으로 돌아가는 링크, 그리고 그림을 다시 읽습니다 | API-115#404(`proposal_not_found`, `project_not_found`), API-116#404(`edit_not_found`, `project_not_found`), API-124#404(`proposal_not_found`, `project_not_found`), API-125#404(`proposal_not_found`, `project_not_found`), API-127#404(`edit_not_found`, `project_not_found`) |

해당하지 않는 것:

- 비어 있음: 제안은 언제나 그 까닭과 바꿀 것을 담습니다.

## 경우의 수

| 종류 | 사용자가 보는 것 |
| --- | --- |
| 접근 | 사람 본인의 로그인만 받고 버립니다(SPEC-116): `user_only`와 끝난 로그인은 SCR-108#permission |
| 입력 | 패널에 닿지 않습니다: 그 쓰기는 글 없이 쓰기 ID만 싣습니다 |
| 대상 | 서버에 없는 제안이나 반영, 또는 그것을 가리키는 주소: SCR-108#gone |
| 상태 변화 | 다른 탭이나 에이전트가 받거나 버리거나 철회함, 또는 다른 상태의 반영: 다시 읽은 SCR-108#stale(SPEC-131) |
| 되풀이 | 받기, 버리기, 반영 버리기는 도는 동안 막힙니다. 한 쓰기 ID로 두 번 받아도 반영 대기는 하나입니다(SPEC-131) |
| 동시성 | 다른 탭에서 닫힌 제안: `proposal_not_open`, SCR-108#stale. 반영에 대한 에이전트의 보고는 패널이 다시 읽을 때 보입니다 |
| 상한 | 공간의 반영 대기 500개: `reflection_limit`, 제안은 열린 채로 남습니다. 20,000자까지의 단계 원본 글은 자기 상자 안에서 스크롤됩니다 |
| 바깥 서비스 | PR의 링크는 따로 열립니다. 패널의 나머지는 그대로입니다 |
| 자료 노출 | 단계 원본의 글은 따로 읽어(API-115) 여기서만 보입니다. 쓴 쪽의 종류 말고는 신원이 없습니다 |
| 빈 응답과 스트림 | 패널에 닿지 않습니다: 제안은 비지 않습니다. 스트림은 없습니다 |
| 화면 상태 | 모든 상태를 320과 1440픽셀에서, [와이어프레임](wireframes.html#scr-108)에 |
| AI 응답 | 없음: NEXUS는 AI 모델을 부르지 않습니다(REQ-121). 에이전트의 제안은 허브를 거쳐 쓴 글입니다 |

## 배치

| 영역 | 320픽셀에서 | 1440픽셀에서 |
| --- | --- | --- |
| 패널 | 그림 위로 높이의 85퍼센트까지 올라오는 아래쪽 시트, 맨 위에 손잡이, 제목, 닫기 | 그림 옆, 너비 400픽셀의 옆 패널. 그림의 그 항목들은 표시가 남습니다 |
| 제안 | 까닭, 바꿀 것, 자기 스크롤 상자 속 단계 원본의 글, 그 아래 그것이 답한 것 | 같은 차례로, 옆 패널 안에 |
| 단추 | 시트 바닥: 나란한 받기와 버리기, 또는 반영의 상태와 그 단추 | 옆 패널 바닥 |
