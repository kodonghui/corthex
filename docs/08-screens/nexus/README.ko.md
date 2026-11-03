# NEXUS: 화면 상태

[English](README.md)

CORTHEX 자신의 프로젝트에서 NEXUS 0.2의 08단계입니다: [사이트맵](../../07-sitemap/nexus.ko.md)의 화면 아홉 개마다 정의 하나, 곧 그 화면이 보여 주는 자료와 저마다 어느 요청에서 오는지, 그 동작과 결과와 실패, 그리고 모든 상태와 그것으로 이어지는 응답; 그리고 이 파일에 있는 모든 화면에 걸리는 규칙, 메시지의 최종 문구, 정의에서 그린 [와이어프레임](wireframes.html)입니다. 상태: 2026-11-03 초안이며, 관리자가 2026-11-02에 고른 대로 기억 플러그인을 만드는 동안, 확인 지점이 아직 열려 있는 사용자 흐름, 기능 명세, 서버의 자료, 인터페이스, 사이트맵의 추천을 따라 썼습니다. 관리자는 이 단계를 그것들과 함께 확인합니다. 이 번역과 영어 원문이 다르면 영어 원문이 원본입니다.

입력: [docs/07-sitemap/nexus.yaml](../../07-sitemap/nexus.yaml)의 사이트맵(SCR-101\~SCR-109)과 그 [08단계를 위한 메모](../../07-sitemap/nexus.ko.md#08단계-화면-상태); [docs/04-functional-spec/nexus.ko.md](../../04-functional-spec/nexus.ko.md)의 기능 명세, 특히 SPEC-119, SPEC-122\~SPEC-127, SPEC-131\~SPEC-134, SPEC-138, SPEC-139와 그 [07·08단계를 위한 메모](../../04-functional-spec/nexus.ko.md#0708단계-화면); [docs/06-api/nexus.ko.md](../../06-api/nexus.ko.md)의 인터페이스와 계약 [nexus.openapi.yaml](../../06-api/nexus.openapi.yaml), 상태는 그 응답과 [오류 코드](../../06-api/nexus.ko.md#오류-코드)를 따르며, 그 [07·08단계를 위한 메모](../../06-api/nexus.ko.md#0708단계-화면)와 함께; [docs/05-erd/nexus.ko.md](../../05-erd/nexus.ko.md)의 서버의 자료, 거기서 오는 표시를 위해; [docs/03-user-flow/nexus/](../../03-user-flow/nexus/README.ko.md)에 있는, 브라우저에서 도는 사용자 흐름 FL-105\~FL-107, FL-109, FL-110, FL-113, FL-115; 그리고 지금 도는 1차의 허브 페이지 [hub.html](../../../plugins/corthex-nexus/skills/corthex-hub/assets/hub.html), 허브 페이지와 그 보기는 그 상태를 그대로 둡니다. 기억 플러그인에는 화면이 없으므로 이 단계에는 그 파일이 없습니다.

이 단계의 기본 사람 화면은 정의에서 그린 회색 와이어프레임입니다. 여기서는 그것이 한 페이지 [wireframes.html](wireframes.html)이며 상태마다 320과 1440픽셀의 틀이 있고, 저장소가 공개이므로 사람은 그것을 링크가 프로젝트의 기록에 있는 비공개 게시 페이지로 봅니다. 정의는 프로젝트의 Notion 기록에 있는 한국어 사본으로 읽으며, 표는 거기서 데이터베이스입니다. `.corthex/project.json`이 이 선택을 적어 둡니다.

## 화면

- [SCR-101 허브 페이지](SCR-101-hub-page.ko.md), `/`: normal, empty, stale, error, permission.
- [SCR-102 검색 결과](SCR-102-search-results.ko.md), `/#q={words}`: normal, empty.
- [SCR-103 추적 화면](SCR-103-trace-view.ko.md), `/#p={project}&id={id}`: normal, error.
- [SCR-104 단계 자세히 보기](SCR-104-stage-detail.ko.md), `/#p={project}&s={stage}`: normal, empty, stale, error.
- [SCR-105 그림 보기](SCR-105-picture-view.ko.md), `/pictures/{project}/{part}/{stage}`: loading, normal, large, empty, stale, error, code-failed, permission.
- [SCR-106 항목](SCR-106-item.ko.md), `#item={id}`: normal, empty, loading, error, permission, gone.
- [SCR-107 의견](SCR-107-comment.ko.md), `#comment={comment}`: loading, normal, stale, error, permission, gone.
- [SCR-108 제안](SCR-108-proposal.ko.md), `#proposal={proposal}`: loading, normal, stale, error, permission, gone.
- [SCR-109 단계 현황](SCR-109-stage-overview.ko.md), `/overview/{project}/{part}/{stage}`: loading, normal, empty, stale, error, permission.

## 정의서를 읽는 법

- **목적**: 그 화면을 지나는 흐름에서 온 한 문장과 그 FL ID. 그다음 화면의 경로, 볼 수 있는 사람, 그리고 1차에서 만들었는지 NEXUS 0.2에서 새로 생기는지.
- **자료**: 화면이 보여 주는 것과 저마다 어디서 오는지: API ID로 적은 계약의 요청, 페이지 자신의 자료, 페이지의 주소, 또는 브라우저 저장소.
- **동작**: 저마다 그 결과와 실패이며, 실패는 그것이 이어지는 상태를 적습니다.
- **상태**: 상태마다 `SCR-105#empty`처럼 적은 그 ID, 사용자가 보는 것과 할 수 있는 것, 그리고 `API-111#404`처럼 적은 그것으로 이어지는 응답과, 괄호 안에 그것을 정하는 오류 코드. 계약이 화면의 요청에 늘어놓는 모든 응답이 어느 상태로 이어지고, 계약이 그 응답에 주는 모든 코드가 적혀 있습니다. 표 아래에는 해당하지 않는 단계의 상태와 그 까닭.
- **경우의 수**: 04, 06, 12단계가 쓰는 종류 12가지, 저마다 화면이 보여 주는 것, 또는 그것이 왜 화면에 닿지 않는지.
- **배치**: NEXUS가 받치는 가장 좁은 폭과 가장 넓은 폭인 320과 1440픽셀(REQ-101, REQ-146)에서의 화면의 영역이며, 와이어프레임이 그것을 그립니다.

## 모든 화면

1. **글로만.** 프로젝트의 글, 의견, 답글, 까닭, 단계 원본의 글은 글로만 보입니다: 그 안의 어떤 것도 마크업으로 읽히거나 돌지 않습니다(REQ-098, REQ-148). 긴 글은 줄을 바꾸고, 긴 낱말이나 ID는 페이지를 넓히지 않고 끊겨서, 320에서 1440픽셀까지 어느 폭에서도 페이지가 옆으로 밀리지 않습니다(REQ-101, REQ-146). 틀보다 큰 그림은 틀 안에서 움직이고, 제안의 단계 원본 글은 자기 상자 안에서 스크롤됩니다.
2. **언어와 테마.** 모든 화면은 그 페이지 자료의 언어 `lang`으로 말합니다. 그것은 서버의 `NEXUS_LANGUAGE`에서, 기기에서는 프로필에서 오며 영어나 한국어입니다. 화면은 시스템의 밝은 모드나 어두운 모드를 따릅니다(REQ-099, REQ-100, REQ-150). 시각은 1차처럼 브라우저의 시간대로 보입니다.
3. **메시지.** 거절이나 오류는 [메시지](#메시지)에서 그 코드의 메시지를 페이지의 언어로 보이고, 답의 `detail`은 절대 보이지 않으며, 그 아래 작은 글자로 서버의 로그에도 있는 "추적 ID {traceId}"를 보입니다([고른 것 4](#이-단계가-고른-것)).
4. **쓰기.** 쓰기의 단추는 그 요청이 도는 동안 막히고 "보내는 중…"이라고 적힙니다. 보기는 쓰기마다 쓰기 ID 하나, 곧 `nw_` ID를 만들어 그 쓰기를 시도할 때마다 실어, 답을 잃은 뒤의 시도가 결과 하나를 남기게 합니다(SPEC-126). `write_id_reused` 뒤에는 다음 시도가 새 ID를 씁니다. 그 요청은 서버에만, JSON으로, `redirect: "manual"`과 함께 갑니다.
5. **보내지 않은 글.** 4,000자까지의 의견이나 답글의 글과 2,000자까지의 확인 지점의 말은, 서버가 받을 때까지 그 칸과, 그 그림과 항목, 그 의견, 또는 그 부분과 단계의 브라우저 저장소에 쓰기 ID와 함께 남고, 다시 불러온 뒤 돌아옵니다(SPEC-126). 한도의 90퍼센트부터 칸은 남은 글자 수를 보이며, 한도를 넘는 글은 보내지 않습니다. 빈 글이나 공백뿐인 의견과 답글은 보내지 않습니다. 확인 지점의 말은 비워 둘 수 있습니다: 비었거나 공백뿐인 말은 요청에서 빠지고, 확인 지점은 말 없이 통과합니다(SPEC-139). 일부 비공개 창처럼 브라우저가 저장소를 두지 않는 곳에서는 글이 페이지에만 남습니다.
6. **다시 읽기.** 쓰기 뒤 보기는 그 자료, 곧 그림(API-111)이나 현황(API-112)을, 열린 패널은 그 의견(API-114)이나 제안(API-115)을 다시 읽습니다. 그동안 "새로 읽는 중…"이 보이고 화면은 그대로 쓸 수 있습니다. 그린 그림보다 새 그림은 사용자 밑에서 다시 그리지 않고 권합니다(SCR-105#stale). 다시 읽기가 실패하면 화면은 보이던 것을 그대로 두고 "새로 읽지 못했습니다. 보이는 내용이 최신이 아닐 수 있습니다."와 다시 시도를 보입니다.
7. **로그인.** 서버에서는 모든 페이지와 요청이 Cloudflare Access 뒤에 있고, 그 로그인 페이지와 거절은 Access 자신의 것으로 사이트맵 밖에 있습니다. 보기가 열린 동안 로그인이 끝나면 요청은 Access의 리다이렉트를 받고, 보기는 그것을 `opaqueredirect` 응답으로 보거나 `401`을 받습니다. 그러면 보기는 로그인이 끝났다고 알리고, 사용자가 쓴 것을 그대로 두며, 다시 로그인을 둡니다. 다시 로그인은 Access의 로그인을 거쳐 페이지를 다시 불러오고, 그 패널과 함께 같은 주소로 돌아옵니다.
8. **연결.** 네트워크 없음, 30초 안에 답 없음, 또는 Cloudflare의 `429`나 `503`: [메시지](#메시지)의 그 메시지와 다시 시도가 있는 오류이며, 화면의 나머지는 그대로 돌고 사용자가 쓴 것은 남습니다.
9. **페이지의 거절.** 세 페이지, 곧 허브 페이지(API-101), 그림 보기(API-102), 단계 현황(API-103)은 거절하거나 실패한 브라우저의 요청에 서버의 언어로 된 메시지 하나의 작은 HTML 페이지로 답하며, 거기에는 추적 ID, 다시 불러오기, 허브 페이지 링크가 있습니다([변경 1](#앞-단계의-변경)). 보기 자신의 자료는 `problem`에 Problem Details를 담습니다.
10. **패널과 주소.** 항목, 의견, 제안의 패널은 `#` 뒤의 주소 `item=`, `comment=`, `proposal=`에서 곧바로, 휴대폰에서도 열립니다. 어느 항목도 담지 않는 부분은 자기 주소 없이 항목 패널을 엽니다([고른 것 12](#이-단계가-고른-것)). 포커스는 패널의 제목으로 옮겨 가고, Escape, 닫기, 브라우저의 뒤로 단추는 패널을 닫고 그림의 주소를 남깁니다. 허브 페이지는 1차의 주소, 곧 `q`, 그리고 `id`나 `s`가 붙은 `p`를 그대로 둡니다.
11. **누구에게나 같음.** 화면은 그것을 보는 모든 사람, 곧 사용자와 Access가 들여보낸 다른 누구에게나 같은 것을 보입니다. 누가 무엇을 할 수 있는지는 요청의 로그인을 따릅니다: 제안을 받거나 버리기, 반영 버리기, 확인 지점을 통과시키거나 철회하기에는 사람 본인의 로그인이 필요하고(API-124, API-125, API-127\~API-129), 거절은 그 메시지를 보입니다. 어느 화면도 이메일 주소, 이름, 그 밖의 신원의 어떤 부분도 보이지 않습니다: 항목은 쓴 쪽의 종류 "사용자"나 "에이전트"를 보입니다(REQ-163, [고른 것 9](#이-단계가-고른-것)).
12. **목록과 한도.** 읽기가 잘라 내는 목록은 "73개 중 50개"처럼 전체 가운데 몇 개를 담았는지 보입니다. 단계 현황은 저마다 50개를 늘어놓고, 500개를 늘어놓는 그림 보기로 잇습니다. 999를 넘는 수는 `999+`로 보입니다(SPEC-123).

## 응답과 상태

NEXUS의 요청이 답하는 대로 쓴 단계의 기본값입니다. 정의마다 자기 요청의 응답을 적습니다.

| 응답 | 상태 | 사용자가 보는 것 |
| --- | --- | --- |
| 자료가 있는 `200`이나 `201` | normal | 그 자료. 쓰기 뒤에는 그 결과와 다시 읽은 자료 |
| 빈 목록이 있는 `200`, 또는 문제 `picture_not_found` | empty | 무엇이 나타날지와 그것이 어떻게 나타나는지 |
| `changed: false`인 `200` | stale | 다른 탭이나 에이전트가 이미 했다는 것과 다시 읽은 자료 |
| `400` `invalid_request` | error | `field`가 가리킨 칸 옆의 메시지, 입력은 그대로 |
| `401`, 또는 `opaqueredirect` 응답으로 온 Access의 리다이렉트 | permission | 로그인이 끝남: 다시 로그인, 입력은 그대로(규칙 7) |
| `403` `access_missing`, `access_other_app`, `user_only`, `no_kind` | permission | 코드의 메시지로 본 까닭과 돌아갈 길, 입력은 그대로 |
| `403` `cross_site` | error | 메시지와, 서버 자체 주소의 그 페이지로 가는 링크 |
| 프로젝트, 그 공간, 부분, 단계의 `404` | error | 코드의 메시지와 허브 페이지 링크 |
| 항목, 곧 의견, 어긋남, 제안, 반영, 확인 지점의 `404` | 패널에서는 gone, 그 밖에는 error | 그것이 서버에 없다는 것. 보기는 다시 읽습니다 |
| 상태의 `409`: `proposal_not_open`, `edit_state`, `checkpoint_recorded` | stale | 그것이 지금 무엇인지와 다시 읽은 자료 |
| 한도의 `409`: `comment_limit`, `reply_limit`, `reflection_limit`, `space_full` | error | 한도, 글은 그대로. `reply_limit`이면 새 의견을 권함 |
| `409` `write_id_reused` | error | 새 쓰기 ID를 만드는 다시 시도 |
| `413` `text_too_long`이나 `body_too_large` | error | 칸 옆의 한도, 글은 그대로 |
| `415`, `500`, 그 밖의 오류 | error | 메시지와 다시 시도, 화면이 담은 것은 그대로 |
| Cloudflare의 `429`나 `503`, 네트워크 없음, 30초 안에 답 없음 | error | 메시지와 다시 시도(규칙 8) |

NEXUS가 단계의 기본값과 다른 곳: `401`은 서버가 아니라 Access의 것이고, 끝난 로그인만 그것을 보기에 가져옵니다. 항목의 `404`는 패널 자신의 상태 `gone`으로 이어집니다. 한도의 `409`는 글을 그대로 두는 오류입니다. 요청은 제 꼴이었고 가득 찬 것은 공간이기 때문입니다.

## 메시지

화면이 보이는 06단계 [오류 코드](../../06-api/nexus.ko.md#오류-코드)의 메시지와 화면 자신의 메시지의 최종 문구입니다. `{limit}`, `{state}`와 중괄호 속 다른 이름은 답이나 자료에서 채웁니다. 한국어는 1차의 허브 페이지처럼 존댓말로 씁니다.

### 오류 코드

| 코드 | 상태 | 영어 | 한국어 |
| --- | --- | --- | --- |
| `invalid_request` | 400 | This could not be sent: check the marked field. | 보내지 못했습니다. 표시한 칸을 확인해 주세요. |
| `access_missing` | 403 | Cloudflare Access did not check this request. Protect the server with Access first. | Cloudflare Access가 이 요청을 확인하지 않았습니다. 먼저 서버를 Access로 보호해 주세요. |
| `access_other_app` | 403 | This request was checked for another Access application. Check the server's Access settings. | 이 요청은 다른 Access 애플리케이션용으로 확인되었습니다. 서버의 Access 설정을 확인해 주세요. |
| `cross_site` | 403 | A change from another site is refused. Open this page at the server's own address. | 다른 사이트에서 보낸 변경은 받지 않습니다. 서버 주소에서 이 페이지를 열어 주세요. |
| `user_only` | 403 | Only you can do this, signed in yourself. | 본인이 직접 로그인해야 할 수 있습니다. |
| `no_kind` | 403 | This sign-in cannot write here. Check the Access policy. | 이 로그인으로는 여기에 쓸 수 없습니다. Access 정책을 확인해 주세요. |
| `not_found` | 404 | Not found. | 찾을 수 없습니다. |
| `project_not_found` | 404 | This project is not on the server. | 이 프로젝트는 서버에 없습니다. |
| `space_not_found` | 404 | This project was pushed only by an older hub, so it has no pictures or checkpoints here yet. Push it with corthex-nexus 0.2. | 이 프로젝트는 이전 허브로만 올라와 아직 그림과 확인 지점이 없습니다. corthex-nexus 0.2로 올려 주세요. |
| `part_not_found` | 404 | This part is not in the project's snapshot. | 이 부분은 프로젝트의 스냅샷에 없습니다. |
| `picture_not_found`, `why`가 `not-drawn` | 404 | No picture is drawn yet for this stage and part. It appears after a push that holds the stage's document. | 이 단계와 부분의 그림은 아직 없습니다. 단계 문서를 담은 스냅샷을 올리면 나타납니다. |
| `picture_not_found`, `why`가 `size` | 404 | This picture was left out: its source is larger than a snapshot may hold. | 원본이 스냅샷에 담을 수 있는 크기보다 커서 이 그림은 빠졌습니다. |
| `picture_not_found`, `why`가 `other-repository` | 404 | This picture was left out: its source is in another repository. | 원본이 다른 저장소에 있어서 이 그림은 빠졌습니다. |
| `comment_not_found` | 404 | This comment is not on the server. | 이 의견은 서버에 없습니다. |
| `discrepancy_not_found` | 404 | This discrepancy is not on the server. | 이 어긋남은 서버에 없습니다. |
| `proposal_not_found` | 404 | This proposal is not on the server. | 이 제안은 서버에 없습니다. |
| `edit_not_found` | 404 | This reflection is not on the server. | 이 반영은 서버에 없습니다. |
| `checkpoint_not_found` | 404 | This checkpoint is not on the server. | 이 확인 지점은 서버에 없습니다. |
| `method_not_allowed` | 405 | This request is not allowed here. Load the page again. | 여기서는 할 수 없는 요청입니다. 페이지를 다시 불러와 주세요. |
| `comment_limit` | 409 | This project holds as many comments as it may ({limit}). Your text stays here. | 이 프로젝트에 남길 수 있는 의견({limit}개)이 다 찼습니다. 쓴 글은 여기 남아 있습니다. |
| `reply_limit` | 409 | This comment holds as many replies as it may ({limit}). Leave a new comment. | 이 의견에 달 수 있는 답글({limit}개)이 다 찼습니다. 새 의견으로 남겨 주세요. |
| `reflection_limit` | 409 | This project holds as many pending reflections as it may ({limit}). The proposal stays open. | 이 프로젝트의 반영 대기가 한도({limit}개)에 닿았습니다. 제안은 열린 채로 둡니다. |
| `space_full` | 409 | This project's space is full. Your text stays here. | 이 프로젝트의 공간이 가득 찼습니다. 쓴 글은 여기 남아 있습니다. |
| `proposal_not_open` | 409 | This proposal is no longer open: it was {state}. | 이 제안은 이제 열려 있지 않습니다. 상태: {state} |
| `edit_state` | 409 | This reflection changed meanwhile: it is now {state}. | 이 반영은 그사이 바뀌었습니다. 지금 상태: {state} |
| `checkpoint_recorded` | 409 | This checkpoint is recorded, so it cannot be withdrawn here. Changing it is a new decision. | 이 확인 지점은 이미 기록되어 여기서 철회할 수 없습니다. 바꾸려면 새로 결정해야 합니다. |
| `write_id_reused` | 409 | This could not be sent. Try again. | 보내지 못했습니다. 다시 시도해 주세요. |
| `body_too_large` | 413 | This is larger than the server takes. | 서버가 받는 크기보다 큽니다. |
| `text_too_long` | 413 | This text is too long: {limit} characters at most. | 글이 너무 깁니다. {limit}자까지 쓸 수 있습니다. |
| `json_required` | 415 | This could not be sent. Load the page again, then try again. | 보내지 못했습니다. 페이지를 다시 불러온 뒤 다시 시도해 주세요. |
| `internal` | 500 | Something went wrong on the server. Try again. | 서버에서 문제가 생겼습니다. 다시 시도해 주세요. |

`{state}`에 들어가는 상태: 제안은 받음, 버림, 철회됨(accepted, dismissed, withdrawn), 반영은 `pending`, `in-review`, `needs-user`, `closed`, `dismissed`에 따라 반영 전, 검토 중, 사용자를 기다림, 반영됨, 버림(not yet reflected, in review, waiting for the user, reflected, dismissed)입니다.

다른 코드는 어느 화면도 보이지 않습니다. `agent_only`, `claimed`, `comment_closed`는 에이전트의 쓰기만 거절하고, `invalid_snapshot`, `clock_ahead`, `unknown_item`, `older_snapshot`, `commit_not_replaced`, `too_many_projects`, `repository_mismatch`, `proposal_limit`, `pull_request_reported`, `pull_request_mismatch`, `entry_closed`, `checkpoint_withdrawn`, `snapshot_too_large`, `entry_not_found`는 허브에만 닿으며 허브는 세션에서 `detail`을 보입니다. 그 메시지는 06단계가 쓴 초안 그대로입니다.

### 화면 자신의 메시지

| 메시지 | 나오는 곳 | 영어 | 한국어 |
| --- | --- | --- | --- |
| 끝난 로그인 | 모든 보기(규칙 7) | Your sign-in has expired. Sign in again: what you wrote stays here. | 로그인이 끝났습니다. 다시 로그인해 주세요. 쓴 글은 여기 남아 있습니다. |
| 연결 없음 | 모든 보기(규칙 8) | No connection to the server. Check the network, then try again. | 서버에 연결되지 않습니다. 네트워크를 확인한 뒤 다시 시도해 주세요. |
| 제때 답 없음 | 모든 보기(규칙 8) | The server did not answer in time. Try again. | 서버가 제때 답하지 않았습니다. 다시 시도해 주세요. |
| 바쁨 | 모든 보기(규칙 8) | The server is busy. Wait a moment, then try again. | 서버가 바쁩니다. 잠시 뒤 다시 시도해 주세요. |
| 추적 ID | 모든 오류 아래(규칙 3) | Trace ID {traceId} | 추적 ID {traceId} |
| 새로 읽는 중 | 모든 보기(규칙 6) | Updating… | 새로 읽는 중… |
| 새로 읽지 못함 | 모든 보기(규칙 6) | Could not update. What you see may be out of date. | 새로 읽지 못했습니다. 보이는 내용이 최신이 아닐 수 있습니다. |
| 보내는 중 | 모든 쓰기(규칙 4) | Sending… | 보내는 중… |
| 남은 글자 수 | 모든 칸(규칙 5) | {n} characters left | {n}자 남음 |
| 읽지 못한 페이지 자료 | SCR-101 | This page's data could not be read. Load the page again. On a device: Build the hub again. | 이 페이지의 데이터를 읽지 못했습니다. 페이지를 다시 불러와 주세요. 기기에서는 허브를 다시 만들어 주세요. |
| 빈 서버 | SCR-101 | Nothing has been pushed to this server yet. It shows each pushed project's stages, checks and pictures. To push a project: register it with the corthex skill; list it in `nexus.push` with this server's address in `nexus.url`; set the service token's two environment variables, `CORTHEX_NEXUS_CLIENT_ID` and `CORTHEX_NEXUS_CLIENT_SECRET`; then have the agent show a dry run and push. | 아직 이 서버에 올라온 프로젝트가 없습니다. 이 서버는 올라온 프로젝트마다 단계, 점검, 그림을 보여 줍니다. 프로젝트를 올리려면 corthex 스킬로 등록하고, `nexus.push`에 넣고 `nexus.url`에 이 서버의 주소를 적고, 서비스 토큰의 환경 변수 두 개 `CORTHEX_NEXUS_CLIENT_ID`와 `CORTHEX_NEXUS_CLIENT_SECRET`을 설정한 뒤, 에이전트에게 미리 보기를 보이고 올려 달라고 하세요. |
| 서버에 있음 | 기기의 SCR-101, SCR-104 | The pictures, comments and stage overviews are on the NEXUS server. | 그림, 의견, 단계 현황은 NEXUS 서버에 있습니다. |
| 페이지에 없는 프로젝트 | SCR-103, SCR-104 | This project is not on this page. | 이 프로젝트는 이 페이지에 없습니다. |
| 단계가 아님 | SCR-104 | This stage is not one of the 13. | 13단계에 없는 단계입니다. |
| 보기를 불러오는 중 | 코드가 돌기 전의 SCR-105 | Loading the picture view. If it does not appear, load the page again. | 그림 보기를 불러오는 중입니다. 나타나지 않으면 페이지를 다시 불러와 주세요. |
| 그리는 중 | SCR-105 | Drawing the picture… | 그림을 그리는 중… |
| 큰 그림 | SCR-105 | This picture is large ({n} elements), so drawing it may take longer. | 이 그림은 요소가 {n}개로 커서 그리는 데 시간이 더 걸릴 수 있습니다. |
| 최신 아님 | SCR-105 | This picture shows commit {commit}: its newest source is larger than a snapshot may hold. Or: its newest source is gone from the repository. Or: its newest source is in another repository. | 이 그림은 커밋 {commit}의 그림입니다. 최신 원본이 스냅샷에 담을 수 있는 크기보다 큽니다. 또는: 최신 원본이 저장소에서 사라졌습니다. 또는: 최신 원본이 다른 저장소에 있습니다. |
| 링크 옆의 최신 아님 | SCR-104, SCR-109 | Not current: its newest source is larger than a snapshot may hold. Or: is gone from the repository. Or: is in another repository. | 최신 아님: 최신 원본이 스냅샷에 담을 수 있는 크기보다 큼. 또는: 저장소에서 사라짐. 또는: 다른 저장소에 있음. |
| 새 판 | SCR-105 | A newer version of this picture is on the server. Show it | 서버에 이 그림의 새 판이 있습니다. 보기 |
| 코드 실패 | SCR-105 | The picture could not be drawn here, so its items are listed instead. | 여기서는 그림을 그리지 못해 항목을 목록으로 보여 드립니다. |
| 따로 | SCR-105 | Apart: comments whose item is gone ({n}) | 따로: 항목이 없어진 의견 ({n}) |
| 기다림 | SCR-105, SCR-106 | Waits for a current picture | 최신 그림을 기다림 |
| 받음 | SCR-105, SCR-108 | Accepted, not yet reflected | 받음, 아직 반영 전 |
| 의견 없음 | SCR-106 | No comments on {id} yet. | {id}에는 아직 의견이 없습니다. |
| 그림에 없음 | SCR-106 | {id} is not in this picture. | {id} 항목은 이 그림에 없습니다. |
| ID 없음 | SCR-106 | No ID: comments on it are kept on the picture, with its name as the quote. | ID가 없어, 의견은 이 이름을 인용으로 붙여 그림에 남습니다. |
| 의견의 상태 | SCR-107 | Waiting for the agent. Waiting for the user. Settled by the user, waiting for the agent's record. A proposal was dismissed. Closed as answered. Closed with a decision. | 에이전트를 기다림. 사용자를 기다림. 사용자가 정함, 에이전트의 기록을 기다림. 제안을 버림. 답이 나서 닫힘. 결정으로 닫힘. |
| 답글 없음 | SCR-107 | No replies yet. | 아직 답글이 없습니다. |
| 정함 | SCR-107 | This settles it | 이것으로 정함 |
| 다시 열기 | SCR-107 | Reply and open again | 답글 달고 다시 열기 |
| 이미 닫힘 | SCR-107 | This comment was already closed. | 이 의견은 이미 닫혀 있었습니다. |
| 불러오지 못함 | SCR-107, SCR-108 | Could not load this comment. Or: Could not load this proposal. | 이 의견을 불러오지 못했습니다. 또는: 이 제안을 불러오지 못했습니다. |
| 반영의 상태 | SCR-108 | Accepted, not yet reflected. In review: {pull request}. The change no longer fits the stage source; the agent asks you on its comment. Reflected by {pull request}. Reflected: already in the stage source at commit {commit}. The reflection was dismissed. | 받음, 아직 반영 전. 검토 중: {pull request}. 단계 원본이 바뀌어 이 변경이 더는 맞지 않습니다. 에이전트가 의견에서 묻습니다. {pull request}로 반영됨. 반영됨: 커밋 {commit}의 단계 원본에 이미 있음. 반영을 버렸습니다. |
| 버림, 철회됨 | SCR-108 | Dismissed on {date}; its comment stays open. Withdrawn by the agent on {date}. | {date}에 버림. 의견은 열린 채로 남습니다. {date}에 에이전트가 철회함. |
| 이미 버림 | SCR-108 | The reflection was already dismissed. | 이 반영은 이미 버려져 있었습니다. |
| 앞 그림 | SCR-108 | Made on the picture of commit {commit}; the stage source may have changed since. | 커밋 {commit}의 그림에서 낸 제안입니다. 그 뒤 단계 원본이 바뀌었을 수 있습니다. |
| 현황을 불러오는 중 | 코드가 돌기 전의 SCR-109 | Loading the stage overview. If it does not appear, load the page again. | 단계 현황을 불러오는 중입니다. 나타나지 않으면 페이지를 다시 불러와 주세요. |
| 남은 것 없음 | SCR-109 | Nothing is left in this stage. | 이 단계에 남은 것이 없습니다. |
| 읽지 않는 단계 | SCR-109 | This project does not read this stage: {why}. You can still pass its checkpoint. | 이 프로젝트는 이 단계를 읽지 않습니다: {why}. 그래도 확인 지점은 통과시킬 수 있습니다. |
| 기록을 기다림 | SCR-101, SCR-104, SCR-109 | Passed in NEXUS on {date}, waiting for its record | {date}에 NEXUS에서 통과, 기록을 기다림 |
| 다시 통과 | SCR-109 | Pass again | 다시 통과 |
| 기록된 철회 | SCR-101, SCR-104, SCR-109 | The record names a checkpoint that was withdrawn in NEXUS. The agent corrects the record. | 기록에 NEXUS에서 철회한 확인 지점이 적혀 있습니다. 에이전트가 기록을 고칩니다. |
| 이미 철회됨 | SCR-109 | This checkpoint was already withdrawn. | 이 확인 지점은 이미 철회되어 있었습니다. |
| 철회함 | SCR-109 | Withdrawn on {date} | {date}에 철회함 |
| 열지 못함 | SCR-109 | {n} discrepancies could not be opened, since the space holds 1,000 open ones. | 공간에 열린 어긋남이 1,000개라 {n}개를 열지 못했습니다. |

허브 페이지와 그 보기는 1차의 다른 메시지, 곧 "아직 프로젝트가 없습니다. corthex 스킬로 프로젝트를 등록한 뒤 허브를 다시 만들어 주세요."나 "“{q}”와 맞는 항목이 없습니다." 같은 것을 hub.html이 담은 영어와 한국어 그대로 둡니다.

### 목업이 더한 말

09단계의 목업([A 방향](../../09-mockup/nexus/README.ko.md#결정))에 필요했지만 08단계가 쓰지 않았던 말입니다. 2026-11-03에 목업과 함께 더했으며, 확인 지점에서 바뀔 수 있습니다. `·` 사이의 말은 저마다 따로 쓰는 이름표입니다.

| 말 | 나오는 곳 | 영어 | 한국어 |
| --- | --- | --- | --- |
| 열린 수 | SCR-101, 서버에서 | 1 open comment · {n} open comments · 1 open proposal · {n} open proposals · 1 open discrepancy · {n} open discrepancies | 열린 의견 {n} · 열린 제안 {n} · 열린 어긋남 {n} |
| 그림 표시 | SCR-101, 서버에서: 단계 표시의 설명 끝과, 그림이 있는 단계의 이름 | picture in NEXUS | NEXUS에 그림 |
| 기다리는 확인 지점 | SCR-101, 서버에서 | Waiting for their records ({n}) | 기록을 기다리는 확인 지점 ({n}) |
| NEXUS에서 | SCR-101#stale, 서버에서: 최신이 아닌 그림이 있거나 기록에 철회한 확인 지점이 적혀 있을 때 카드의 그 줄들의 제목 | In NEXUS | NEXUS에서 |
| 먼저 묻는 일 | SCR-101, 서버에서(SPEC-125) | Asks first ({source}) · {list} and {n} more in the settings · Not asked in this project: {list} · Anything that cannot be undone is asked in any case. · Only what cannot be undone is asked. | 먼저 묻는 일 ({source}) · {list} 외 {n}개는 설정에 있음 · 이 프로젝트에서 묻지 않는 일: {list} · 되돌릴 수 없는 일은 어쨌든 묻습니다. · 되돌릴 수 없는 일만 묻습니다. |
| 목록의 출처 | SCR-101, 먼저 묻는 일 안 | the project's list · the profile's list · the default list | 프로젝트의 목록 · 프로필의 목록 · 기본 목록 |
| 모든 프로젝트 | SCR-103, SCR-104: 프로젝트로 가는 링크 | All projects | 모든 프로젝트 |
| 확대 | SCR-105: 확대 단추의 이름 | Zoom out · Zoom in · Whole picture | 축소 · 확대 · 그림 전체 |
| 합친 표시 | SCR-105: 그림 전체에서 합친 컨텍스트 표시의 이름 | 1 mark in {context}: zoom in · {n} marks in {context}: zoom in | {context}의 표시 {n}개: 확대하기 |
| 표시의 설명 | SCR-105: 표시 설명의 이름 | Legend of the marks | 표시의 설명 |
| 항목 목록 | SCR-105 | With marks ({n}) · The rest ({n}) · Part without an ID | 표시가 있는 것 ({n}) · 나머지 ({n}) · ID 없는 부분 |
| 항목 패널 | SCR-106 | Proposals ({n}) · Comments ({n}) · Closed ({n}) · 1 reply · {n} replies | 제안 ({n}) · 의견 ({n}) · 닫힌 의견 ({n}) · 답글 {n}개 |
| 그림으로 돌아가기 | SCR-106, SCR-107, SCR-108, 그 항목·의견·제안이 없어졌을 때 | Back to the picture | 그림으로 돌아가기 |
| 답글 불러오기 | SCR-107#loading, 화면 낭독기용 | Loading the replies… | 답글을 불러오는 중… |
| 새 답글 | SCR-107#stale: 패널을 연 뒤에 온 답글 | New | 새 답글 |
| 제안 패널 | SCR-108 | Change · Reason · Stage source text · Made on commit {commit} · Answers | 변경 · 까닭 · 단계 원본의 글 · 커밋 {commit}에서 낸 제안 · 답하는 의견 |
| 원본 글 불러오기 | SCR-108#loading, 화면 낭독기용 | Loading the stage source text… | 단계 원본의 글을 불러오는 중… |
| 단계 현황의 제목 | SCR-109 | Recorded state · Updated {time} · Discrepancies ({n}) · Comments ({n}) · Pending reflections ({n}) · Words (optional) | 기록된 상태 · 갱신 {time} · 어긋남 ({n}) · 의견 ({n}) · 반영 대기 ({n}) · 남길 말 (선택) |

## 이 단계가 고른 것

앞 단계들이 이것들을 08단계에 맡겼습니다. 저마다 확인 지점에서 바뀔 수 있습니다.

1. 화면마다 파일 하나를 그 ID와 짧은 이름으로 이름 지어 NEXUS의 폴더에 두고, 모든 화면의 규칙과 메시지는 이 파일에 둡니다. 03단계의 흐름을 둔 방식과 같습니다. 이 단계의 기본은 `docs/08-screens/`에 화면마다 그 ID만으로 이름 지은 파일 하나입니다.
2. 단계의 여섯 상태 말고 화면 자신의 상태 셋: SPEC-119가 이름을 붙인 그림 보기의 `large`와 `code-failed`, 그리고 세 패널의 `gone`. `gone`은 주소나 패널이 가리키는 항목, 의견, 제안이 이제 없을 때이며, 단계의 기본값이면 오류라고 부를 것입니다.
3. 패널은 1,024픽셀 폭부터, 곧 ② 차례가 고치기를 하는 폭부터(SPEC-134) 그림 옆에 너비 400픽셀로 열리고, 그보다 좁으면 높이의 85퍼센트까지 아래에서 올라오는 시트로 열려, 휴대폰에서도 그림이 보이게 합니다.
4. 메시지는 `detail`을 절대 보이지 않으므로, 모든 오류는 그 메시지 아래 작은 글자로 추적 ID를 보여 사용자가 그것을 알리고 서버의 로그에서 그것을 찾을 수 있게 합니다.
5. 보기의 요청은 허브의 요청처럼(06단계의 [상한](../../06-api/nexus.ko.md#상한)) 30초를 가집니다. 그 뒤 보기는 서버가 제때 답하지 않았다고 알립니다.
6. 쓰기나 다시 읽기 뒤의 새 그림은 사용자 밑에서 다시 그리지 않고 보기와 함께 권하여, 사용자가 읽고 있는 항목이 움직이지 않게 합니다.
7. 허브 페이지가 그 프로젝트나 단계를 담지 않은 `#` 뒤의 주소는, 1차가 아무것도 보이지 않던 자리에 프로젝트 목록으로 가는 링크를 단 안내를 보입니다.
8. 자료를 읽지 못한 허브 페이지는 그렇다고 알립니다. 1차는 빈 페이지 "아직 프로젝트가 없습니다"를 보이는데, 그러면 있는 프로젝트를 등록하라고 사용자를 보내게 됩니다.
9. 항목의 쓴 쪽은 "나" 대신 서버가 두는 종류(REQ-163)인 "사용자"나 "에이전트"로 보입니다. Access가 들여보낸 누구나 같은 화면을 보기 때문입니다.
10. 메시지는 무슨 일이 있었는지와 사용자가 할 수 있는 것을 페이지의 언어로, 1차의 메시지 꼴로, 곧 영어 문장과 존댓말의 한국어로 말합니다. 허브만 보는 코드는 06단계의 초안을 그대로 둡니다.
11. 사람 화면: 한 페이지의 와이어프레임을, 저장소가 공개이므로 링크가 프로젝트의 기록에 있는 비공개 페이지로 게시하고, 정의는 표를 데이터베이스로 둔 Notion의 한국어 사본으로 읽습니다.
12. ID 없이 그린 표나 화면처럼 어느 항목도 담지 않는 부분은 그림 자체에 대한 항목 패널을 엽니다. 그 부분의 이름이 패널의 제목이 되고, 거기 남기는 의견의 인용이 됩니다(SPEC-126). 그 부분을 가리키는 ID가 없으므로 이 패널에는 자기 주소가 없습니다: 다시 불러오면 그림이 보이고, 그 부분의 표시가 패널을 다시 열며, 보내지 않은 글은 그 부분을 다시 고르면 돌아옵니다.

## 앞 단계의 변경

이 단계와 함께 확인 지점을 기다리며, 확인 지점을 통과하면 앞 단계의 파일을 바꿉니다. 다만 07단계의 실수 둘을 바로잡는 마지막 것은 이미 바꿨습니다.

1. 06단계: 세 페이지 API-101\~API-103은 브라우저의 요청처럼 요청이 받아들이면 거절이나 오류에 `text/html`로 답합니다. 서버의 언어로 된 메시지 하나의 작은 페이지에 추적 ID, 다시 불러오기, 허브 페이지 링크가 있고, 정책 `default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'` 아래, 같은 상태로 답합니다. 지금 계약은 그 페이지들에 `application/problem+json`만 주는데, 브라우저는 그것을 날 글로 보입니다. 다른 클라이언트는 Problem Details를 그대로 받고 `/api/` 요청은 바뀌지 않습니다. 페이지들은 계약에서 두 형식이 있는 자기 응답을 얻습니다.
2. 06단계의 [읽기](../../06-api/nexus.ko.md#읽기)는 공간이 없는 프로젝트의 그림 보기가 `picture_not_found`를 보인다고 말하지만, 계약은 그 페이지에 `404` `space_not_found`로 답합니다. 그 문장은 계약을 따르고, 이 단계는 그 코드의 메시지를 확인 지점의 통과(API-128)에도 맞게 씁니다.
3. 06단계의 07·08단계를 위한 메모는 화면마다의 요청을 늘어놓습니다. 단계 현황도 그 정책이 말하듯 API-104에서 그 코드를 불러오고, 제안의 패널은 그림이 더는 늘어놓지 않는 닫히거나 버려진 반영을, 그 PR을 보이려고 API-116으로 읽습니다.
4. 07단계의 08단계를 위한 메모는 폭에 허브 페이지의 언어인 REQ-099를 적었는데, 폭은 REQ-101과 REQ-146입니다. 또 07단계는 06단계의 예시를 설명하며 양식의 예시 화면 ID 둘을 적어, 허브가 그것을 언급했지만 정의하지 않은 것으로 알렸습니다. 이 변경은 두 곳을 바로잡으며, 규칙은 바꾸지 않습니다.

## 돌린 검사

2026-11-03에 정의서 아홉 개, 이 파일, 그 한국어 번역, 와이어프레임에서:

- 이 단계의 검사, 저장소 밖에 두는 스크립트로: 모든 자료가 그 요청이나 출처를 적음; 모든 동작에 결과와 실패가 있음; 화면이 부르는 요청마다 계약이 늘어놓는 모든 응답, 모두 97개가 어느 상태로 이어지고, 계약이 그 응답에 주는 모든 오류 코드가 그 상태에 적혀 있음; 화면마다 단계의 여섯 상태를 저마다 설명하거나 해당하지 않는 까닭을 적음; 정의서마다 경우의 수 12가지가 차례대로 있고 두 폭의 배치가 있음; 파일이 적는 `SCR-105#stale` 같은 모든 상태가 정의돼 있음; 이 파일이 늘어놓은 상태가 정의서와 같음; 한국어 번역이 영어 파일과 같은 상태, 응답, 코드, 적은 상태를 담음.
- 이 파일들의 모든 링크가 그 앵커까지 맞음. 와이어프레임 안의 화면마다의 자리도 포함.
- 와이어프레임에 상태 45개마다 320과 1440픽셀의 틀이 있고, 정의되지 않은 상태의 틀은 없음. Chromium에서 320, 390, 1,280, 1,440픽셀 폭, 밝은 모드와 어두운 모드, 두 언어로 페이지가 옆으로 밀리지 않고, 틀 밖으로 나간 요소가 없으며, 콘솔에 오류가 없음. 그림으로 본 것: 밝은 모드와 한국어로 두 폭의 `SCR-101#normal`, `SCR-106#error`, `SCR-109#stale`, 그리고 어두운 모드와 한국어로 320픽셀의 `SCR-107#normal`. 나머지 틀은 재기만 하고 보지는 않았음.
- 이 저장소의 허브 스냅샷이 정의서 아홉 개를 SCR-101\~SCR-109의 화면 정의로, 그 상태 45개와 함께 읽고, 점검 결과를 더하지 않음. 변경 4의 수정으로 07단계의 글이 `main`에서 낸 경고 둘도 사라짐.
- 이 파일들을 넣은 저장소의 검사가 통과함: `python -m unittest discover -s tests`, 마켓플레이스와 그 세 플러그인의 `claude plugin validate --strict`, `node --test nexus/test/*.test.js`, `git diff --check`.

## 확인할 것

사용자 흐름, 기능 명세, 서버의 자료, 인터페이스, 사이트맵의 확인 지점과 함께 기다립니다. 특히 볼 만한 것:

1. HTML로 된 페이지의 거절(변경 1). 계약의 세 페이지를 바꿉니다.
2. 그림 보기의 상태, 특히 `large`, `code-failed`, 그리고 그리지 않고 권하는 새 판(고른 것 2와 6), 그림 옆이나 아래의 패널(고른 것 3), 그리고 ID 없는 부분의 패널(고른 것 12).
3. 영어와 한국어로 된 메시지의 최종 문구.
4. 휴대폰처럼 320픽셀에서 본 와이어프레임.

## 다음 단계를 위한 메모

### 09단계: 목업

- 새 화면 SCR-105\~SCR-109마다 후보 둘, 휴대폰을 먼저, 320픽셀에서, 이 틀에서 시작합니다. 상태마다 디자인할 틀입니다. 허브 페이지는 1차의 디자인을 그대로 두고 SCR-101과 SCR-104에 0.2가 더하는 것을 더합니다.
- 그림의 항목 위의 표시와 "받음, 아직 반영 전"은 꽉 찬 DDD 보드 위에서도 두 테마에서도 읽히는 꼴과, 손가락으로 고를 수 있는 크기가 필요합니다.

### 10단계: 작업 분해

- 변경 1의 메시지 페이지는 서버의 페이지와 함께, 보기의 상태는 보기와 함께, 허브 페이지의 0.2 상태는 [hub.html](../../../plugins/corthex-nexus/skills/corthex-hub/assets/hub.html)에서 하며, 그 파일을 [nexus/src/hub.html](../../../nexus/src/hub.html)이 복사합니다.

### 11단계: 개발

- 서버가 준비되기 전에, 계약이 늘어놓는 어느 응답이든 요청하면 돌려주는 Prism의 목에 맞춰 상태마다 만듭니다.
- 보기의 요청: `redirect: "manual"`, 30초 뒤의 중단, 브라우저 저장소에 글과 함께 두는 쓰기 ID, 그리고 끝난 로그인으로 읽는 `opaqueredirect` 응답.
- 보기마다 HTML에 둔 고정 문구는 핵심 파일이 돌면 숨기고, 편집기는 따로 불러와 그 실패가 항목 목록을 남기게 합니다.
- 테스트는 패널마다 그 주소에서 열고, 상태마다 그 응답에서 이끌어 내며, 다시 불러온 뒤 보내지 않은 글을 되돌립니다.

### 12단계: QA

- `SCR-105#large` 같은 상태마다 테스트 케이스 하나를 320과 1440픽셀에서 두고, 그 단계의 브라우저 에이전트가 먼저 목의 응답으로, 그다음 Access 뒤의 개발 서버에서 걸어 봅니다.
- 손으로: 열린 보기에서 끝나는 로그인, 잃어버린 답, 의견을 닫는 두 번째 탭, 30초 넘게 기다리는 요청.
