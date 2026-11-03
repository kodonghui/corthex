# NEXUS: 요청, 명령, 형식

[English](nexus.md)

CORTHEX 자신의 프로젝트에서 NEXUS 0.2의 06단계입니다: OpenAPI 계약 [nexus.openapi.yaml](nexus.openapi.yaml)에 있는 NEXUS 서버의 요청, 그리고 이 파일에 있는 그 계약이 따르는 규칙, 허브의 명령, 그것과 함께 가는 파일의 형식입니다. 상태: 2026-11-02에 관리자가 그날 고른 대로 기억 플러그인을 만드는 동안, 사용자 흐름, 기능 명세, 서버의 자료의 추천을 따라 초안을 썼습니다. 관리자가 2026-11-03에 03\~05단계, 07·08단계와 함께 이 파일의 확인 지점을 통과시켜, 10단계가 작업을 나누기 전에 NEXUS 0.2의 요청, 명령, 형식이 고정되었습니다. 이제 호환되지 않는 변경을 하려면 관리자의 결정이 필요합니다. 계약은 그 안에 있는 모든 요청, 응답, 예시, 오류 코드의 원본이고, 이 파일은 그것을 설명하며 나머지의 원본입니다. 이 번역과 영어 원문이 다르면 영어 원문이 원본입니다.

입력: [docs/04-functional-spec/nexus.ko.md](../04-functional-spec/nexus.ko.md)의 기능 명세(SPEC-101\~SPEC-140), 특히 그 [06단계를 위한 메모](../04-functional-spec/nexus.ko.md#06단계-요청-명령-형식); [docs/05-erd/nexus.ko.md](../05-erd/nexus.ko.md)와 [nexus.sql](../05-erd/nexus.sql)의 서버의 자료와 파일(TBL-101\~TBL-118), 그 [06단계를 위한 메모](../05-erd/nexus.ko.md#06단계-요청-명령-형식)와 상한; [docs/02-prd/nexus.ko.md](../02-prd/nexus.ko.md)의 요구사항; [docs/01-domain/nexus.ko.md](../01-domain/nexus.ko.md)의 용어집과 DDD 보드(이 파일은 그 말을 그 뜻으로 씁니다); 그리고 지금 도는 1차, 곧 [app.js](../../nexus/src/app.js), [snapshot.js](../../nexus/src/snapshot.js), [store.js](../../nexus/src/store.js)의 서버와, [snapshot.md](../../plugins/corthex-nexus/skills/corthex-hub/references/snapshot.md), [reading.md](../../plugins/corthex-nexus/skills/corthex-hub/references/reading.md)가 설명하는 [hub.py](../../plugins/corthex-nexus/skills/corthex-hub/scripts/hub.py)의 허브입니다. 사이트맵(07단계)은 나중이라 아직 입력에 화면 ID가 없고, 요청은 사용자 흐름과 기능 명세가 적은 화면을 맡습니다.

이 단계의 기본 계약은 Swagger UI로 읽는 `api/openapi.yaml`입니다. NEXUS 서버에는 HTTP API가 있으므로 계약은 단계가 말하는 대로 OpenAPI 3.1이고, 다른 부분의 인터페이스 옆에 `docs/06-api/nexus.openapi.yaml`로 둡니다. 사람은 프로젝트의 Notion 기록에 있는 한국어 사본으로 읽고, 파일 자체는 Swagger UI 같은 OpenAPI 보기 도구로 읽습니다. `.corthex/project.json`이 이 선택을 적어 둡니다. 허브의 명령은 HTTP 요청이 아니므로 이 파일이 MEMORY의 [인터페이스](memory.ko.md)와 같은 꼴로 정합니다: 명령마다 API ID, 맡는 동작, 결과가 있습니다.

## 이 파일을 읽는 법

- 서버의 요청은 계약의 작업 API-101\~API-132입니다. 작업마다 `operationId`, 맡는 동작(SPEC), 보낼 수 있는 쪽, 줄 수 있는 모든 응답과 그 이름 붙은 예시, 그리고 `x-corthex.omit` 아래에 줄 수 없는 응답과 그 까닭이 있습니다. [인터페이스](#인터페이스)가 목록을 보이고, 계약이 정합니다.
- 허브의 명령 API-133\~API-150은 [허브의 명령](#허브의-명령)이 옵션, 결과, 종료 코드와 함께 정합니다.
- 응답은 그 요청의 ID와 상태로 `API-105#409`처럼 적고, 명령의 결과는 그 ID와 결과로 `API-136#refused`처럼 적습니다.
- 오류 코드는 `commit_not_replaced`처럼 적습니다. [오류 코드](#오류-코드)는 계약의 `components.x-corthex.errors`대로 코드마다 상태, 뜻, 더하는 멤버, 사용자가 보는 말, 클라이언트가 하는 일을 적습니다.
- 서버의 시각은 `2026-11-03T09:00:00.000Z`처럼 밀리초까지 UTC이고, 기기나 Git의 시각은 그 시간대를 지닙니다. 바이트 크기는 UTF-8로 세고, 글자 수는 05단계처럼 코드 포인트로 셉니다.
- 상태: 지금 도는 1차가 주는 것은 `built`, NEXUS 0.2가 더하거나 바꾸는 것은 `active`입니다. PC에서의 편집(SPEC-134)은 ② 차례이고, 그 요청은 그때 더합니다.
- `~/.corthex/`는 사용자 홈 폴더의 CORTHEX 폴더이고, Windows에서는 `%USERPROFILE%\.corthex\`입니다. 허브의 파일은 1차처럼 `~/.corthex/hub/` 아래에 있습니다.

## 출처

2026-11-02에 읽은 문서:

- Cloudflare Access와 Workers. [Cloudflare Access](https://developers.cloudflare.com/workers/configuration/cloudflare-access/): Worker는 Access가 인증한 요청에서만 애플리케이션의 `aud`와 `getIdentity()`가 있는 `ctx.access`를 받고, 정적 자산을 내줄 때는 받지 못합니다. [애플리케이션 토큰](https://developers.cloudflare.com/cloudflare-one/identity/authorization-cookie/application-token/): 사람의 토큰에는 `sub`와 `email`이 있고, 서비스 토큰의 토큰에는 `common_name`에 그 토큰의 클라이언트 ID가, `sub`에는 빈 값이 있습니다. [JWT 검증](https://developers.cloudflare.com/cloudflare-one/identity/authorization-cookie/validating-json/): 토큰은 `Cf-Access-Jwt-Assertion` 헤더로 오고, 팀의 키는 `https://<team>.cloudflareaccess.com/cdn-cgi/access/certs`에 있습니다. [서비스 토큰](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/): 클라이언트는 `CF-Access-Client-Id`와 `CF-Access-Client-Secret` 헤더를 보냅니다.
- 무료 요금제의 한도: [Workers](https://developers.cloudflare.com/workers/platform/limits/)는 요청마다 CPU 시간 10 ms와 하위 요청 50개, 하루 요청 100,000개; [D1](https://developers.cloudflare.com/d1/platform/limits/)은 호출마다 쿼리 50개, 데이터베이스마다 500 MB입니다.
- [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457.html), HTTP API의 문제 세부 정보(Problem Details): `type`이 없으면 `about:blank`라는 뜻이고, 미디어 형식은 `application/problem+json`이며, 문제는 자기 멤버를 더할 수 있고 그것을 모르는 클라이언트는 무시하며, `status`는 응답 자신의 상태입니다.
- [Idempotency-Key HTTP 헤더 필드](https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/), 2026-10-22의 08판, RFC가 아닌 인터넷 초안: 키는 구조화 필드 값(Structured Field Values)의 String이라 큰따옴표 안에 씁니다. 다른 요청과 함께 다시 보낸 키는 `422`를, 첫 요청을 아직 처리하는 중인 키는 `409`를 받는 것이 좋다고 합니다. NEXUS가 어디서 다른지는 [쓰기 ID](#쓰기-id)가 말합니다.

아직 보지 못한 것: 실제 Access 설정에서의 두 가지 로그인, 그리고 문서가 말하지 않는 서비스 토큰에 대한 `getIdentity()`의 결과. [로그인](#로그인)이 이것을 열린 질문으로 둡니다.

## 인터페이스

기능 명세의 모든 동작에 인터페이스가 있습니다. ② 차례가 더하는 PC에서의 편집(SPEC-134)만 예외입니다.

### 서버의 요청 목록

계약이 정하고, 이 표는 목록을 보입니다. 보낼 수 있는 쪽: `사용자`는 사람 자신의 로그인, `에이전트`는 서비스 토큰, `둘 다`는 둘 모두입니다([로그인](#로그인)).

| API | 요청 | 코드 이름 | 보낼 수 있는 쪽 | 맡는 동작 | 상태 |
| --- | --- | --- | --- | --- | --- |
| API-101 | `GET /` | `getHubPage` | 둘 다 | SPEC-113, SPEC-122, SPEC-123, SPEC-124, SPEC-125 | active |
| API-102 | `GET /pictures/{project}/{part}/{stage}` | `getPictureViewPage` | 둘 다 | SPEC-113, SPEC-119 | active |
| API-103 | `GET /overview/{project}/{part}/{stage}` | `getStageOverviewPage` | 둘 다 | SPEC-113, SPEC-138, SPEC-139 | active |
| API-104 | `GET /code/{file}` | `getViewCode` | 둘 다 | SPEC-113, SPEC-119 | active |
| API-105 | `POST /api/snapshots` | `pushSnapshot` | 둘 다 | SPEC-111, SPEC-112, SPEC-113, SPEC-114, SPEC-117, SPEC-118, SPEC-120, SPEC-121, SPEC-140 | active |
| API-106 | `GET /api/snapshots` | `listSnapshots` | 둘 다 | SPEC-113, SPEC-122 | built |
| API-107 | `GET /api/snapshots/{project}` | `getSnapshot` | 둘 다 | SPEC-113, SPEC-122 | built |
| API-108 | `DELETE /api/snapshots/{project}` | `removeProject` | 둘 다 | SPEC-113, SPEC-115 | active |
| API-109 | `GET /api/snapshots/{project}/held` | `getHeldCommit` | 둘 다 | SPEC-111, SPEC-112, SPEC-113 | active |
| API-110 | `GET /api/snapshots/{project}/removal` | `getRemovalDryRun` | 둘 다 | SPEC-113, SPEC-115 | active |
| API-111 | `GET /api/spaces/{project}/pictures/{part}/{stage}` | `getPicture` | 둘 다 | SPEC-113, SPEC-118, SPEC-119 | active |
| API-112 | `GET /api/spaces/{project}/overview/{part}/{stage}` | `getStageOverview` | 둘 다 | SPEC-113, SPEC-138 | active |
| API-113 | `GET /api/spaces/{project}/todo` | `getAgentTodo` | 둘 다 | SPEC-113, SPEC-135, SPEC-136 | active |
| API-114 | `GET /api/spaces/{project}/comments/{comment}` | `getComment` | 둘 다 | SPEC-113, SPEC-127, SPEC-132, SPEC-135 | active |
| API-115 | `GET /api/spaces/{project}/proposals/{proposal}` | `getProposal` | 둘 다 | SPEC-113, SPEC-130, SPEC-131 | active |
| API-116 | `GET /api/spaces/{project}/edits/{edit}` | `getEdit` | 둘 다 | SPEC-113, SPEC-133 | active |
| API-117 | `GET /api/spaces/{project}/checkpoints/{checkpoint}` | `getCheckpoint` | 둘 다 | SPEC-113, SPEC-140 | active |
| API-118 | `POST /api/spaces/{project}/comments` | `leaveComment` | 둘 다 | SPEC-113, SPEC-116, SPEC-126, SPEC-128 | active |
| API-119 | `POST /api/spaces/{project}/comments/{comment}/replies` | `replyToComment` | 둘 다 | SPEC-113, SPEC-116, SPEC-127, SPEC-128, SPEC-132 | active |
| API-120 | `POST /api/spaces/{project}/comments/{comment}/answered` | `markAnswered` | 둘 다 | SPEC-113, SPEC-116, SPEC-127 | active |
| API-121 | `POST /api/spaces/{project}/comments/{comment}/decisions` | `recordDecision` | 에이전트 | SPEC-113, SPEC-116, SPEC-128, SPEC-132 | active |
| API-122 | `POST /api/spaces/{project}/proposals` | `makeProposal` | 에이전트 | SPEC-113, SPEC-116, SPEC-128, SPEC-130 | active |
| API-123 | `POST /api/spaces/{project}/proposals/{proposal}/withdraw` | `withdrawProposal` | 에이전트 | SPEC-113, SPEC-116, SPEC-130 | active |
| API-124 | `POST /api/spaces/{project}/proposals/{proposal}/accept` | `acceptProposal` | 사용자 | SPEC-113, SPEC-116, SPEC-131 | active |
| API-125 | `POST /api/spaces/{project}/proposals/{proposal}/dismiss` | `dismissProposal` | 사용자 | SPEC-113, SPEC-116, SPEC-131 | active |
| API-126 | `POST /api/spaces/{project}/edits/{edit}/report` | `reportEdit` | 에이전트 | SPEC-113, SPEC-116, SPEC-128, SPEC-133, SPEC-136 | active |
| API-127 | `POST /api/spaces/{project}/edits/{edit}/dismiss` | `dismissEdit` | 사용자 | SPEC-113, SPEC-116, SPEC-133 | active |
| API-128 | `POST /api/spaces/{project}/checkpoints` | `passCheckpoint` | 사용자 | SPEC-113, SPEC-116, SPEC-139 | active |
| API-129 | `POST /api/spaces/{project}/checkpoints/{checkpoint}/withdraw` | `withdrawCheckpoint` | 사용자 | SPEC-113, SPEC-116, SPEC-139 | active |
| API-130 | `POST /api/spaces/{project}/checkpoints/{checkpoint}/report` | `reportCheckpoint` | 에이전트 | SPEC-113, SPEC-116, SPEC-128, SPEC-136, SPEC-140 | active |
| API-131 | `POST /api/spaces/{project}/claims/{entry}` | `claimEntry` | 에이전트 | SPEC-113, SPEC-116, SPEC-136 | active |
| API-132 | `DELETE /api/spaces/{project}/claims/{entry}` | `releaseEntry` | 에이전트 | SPEC-113, SPEC-116, SPEC-136 | active |

### 허브의 명령 목록

| ID | 이름 | 보내는 요청 | 맡는 동작 | 상태 |
| --- | --- | --- | --- | --- |
| API-133 | `snapshot` | 없음 | SPEC-101, SPEC-102, SPEC-103, SPEC-104, SPEC-105, SPEC-106, SPEC-107, SPEC-108, SPEC-109, SPEC-110 | active |
| API-134 | `status` | 없음 | SPEC-109, SPEC-137, SPEC-140 | active |
| API-135 | `build` | 없음 | SPEC-122, SPEC-123, SPEC-125 | active |
| API-136 | `push` | API-109, API-105 | SPEC-111, SPEC-112, SPEC-129 | active |
| API-137 | `remove` | API-110, API-108 | SPEC-115 | active |
| API-138 | `todo` | API-113 | SPEC-135, SPEC-129 | active |
| API-139 | `comment` | API-118 | SPEC-128, SPEC-129, SPEC-135 | active |
| API-140 | `reply` | API-119 | SPEC-127, SPEC-128, SPEC-129, SPEC-132 | active |
| API-141 | `answered` | API-120 | SPEC-127, SPEC-128, SPEC-129 | active |
| API-142 | `decide` | API-121 | SPEC-132, SPEC-128, SPEC-129 | active |
| API-143 | `propose` | API-122 | SPEC-130, SPEC-128, SPEC-129 | active |
| API-144 | `withdraw` | API-123 | SPEC-130, SPEC-128, SPEC-129 | active |
| API-145 | `reflect` | API-126 | SPEC-133, SPEC-128, SPEC-129 | active |
| API-146 | `record` | API-130 | SPEC-140, SPEC-128, SPEC-129 | active |
| API-147 | `show` | API-114, API-115, API-116, API-117 | SPEC-132, SPEC-133, SPEC-140 | active |
| API-148 | `claim` | API-131 | SPEC-136 | active |
| API-149 | `release` | API-132 | SPEC-136 | active |
| API-150 | `outbox` | 담긴 쓰기의 요청 | SPEC-129 | active |

## 공통 규칙

### 주소와 경로

- 서버는 1차처럼 사용자가 정한 주소, 곧 `nexus.url`이 적은 주소에서만 답하고, `workers.dev`나 미리 보기 주소에서는 답하지 않습니다(SPEC-113). 페이지는 `/`, `/pictures/…`, `/overview/…`이고, 보기 화면의 코드는 `/code/` 아래, 나머지는 `/api/` 아래에 있습니다.
- `{project}`는 등록한 이름입니다: 소문자와 숫자로 된 낱말을 하이픈으로 이은 것으로, 100자까지입니다. `{part}`는 같은 꼴의 부분 이름이거나, 프로젝트 전체를 뜻하는 `_`이며, JSON 본문에서는 `""`로 씁니다. `{stage}`는 단계 키이고, 그림이 있는 단계는 `01-domain`, `05-erd`, `07-sitemap`뿐입니다.
- 서버 자신의 ID는 접두어와 소문자 Crockford base32의 임의 글자 12개입니다. 숫자와 `i`, `l`, `o`, `u`를 뺀 글자를 씁니다: 의견은 `nc_`, 어긋남은 `nd_`, 제안은 `np_`, 편집은 `ne_`, 확인 지점은 `nk_`, 쓰기는 `nw_`입니다. 쓰기 ID는 페이지와 허브가 만들고, 나머지는 서버가 만듭니다. 이것은 추적 ID가 아니며, 허브는 이것을 항목으로 읽지 않습니다.
- 꼴이 다른 경로 값은 서버가 갖지 않은 값과 같은 `404`를 받습니다. 1차가 프로젝트 이름에 그렇게 답하는 것과 같으며, `400`은 받지 않습니다([고른 것 1](#이-단계가-고른-것)).

### 메서드와 본문

- `GET`은 읽고, 모든 `GET`은 같은 상태와 헤더로 본문 없이 `HEAD`에도 답합니다. `POST`는 쓰고, `DELETE`는 프로젝트를 지우거나 맡음을 끝냅니다. 경로가 받지 않는 메서드는 받는 메서드를 적은 `Allow` 헤더와 함께 `405`를 받고, 모르는 경로는 `404` `not_found`를 받습니다.
- 본문은 `Content-Type: application/json`으로 보낸 UTF-8의 JSON입니다(아니면 `415` `json_required`, UTF-8이 아니면 `400`). 스냅샷은 1 MiB까지, 다른 본문은 256 KiB까지입니다(`413`). 본문을 받지 않는 요청은 보낸 본문을 읽지 않습니다.
- 쓰기의 본문에는 계약이 적은 필드만 있고, 다른 이름의 필드는 `400`으로 거절합니다. 스냅샷은 1차처럼 서버가 모르는 필드도 간직합니다.
- 쓰기에 꼭 있어야 하는 글, 이를테면 답글의 글이 비었거나 공백뿐이면 `400`으로, 상한보다 길면 `413` `text_too_long`으로 거절합니다. 글은 클라이언트가 보낸 그대로 저장하고, 에이전트의 글은 허브가 보내기 전에 가립니다(SPEC-128).

### 응답

- 응답은 `application/json; charset=utf-8`의 JSON이고, 상태는 `200`, 항목을 더하는 쓰기는 `201`입니다. 페이지는 `text/html; charset=utf-8`이고, 보기 화면의 코드 파일은 제 형식을 지닙니다.
- 모든 응답은 1차의 헤더를 지닙니다: `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-Robots-Tag: noindex, nofollow`, `Cross-Origin-Resource-Policy: same-origin`. 그래서 어떤 응답도 캐시되거나, 다른 사이트의 프레임에 보이거나, 색인되지 않습니다(SPEC-113). JSON 응답에는 `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`을 더합니다.
- 허브 페이지는 1차의 정책을 그대로 둡니다. 자기 인라인 스크립트만 그 다이제스트로 돌리고, 아무 요청도 보내지 않습니다: `default-src 'none'; script-src 'sha256-…'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`, 그리고 `Cross-Origin-Opener-Policy: same-origin`.
- 그림 보기와 단계 현황은 코드를 `/code/`에서만 불러오고 요청은 서버에만 보냅니다(REQ-147): `default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`, 그리고 `Cross-Origin-Opener-Policy: same-origin`. 그 자료는 JSON 스크립트 블록에 있고, 페이지는 그것을 글로 읽을 뿐 돌리지 않습니다.
- 브라우저가 간직해도 되는 것은 보기 화면의 코드 파일뿐이며, `Cache-Control: private, max-age=31536000, immutable`을 지닙니다. 파일 이름마다 그 내용의 다이제스트가 들어 있고, 프로젝트 자료는 없기 때문입니다. 이 단계의 확인 지점이 SPEC-113을 그렇게 바꿨습니다([앞 단계의 변경](#앞-단계의-변경)).

### 오류

모든 거절과 오류는 아래 페이지가 브라우저에 하는 답을 빼면 `application/problem+json`으로 보내는 문제 세부 정보(RFC 9457)이며, 다음 멤버가 있습니다(계약의 `Problem`):

| 멤버 | 값 |
| --- | --- |
| `title` | 코드의 짧은 영어 제목. 그 코드의 모든 응답에서 같습니다 |
| `status` | 응답의 상태 |
| `detail` | 이 요청에서 무엇이 잘못됐는지 말하는 한 줄. 필드나 커밋 같은 요청의 값은 적을 수 있지만, 저장된 글은 적지 않습니다 |
| `code` | [오류 코드](#오류-코드) 가운데 하나 |
| `traceId` | Cloudflare가 `Cf-Ray` 헤더로 보내는 요청의 Ray ID(이를테면 `8f6c3b2a1d0e9f80-ICN`). 기기에서처럼 그것이 없으면 임의의 16진수 16자리. 오류에 대한 서버의 로그 줄에도 같은 ID가 있습니다 |
| `error` | `detail`과 같은 값. 거절의 `error`를 보여 주고 응답을 4,096바이트까지만 읽는 0.1의 허브를 위한 것입니다 |
| 그 밖 | [오류 코드](#오류-코드)가 적는, 그 코드가 더하는 멤버. 이를테면 `field`와 `limit` |

NEXUS는 `type`을 보내지 않으며(RFC 9457은 이것을 `about:blank`로 읽습니다), `instance`도 보내지 않습니다. 클라이언트는 RFC 9457이 말하는 대로 모르는 멤버를 무시합니다. 보기 화면은 `detail`이 아니라 사용자의 언어로 된 코드의 말을 보여 주고, 허브는 `detail`을 보여 줍니다. 서버의 로그에는 오류의 종류와 추적 ID만 있고, 저장된 글이나 요청의 값은 없습니다(SPEC-113).

세 페이지 API-101\~API-103은 요청의 `Accept` 헤더가 `text/html`을 적으면, 곧 브라우저가 페이지를 열 때처럼 하면 거절과 오류에 `text/html; charset=utf-8`로 답하고, 그렇지 않으면 문제 세부 정보로 답합니다. 브라우저는 문제 세부 정보를 날 글로 보이기 때문입니다. 그 페이지에는 서버의 언어로 된 코드의 말 하나와 추적 ID, 다시 불러오기, 허브 페이지 링크가 있고, 응답의 상태와 정책 `default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`을 지니며, 08단계의 [규칙 9](../08-screens/nexus/README.ko.md#모든-화면)가 그것을 그립니다. `/api/` 요청과 보기 화면의 코드는 언제나 문제 세부 정보로 답하고, 보기 자신의 자료는 그것을 `problem`에 담습니다.

### 어느 거절이 먼저인지

규칙을 여러 개 어긴 요청은 다음 순서에서 먼저 오는 거절을 받습니다. 1차는 자기 검사에서 이 순서를 지킵니다:

1. Access: 검사하지 않았으면 `403` `access_missing`, 다른 Access 애플리케이션이 검사했으면 `403` `access_other_app`.
2. 경로와 메서드: `404` `not_found`, `405` `method_not_allowed`. 꼴이 다른 경로 값은 그것이 가리키는 것의 `404`.
3. 브라우저가 다른 사이트에서 보낸 변경: `403` `cross_site`.
4. 쓰기에 필요한 로그인의 종류: `403` `user_only`, `agent_only`, `no_kind`.
5. 헤더, 곧 쓰기 ID와 세션 이름표: `400` `invalid_request`.
6. 본문의 형식 `415` `json_required`, 본문의 크기 `413` `snapshot_too_large`나 `body_too_large`.
7. 본문: UTF-8이나 JSON이 아니거나 꼴이 맞지 않으면 `400` `invalid_request`나 `invalid_snapshot`, 앞선 시각의 스냅샷은 `400` `clock_ahead`, 상한을 넘은 글은 `413` `text_too_long`.
8. 쓰기 ID: 서버가 이미 받은 쓰기는 첫 응답을 받고, 다른 요청이 가진 ID는 `409` `write_id_reused`.
9. 요청이 가리키는 것: 프로젝트, 공간, 부분, 그림, 항목은 `404`, 그림에 없는 항목은 `400` `unknown_item`.
10. 맡음, 상태, 상한: `409`.

## 로그인

1차처럼 Cloudflare Access가 Worker보다 먼저 모든 요청을 검사합니다. 올바른 로그인이 없는 요청은 Worker에 닿지 않습니다. Access가 브라우저는 자기 로그인 페이지로 보내고, 거절한 서비스 토큰에는 리디렉션, `401`, `403`으로 답합니다. 그래서 어느 요청도 `401`을 적지 않고, 계약은 그 까닭을 `x-corthex.omit`마다 적습니다.

그다음 Worker는 1차처럼 Access가 그 요청을(`ctx.access`, 없으면 `403` `access_missing`) 자기 애플리케이션으로(`ACCESS_AUD`가 적은 `aud`, 아니면 `403` `access_other_app`) 검사했는지 보고, Access가 검사한 신원에서 로그인의 종류를 정합니다(SPEC-116):

| 신원 | 종류 |
| --- | --- |
| 비어 있지 않은 `sub`: Access의 로그인으로 들어온 사람 | `user` |
| 빈 `sub`와 `common_name`: 서비스 토큰의 클라이언트 ID | `agent` |
| 그 밖 | 어느 쪽도 아님: 모든 쓰기에서 `403` `no_kind` |

- 읽기, 보내기, 지우기는 1차처럼 Access가 들여보낸 어느 신원이든 받으며, `no_kind`로 답하지 않습니다. 한 종류만 보낼 수 있는 쓰기는 다른 종류에 `user_only`나 `agent_only`로 답하고, 그 `needs`가 받는 종류를 적습니다.
- 신원은 아무것도 간직하거나 로그에 남기지 않습니다. 항목은 쓴 쪽의 종류, 곧 `user`나 `agent`만 간직합니다(REQ-163).
- 보기 화면을 연 동안 로그인이 끝날 수 있습니다. 보기 화면은 요청을 `redirect: "manual"`로 보내므로, Access의 로그인 페이지로 가는 리디렉션이 `opaqueredirect` 응답으로 닿습니다. 그러면 보기 화면은 로그인이 끝났다고 말하고, 글을 간직한 채 페이지를 다시 불러오자고 합니다(SPEC-126).
- 열린 질문: Worker가 신원을 읽는 방법. `ctx.access`에서 `getIdentity()`나 토큰의 클레임으로 읽고, 그것이 두 종류 모두에 `sub`와 `common_name`을 주지 않으면 대신 `Cf-Access-Jwt-Assertion` 헤더를 읽어 토큰을 스스로 검사합니다: `https://<ACCESS_TEAM_DOMAIN>/cdn-cgi/access/certs`에서 가져와 한 시간까지 간직하는 팀의 키 가운데 하나로 서명됐는지, `ACCESS_AUD`가 적은 `aud`인지, 끝나지 않았는지. 11단계가 만들기 전에 실제 Access 설정에서 두 종류를 시험해 어느 쪽인지 정하며, 계약의 보안 방식도 같은 말을 합니다. 어느 쪽도 되지 않으면 선택은 관리자에게 돌아갑니다.

## 쓰기

사용자의 쓰기는 보기 화면에서, 에이전트의 쓰기는 허브를 거쳐 옵니다(SPEC-128). 쓰기마다 D1의 배치 하나이므로, 동시에 온 두 쓰기는 하나씩 차례로 받습니다(05단계의 [사용자와 에이전트의 쓰기](../05-erd/nexus.ko.md#사용자와-에이전트의-쓰기)).

### 쓰기 ID

- 맡음을 뺀 모든 쓰기는 `Idempotency-Key` 헤더에 쓰기 ID를 담습니다. 쓰기 ID는 페이지나 허브가 그 쓰기 하나를 위해 만들어 시도마다 보내는 `nw_` ID이고, 초안이 쓰는 대로 큰따옴표 안에 씁니다: `Idempotency-Key: "nw_6t9w2z5c8f1j"`. 그것이 없거나 꼴이 다르면 쓰기는 `400` `invalid_request`로 거절되고, 그 `field`는 `Idempotency-Key`입니다.
- 서버는 받은 쓰기마다 그 ID를 요청의 이름, 첫 응답과 함께 7일 동안 간직합니다(TBL-112). 그 ID로 다시 보낸 쓰기는 같은 상태로 그 응답을 받고, 아무것도 바꾸지 않습니다. 서버가 거절한 쓰기는 ID를 남기지 않으므로, 다시 보내면 다시 검사합니다.
- 서버가 다른 요청의 것으로 가진 ID는 `409` `write_id_reused`로 거절합니다. NEXUS는 TBL-112가 간직하는 요청의 이름을 견주고, 본문은 견주지 않습니다.
- NEXUS가 초안과 다른 점: 다른 요청의 ID에 `422`가 아니라 `409`로 답합니다. 다른 요청으로 돌아온 쓰기 ID는 클라이언트의 잘못이고, `409`는 쓰기의 다른 충돌에도 그렇게 말하기 때문입니다. 아직 처리하는 중인 쓰기를 따로 두지 않습니다. 쓰기마다 트랜잭션 하나이므로, 두 번째 시도는 첫 시도를 기다려 그 응답을 받기 때문입니다. 그리고 7일 뒤에는 ID를 잊습니다. 그때는 허브의 보낼 편지함도 그 쓰기를 버렸기 때문입니다.
- 보내기에는 쓰기 ID가 필요 없습니다. 커밋 규칙이 새 스냅샷과 다시 보낸 스냅샷을 가르기 때문입니다([보내기](#보내기)). 지우기도 필요 없습니다. 두 번째 지우기는 `404`를 받기 때문입니다. 맡음도 필요 없습니다. 두 번 맡아도 맡음은 하나이기 때문입니다.

### 요청 이름

TBL-112가 쓰기마다 간직하고, 보낼 편지함이 에이전트의 쓰기마다 간직하는 이름입니다:

| 이름 | 요청 | 보낼 수 있는 쪽 |
| --- | --- | --- |
| `comment` | API-118 | 둘 다 |
| `reply` | API-119 | 둘 다 |
| `answered` | API-120 | 둘 다 |
| `decision` | API-121 | 에이전트 |
| `proposal` | API-122 | 에이전트 |
| `withdraw-proposal` | API-123 | 에이전트 |
| `accept` | API-124 | 사용자 |
| `dismiss-proposal` | API-125 | 사용자 |
| `report-edit` | API-126 | 에이전트 |
| `dismiss-edit` | API-127 | 사용자 |
| `checkpoint` | API-128 | 사용자 |
| `withdraw-checkpoint` | API-129 | 사용자 |
| `report-checkpoint` | API-130 | 에이전트 |

### 세션

- 에이전트는 `Nexus-Session` 헤더에 세션 이름표를 담아 자기 세션을 밝힙니다. 이름표는 ASCII 글자, 숫자, `.`, `_`, `:`, `-`로 된 1\~100자이고, 세션 동안 그대로 둡니다. 도구의 세션 ID를 쓰거나, 그것이 없으면 세션을 시작할 때 `claude-code-4f2a91`처럼 만든 이름표를 씁니다. 이름표에는 개인적인 것이 없습니다(SPEC-128). 허브는 이것을 `--session`이나 환경 변수 `CORTHEX_NEXUS_SESSION`에서 가져옵니다.
- 에이전트의 모든 쓰기에 이름표가 있어야 하며, 없으면 `400` `invalid_request`로 거절하고 그 `field`는 `Nexus-Session`입니다. AI 할 일은 그 세션 자신의 맡음을 표시하려고 이것을 읽습니다. 사용자의 쓰기에는 필요 없습니다. 맡음이 사용자를 막지 않기 때문이며, 서버는 사용자의 쓰기에 담긴 이름표를 읽지 않습니다.

### 맡음

- 에이전트는 자기 할 일의 항목, 곧 의견, 어긋남, 편집, 확인 지점을 자기 세션으로 맡습니다(API-131, SPEC-136). 맡음은 그 세션이 그 항목에 마지막으로 쓴 뒤 60분까지 이어지며, 그런 쓰기와 다시 맡기는 그 끝을 뒤로 밉니다. 맡음은 그때가 되거나, 항목이 닫히거나, 세션이 놓을 때(API-132) 끝납니다. 항목이 닫혔다는 것은 할 일이 더는 그것을 늘어놓지 않는다는 뜻입니다: 닫힌 의견, 풀린 어긋남, 닫혔거나 버린 편집, 기록된 확인 지점, 그리고 열린 PR도 저장된 기록도 적지 않는 철회된 확인 지점.
- 맡음이 이어지는 동안 다른 세션의 그 항목에 대한 에이전트의 쓰기는 `409` `claimed`로 거절하고, 그 `ends_at`이 맡음의 끝을 알려 줍니다. 할 일은 그때까지 그 세션들에게 그 항목을 맡겨진 것으로 보여 줍니다. 사용자의 쓰기는 맡음 때문에 거절하지 않습니다.
- 다른 세션의 항목, 닫힌 항목, 보고된 PR이 붙든 항목을 맡으려 하면 `409` `claimed`, `entry_closed`, `pull_request_reported`로 거절합니다. 연 PR의 보고는 그 항목의 맡음을 끝냅니다. 그때부터는 그 PR이 병합되거나 닫힐 때까지 모든 세션에 대해 그 항목을 붙들기 때문입니다(SPEC-133, SPEC-140).
- 쓰기가 어느 항목에 대한 것인지:

| 에이전트의 쓰기 | 그 쓰기의 항목 |
| --- | --- |
| 답글, 답했음 표시, 결정 | 그 의견 |
| 어긋남에 단 의견 | 그 어긋남 |
| 의견이나 어긋남에 답하는 제안, 그리고 그 철회 | 그 의견이나 어긋남 |
| 반영의 보고 | 그 편집 |
| 기록 PR의 보고 | 그 확인 지점 |
| 항목에 단 의견, 에이전트가 스스로 낸 제안 | 없음 |

### 바꾸는 것이 없는 응답

결과가 이미 그렇게 된 쓰기는 아무것도 바꾸지 않고, 응답이 `changed: false`로 그렇다고 말합니다: 답했다고든 결정했다고든 이미 닫힌 의견에 답했음을 표시하는 것(SPEC-127), 이미 철회한 제안이나 확인 지점을 철회하거나 이미 버린 반영을 버리는 것, 그 항목의 마지막 보고를 되풀이하는 보고. 다른 결과가 닫은 쓰기는 그 상태와 함께 `409`로 거절합니다: 열려 있지 않은 제안을 받거나 버리는 것(`proposal_not_open`, SPEC-131), 항목의 상태에 맞지 않는 보고. 쓰기 ID로 다시 보낸 쓰기는 무슨 말이었든 첫 응답을 받습니다([쓰기 ID](#쓰기-id)).

## 보내기

보내기(API-136)는 저장된 스냅샷, 프로젝트 공간, 그 그림, 어긋남, 확인 지점을 기기가 가져온 기본 브랜치의 최신 커밋에 맞춥니다(SPEC-111, SPEC-114):

1. 허브는 먼저 그 프로젝트의 보낼 편지함을 보냅니다([보낼 편지함](#보낼-편지함)).
2. 서버가 쥔 커밋을 묻습니다(API-109): 저장된 스냅샷의 `revision`과 `default_commit`. `404` `project_not_found`는 서버가 아무것도 쥐지 않았다는 뜻입니다. `code`가 없는 `404`는 1차의 서버가 준 것이며, 그 서버는 먼저 0.2 판이 필요합니다. 그때 허브는 아무것도 보내지 않습니다.
3. 새 스냅샷을 찍고(API-133), SPEC-105처럼 저장소를 읽어 그 기본 커밋을 Git으로 확인합니다:

| 서버가 쥔 것 | 스냅샷의 커밋 | 허브 |
| --- | --- | --- |
| 스냅샷이 없거나, 기본 커밋이 있는 스냅샷이 없음 | 아무것이나 | `replaces` 없이 보냅니다 |
| 커밋 H | H | `replaces` 없이 보냅니다 |
| 커밋 H | H의 후손 | `replaces: H`와 함께 보냅니다 |
| 커밋 H | H의 조상이거나, 체크아웃에 H가 없음 | 아무것도 보내지 않고, 기본 브랜치를 가져와 다시 보내라고 말합니다 |
| 커밋 H | 기본 브랜치를 다시 쓴 뒤처럼 H의 후손이 아님 | 아무것도 보내지 않고 두 커밋을 적습니다. 에이전트가 사용자의 동의를 받은 뒤에만 쓰는 `--replace-held`가 있으면 `replaces: H`와 함께 보냅니다 |
| 커밋 H | 체크아웃에 기본 브랜치가 없어 커밋이 없음 | 아무것도 보내지 않고, head를 기록하는 법(`git remote set-head origin --auto`)을 말합니다 |

4. 스냅샷을 1 MiB 이하의 압축 JSON으로 보냅니다(API-105).
5. 서버는 그것이 다음 판일 때 저장하며, 커밋을 이름으로만 견주는 커밋 규칙을 따릅니다:

| 서버가 쥔 것 | 스냅샷 | 서버 |
| --- | --- | --- |
| 그 프로젝트의 것이 없음 | 아무것이나 | 새 프로젝트로 저장합니다. 이미 30개를 쥐었으면 `409` `too_many_projects` |
| 기본 커밋이 없는 스냅샷 | 아무것이나 | 저장된 것보다 이르지 않게 찍혔으면 저장하고, 아니면 `stored_at`과 함께 `409` `older_snapshot` |
| 커밋 H | H의 것 | 위와 같습니다 |
| 커밋 H | `replaces: H`가 있는 다른 커밋의 것 | 저장합니다 |
| 커밋 H | `replaces: H`가 없는 다른 커밋의 것, 또는 커밋이 없는 것 | `held_commit`과 함께 `409` `commit_not_replaced` |
| 커밋 H, 그리고 이 보내기가 읽은 뒤 다른 보내기가 먼저 저장함 | 아무것이나 | 새 `held_commit`과 함께 `409` `commit_not_replaced` |

6. 0.2의 스냅샷이면 같은 요청이, 공간이 없을 때 저장소의 주소에 묶인 프로젝트 공간을 만들고(SPEC-117), 바뀐 그림을 그리고 최신이 아닌 그림을 표시하며(SPEC-118), 그림이 바뀌었거나 다시 최신이 된 부분을 점검하고(SPEC-120, SPEC-121), 단계 기록이 적은 확인 지점을 표시합니다(SPEC-140). 이 모두를 하거나 아무것도 하지 않습니다(05단계의 [보내기](../05-erd/nexus.ko.md#보내기)). 주소가 공간이 묶인 주소가 아니거나, 공간에는 주소가 있는데 스냅샷에 없으면 `bound`와 함께 `409` `repository_mismatch`로 거절합니다. 주소에 묶이지 않은 공간은 스냅샷이 처음 적은 주소를 받습니다(05단계의 고른 것 9).
7. 서버는 판 번호, 이제 쥔 기본 커밋, 바꾼 커밋, 그린 그림·다시 최신이 된 그림·최신이 아니라고 표시한 그림, 열고 푼 어긋남, 기록된 확인 지점, AI 할 일의 개수로 답하며, 목록은 저마다 20개까지입니다(`PushAnswer02`). 0.1의 스냅샷은 1차의 응답, 곧 `name`과 `revision`을 받고, 저장된 스냅샷만 바꿉니다. 프로젝트에 공간이 있으면 그 그림과 항목은 그대로입니다.

공간이 묶이는 주소는 `origin` 원격의 주소를 한 꼴로 맞춘 것이며, 허브가 스냅샷에 쓰고 서버가 견줍니다: 사용자 이름과 비밀번호를 빼고, `git@example.com:owner/repo.git`과 `ssh://git@example.com/owner/repo.git`은 `https://example.com/owner/repo`로, 끝의 `.git`이나 `/`를 빼고, 호스트는 소문자로, `http`는 `https`로 씁니다.

30초 안에 응답이 없거나 네트워크가 없는 보내기는 알리기만 하고 아무것도 간직하지 않습니다. 다음 보내기는 새 스냅샷을 찍기 때문입니다(SPEC-111).

## 읽기

| 읽기 | 담는 것 | 최대 |
| --- | --- | --- |
| 허브 페이지(API-101) | 저장된 모든 스냅샷, 그리고 공간이 있는 프로젝트마다 그 그림, 열린 의견·제안·어긋남의 개수, 기록을 기다리는 NEXUS에서 통과한 확인 지점, `checkpoint-withdrawn` 경고(SPEC-123) | 프로젝트마다 그림 150개, 확인 지점 100개, 경고 100개와 그 총수 |
| 그림 하나(API-111) | 문서 판과 최신 여부가 있는 그림 자료; 최근에 움직인 것부터 그 열린 의견과 저마다의 답글 수와 마지막 답글; 닫힌 의견의 ID; 단계별 원본 글을 뺀 열린 제안; 닫히지 않은 반영; 그 그림에 관한, 그 부분의 열린 어긋남(SPEC-119) | 저마다 500개, 어긋남은 1,000개와 그 총수 |
| 단계 현황(API-112) | 스냅샷에 있는 그 단계의 기록과 점검; 열린 어긋남, 열린 의견, 반영 대기; 아직 어느 기록도 적지 않았거나 철회한 뒤에 기록이 적은, NEXUS에서 통과한 확인 지점(SPEC-138) | 저마다 50개와 그 총수 |
| AI 할 일(API-113) | 그 순서대로 에이전트를 기다리는 의견, 열린 어긋남, 반영 대기, 확인 지점([AI 할 일](#ai-할-일)) | 저마다 50개와 그 총수 |
| 의견 하나(API-114) | 그 답글, 결정, 제안 | 모두. 답글은 많아야 200개 |
| 제안(API-115), 편집(API-116), 확인 지점(API-117) 하나 | 제안의 단계별 원본 글까지 그 항목 전체 | |
| 지우기의 미리 보기(API-110) | 지우기가 지우는 것, 그리고 ID로 적은 열린 의견, 열린 제안, 반영 대기, 아직 기록되지 않은 확인 지점 | 저마다 20개와 그 총수 |

어느 의견, 제안, 어긋남이 떨어져 있는지, 곧 지금 그림에 그 항목이 더는 없는지는 보기 화면이 찾습니다. 그림 자료의 항목을 읽는 것은 보기 화면뿐이기 때문입니다(SPEC-119). 0.1의 허브만 보낸, 공간이 없는 프로젝트에는 그림이 없습니다: 그림 보기와 할 일은 `404` `space_not_found`이고, 단계 현황은 기록과 점검만 보여 줍니다.

### AI 할 일

할 일(API-113, SPEC-135)은 다음 순서로 늘어놓습니다:

1. 에이전트를 기다리는 열린 의견([의견이 기다리는 쪽](#의견이-기다리는-쪽)), 오래된 것부터.
2. 열린 어긋남, `warn`을 `info`보다 먼저, 오래된 것부터.
3. 반영 대기, PR이 없는 것부터, 오래된 것부터.
4. 저장된 기록이 적지 않은, NEXUS에서 통과한 확인 지점을 오래된 것부터, 그다음 열린 PR이나 저장된 기록이 아직 적는 철회된 것. 저마다 `why`가 있습니다: `not-recorded`, `withdrawn-in-review`, `withdrawn-recorded`.

사용자를 기다리는 의견의 개수(`waiting_for_user`)와 다른 세션이 맡은 항목의 개수(`taken`)도 셉니다. 어느 세션이 맡은 항목에는 맡음의 끝이 있고, `Nexus-Session`이 적은 세션의 것이면 `mine`으로 표시합니다. 그 헤더가 없으면 모든 맡음을 다른 세션의 것으로 셉니다. 보고된 열린 PR이 붙든 반영이나 확인 지점에는 그 PR이 있어, 다른 세션은 그것을 검토 중으로 보고 건너뜁니다.

## 의견이 기다리는 쪽

의견의 기록은 그 글, 답글, 그리고 그 의견에 답하는 제안과 그 받음이나 버림입니다. 철회한 제안은 세지 않습니다.

| 마지막 기록 | `waits` |
| --- | --- |
| 사용자의 것: 의견, 답글, 또는 그 의견에 답하는 제안을 받거나 버림 | `agent` |
| 에이전트의 것: 의견, 답글, 또는 그 의견에 답하는 열린 제안 | `user` |
| 의견이 닫힘 | `null` |

- 사용자의 답글이 의견을 매듭지으면 `settled`는 `true`가 되고, 의견은 에이전트가 결정을 기록하기를 기다립니다(SPEC-127, SPEC-132). 결정은 의견을 `decided`로 닫습니다.
- 그 의견에 답한 마지막 제안을 버렸고 그 뒤로 에이전트가 그 의견에 쓰지 않았으면 `dismissed`는 `true`입니다(SPEC-131).
- 닫힌 의견에 사용자가 답글을 달면 의견은 다시 열려 에이전트를 기다리고, 에이전트의 답글은 `409` `comment_closed`로 거절합니다. 의견을 다시 여는 것은 이 답글이며, 따로 된 요청은 없습니다.

## 보고

### 반영의 보고

에이전트는 반영 대기가 어떻게 됐는지 보고합니다(API-126, SPEC-133). `opened`, `merged`, `closed`에는 PR이, `reflected`에는 그 단계별 원본이 이미 변경을 담은 커밋이 있고, `needs-user`에는 아무것도 없습니다:

| 사건 | 편집의 상태 | 바뀐 상태 |
| --- | --- | --- |
| `opened` | `pending`이나 `needs-user` | PR이 붙든 `in-review` |
| `merged` | 그 PR이 있는 `in-review`, 또는 `pending`이나 `needs-user` | 그 PR이 있는 `closed` |
| `closed` | 그 PR이 있는 `in-review` | `pending` |
| `reflected` | `pending`이나 `needs-user` | 그 커밋을 `closed_commit`으로 지닌 `closed` |
| `needs-user` | `pending` | 사용자가 버릴 수 있는 `needs-user`(API-127) |

- 편집의 마지막 보고를 되풀이하는 보고는 아무것도 바꾸지 않습니다(`changed: false`).
- 보고된 다른 PR이 붙든 편집의 `opened`는 `409` `pull_request_reported`로, 붙든 PR이 아닌 다른 PR의 `merged`나 `closed`는 `409` `pull_request_mismatch`로 거절하며, 둘 다 붙든 PR을 적습니다.
- 편집의 상태에 맞지 않는 그 밖의 보고는 `409` `edit_state`로 거절하고, 그 `state`가 상태를 알려 줍니다. 제 필드가 없거나 받지 않는 필드가 있는 사건은 `400`으로 거절합니다.

### 기록 PR의 보고

에이전트는 NEXUS에서 통과한 확인 지점을 단계 기록에 쓰는 PR을 보고합니다(API-130, SPEC-140):

| 사건 | 확인 지점 | 바뀐 상태 |
| --- | --- | --- |
| `opened` | 통과했고, 보고된 PR 가운데 열린 것이 없음 | PR이 붙든 `pr_state: open` |
| `merged` | 보고된 PR이 열려 있음 | `pr_state: merged` |
| `closed` | 보고된 PR이 열려 있음 | 어느 세션이든 맡을 수 있는 `pr_state: closed` |

- 철회한 확인 지점의 `opened`는 `409` `checkpoint_withdrawn`으로 거절하므로, 새 기록은 그것을 적지 않습니다. 철회한 확인 지점의 열린 PR에 대한 `merged`와 `closed`는 받습니다. 에이전트가 그 PR을 닫기 때문입니다(SPEC-140).
- 병합된 PR이 확인 지점을 기록하는 것은 아닙니다. 저장된 기록이 그것을 적는 다음 보내기가 기록하고, 그 `recorded_commit`을 정합니다.
- 되풀이와 다른 PR에는 반영과 같이 답합니다.


## 허브의 명령

### 명령 돌리기

- 허브는 1차처럼 허브 스킬의 `scripts` 폴더에 있는 `hub.py`이며, Windows, macOS, Linux에서 도는 표준 라이브러리만 쓴 Python 3.8 이상입니다. 1차의 옵션 `--home`과 `--version`, 그리고 다섯 명령과 그 옵션을 그대로 두고, 0.2는 아래 명령마다 적은 대로 그것을 넓힙니다.
- 서버에 닿는 명령, 곧 `push`, `remove`, `todo`, 에이전트의 쓰기, `show`, `claim`, `release`, `outbox --send`는 서버의 주소를 `--url`, 그다음 `CORTHEX_NEXUS_URL`, 그다음 프로필의 `nexus.url`에서 가져옵니다: `https`이거나, 기기 자신일 때만 `http`입니다. 서비스 토큰은 `CORTHEX_NEXUS_CLIENT_ID`와 `CORTHEX_NEXUS_CLIENT_SECRET`에서 가져와 보내며(기기 위의 서버에는 필요 없습니다), 절대 파일, 로그, 메시지에 쓰지 않습니다(REQ-109, REQ-110). 리디렉션은 따라가지 않고, 리디렉션이나 JSON 까닭이 없는 `401`, `403`은 거절된 토큰으로 봅니다(REQ-111). `remove`를 빼고는 `nexus.push`에 있는 프로젝트에만 됩니다.
- 에이전트의 쓰기, `claim`, `release`에는 `--session`이나 `CORTHEX_NEXUS_SESSION`에서 가져오는 세션 이름표가 있어야 하고, `todo`는 그것이 주어지면 읽습니다.
- 글은 `--text TEXT`에서, 또는 `--text-file FILE`에서 UTF-8로 가져오며, `-`는 표준 입력입니다. `--reason`과 `--reason-file`, `--change`와 `--change-file`, `--source-file`도 그렇습니다. 허브는 글을 보내기 전에 스냅샷처럼 가립니다: 비밀값과 이메일 주소는 `[redacted]`가 되고, 사용자의 홈 폴더는 `~`가 됩니다(SPEC-128).
- `--part PART`는 부분을 적습니다. 없으면 명령은 프로젝트 전체에 관한 것입니다.
- `--json`은 프로젝트마다 JSON 객체 한 줄을 찍습니다: `command`; `project`; 아래의 `outcome`; 서버의 응답인 `answer`; 거절에 대한 서버의 문제 세부 정보인 `problem`; 실패나 허브 자신의 거절의 종류인 `failure`, 이를테면 `no network`, `timeout`, `HTTP 503`, `no service token`, `refused token`, `not in nexus.push`; 그리고 보낼 편지함의 쓰기 가운데 몇 개를 보냈고(`sent`), 버렸고(`dropped`), 기다리는지(`waiting`) 적은 `outbox`. 이것이 없으면 허브는 같은 것을 사람이 읽는 줄로 찍습니다.

| 종료 코드 | 결과 | 언제 |
| --- | --- | --- |
| 0 | `done` | 명령이 하라는 것을 했을 때. 바꾼 것이 없는 쓰기, 서버가 이미 받은 쓰기, 서버가 갖지 않은 프로젝트의 지우기, 빈 할 일도 여기에 듭니다 |
| 1 | `refused`나 `failed` | 서버나 허브 자신의 검사가 거절했거나 서버에 닿지 못했고, 다시 보내려고 기다리는 것이 없을 때 |
| 2 | | 명령 줄이 틀렸을 때: 모르는 옵션, 꼴이 다른 ID나 이름표, UTF-8이 아닌 글 파일, 빠진 세션 이름표, 또는 비밀값이나 이메일 주소가 든 링크나 역할 |
| 3 | `kept` | 쓰기가 보낼 편지함에서 기다릴 때([보낼 편지함](#보낼-편지함)) |

### 스냅샷과 기록

`snapshot`(API-133):

```txt
hub.py snapshot [PROJECT ...] [--path FOLDER] [--repo ALIAS=FOLDER ...] [--print]
```

1차와 같되 형식은 `corthex-hub/0.2`입니다([스냅샷 0.2](#스냅샷-02)): 0.2부터 스냅샷은 부분, 기본 브랜치의 커밋에서 가져온 그림 자료, 저장소의 단계 기록, 먼저 물을 일도 담고(SPEC-104\~SPEC-110), 그 점검에는 [새 규칙](#점검-규칙)이 듭니다.

`status`(API-134):

```txt
hub.py status PROJECT STAGE [--part PART] [--state STATE] [--next TEXT]
              [--checkpoint TEXT --by ROLE --date DATE [--where LINK] [--nexus CHECKPOINT]]
              [--check LEVEL MESSAGE ...] [--clear-checks] [--reset] [--repository]
```

- 체크아웃에 단계 기록이 있으면, 또는 첫 기록이라면 `--repository`가 있을 때, 단계의 기록을 저장소의 작업 트리, 곧 `.corthex/stages/<part>.json`에, 부분이 없는 프로젝트라면 `.corthex/stages.json`에 씁니다(SPEC-137). 아니면 1차처럼 기기의 진행 기록 파일에 씁니다. 에이전트는 기록을 작업과 함께 그 PR에서 커밋합니다. 허브는 절대 커밋하거나, 푸시하거나, PR을 열지 않습니다.
- 기록에서 `--checkpoint`는 단계의 목록에 확인 지점을 더합니다: 승인한 것, 그것을 승인한 역할인 `--by`(이를테면 `관리자`), `--date`, 그리고 승인한 곳의 링크인 `--where`. `--nexus`는 NEXUS에서 통과한 확인 지점을 적으며, 그 링크는 기본으로 서버에 있는 그 단계 현황, 곧 `<nexus.url>/overview/<project>/<part>/<stage>#<checkpoint>`입니다(SPEC-140). `--state done`에는 날짜가 있는 확인 지점이 기록에 있어야 합니다(REQ-085). 진행 기록 파일에서 `--checkpoint`는 1차의 뜻 그대로입니다.
- 파일은 TBL-115가 말하는 대로 씁니다: 두 칸 들여 쓴 JSON, 그 순서대로의 필드, 끝의 LF이며, 임시 파일에 쓰고 옮깁니다. `updated`는 쓴 시각이고 기기의 시간대를 지닙니다.

`build`(API-135):

```txt
hub.py build [PROJECT ...] [--out FILE] [--no-scan]
```

1차와 같되 페이지 자료는 `corthex-hub-page/0.2`입니다([페이지 자료](#페이지-자료)): 부분마다의 단계 기록과 먼저 물을 일을 담습니다. 기기에서 만든 페이지에는 `spaces`가 없고, 그림과 개수는 서버에 있다고 말합니다(SPEC-123).

### 보내기와 지우기

`push`(API-136):

```txt
hub.py push [PROJECT ...] [--url URL] [--dry-run] [--replace-held]
```

- 이름이 없으면 `nexus.push`에 있는 모든 프로젝트를 저마다 [보내기](#보내기)가 말하는 대로 보내고, 응답을 알립니다: 판 번호, 다시 그린 그림·다시 최신이 된 그림·최신이 아니라고 표시한 그림, 열고 푼 어긋남, 기록된 확인 지점, AI 할 일에서 기다리는 것(SPEC-111).
- `--dry-run`은 아무것도 보내지 않으며, 보낼 편지함도 쥔 커밋을 묻는 질문도 보내지 않습니다: 스냅샷마다 그 개수와 크기, 보낼 그림과 빼는 그림을 보여 주고, 쥔 커밋은 보낼 때 확인한다고 말합니다.
- `--replace-held`는 커밋이 쥔 커밋의 후손이 아닌 스냅샷을, 쥔 커밋을 대신하는 것으로 적어 보냅니다. 에이전트는 사용자가 동의한 뒤에만 이것을 씁니다.
- 결과: `done`; `refused`는 `nexus.push`에 없는 프로젝트, 주소 없음, 토큰의 변수 없음(값 없이 그 이름을 적습니다), [보내기](#보내기)의 표가 막는 커밋, 1차의 서버, 거절된 토큰, 서버의 거절이며, 그 까닭과 함께 알립니다; `failed`는 네트워크가 없거나 30초 안에 응답이 없을 때입니다. 보내기는 절대 간직하지 않습니다. 다음 보내기가 새 스냅샷을 찍기 때문입니다.

`remove`(API-137):

```txt
hub.py remove PROJECT ... [--url URL] [--dry-run]
```

- `--dry-run`은 지우기가 지울 것을 읽어(API-110) 보여 주며, 열린 의견, 열린 제안, 반영 대기, 아직 기록되지 않은 확인 지점을 ID로, 저마다 20개까지 그 총수와 함께 보여 줍니다. 1차와 달리 서버에 닿으므로 서비스 토큰이 필요합니다. 허브 스킬은 에이전트가 그것을 보여 주고, 그 항목에 먼저 답하거나 반영하거나 기록하자고 하며, 사용자가 확인한 뒤에만 지우기를 보내게 합니다(SPEC-115).
- `--dry-run`이 없으면 지우기를 보냅니다(API-108). `404` `project_not_found`는 1차처럼 지울 것이 없다고 알리며 종료 코드는 0입니다. 지우기 뒤에 허브는 그 프로젝트의 보낼 편지함을 지우고, 프로젝트가 아직 `nexus.push`에 있으면 다음 보내기가 빈 공간으로 프로젝트를 되살린다는 것과 목록에서 빼는 법을 말합니다.
- 1차처럼 `nexus.push`가 적었든 아니든 프로젝트를 받습니다.

### 에이전트의 일

`todo`(API-138):

```txt
hub.py todo PROJECT [--session LABEL]
```

프로젝트의 보낼 편지함을 보내고, 세션 이름표와 함께 AI 할 일을 읽어 그 순서대로 찍으며, 사용자를 기다리는 의견과 다른 세션이 맡은 항목의 개수도 찍습니다(SPEC-135). `404` `space_not_found`는 빈 할 일과 종료 코드 0이고, 에이전트는 그것에 대해 아무 말도 하지 않습니다. 서비스 토큰이 없거나 응답이 없으면 `failed`이고, 에이전트는 자기 일을 이어 갑니다(REQ-185).

쓰기(API-139\~API-146):

```txt
hub.py comment  PROJECT --stage STAGE [--part PART] [--item ID] [--quote TEXT]
                [--discrepancy ID] [--commit COMMIT] (--text TEXT | --text-file FILE)
hub.py reply    PROJECT COMMENT (--text TEXT | --text-file FILE)
hub.py answered PROJECT COMMENT
hub.py decide   PROJECT COMMENT --link LINK [--text TEXT | --text-file FILE]
hub.py propose  PROJECT --stage STAGE [--part PART] --item ID [--item ID ...] [--adds ID ...]
                (--reason TEXT | --reason-file FILE) (--change TEXT | --change-file FILE)
                [--source-file FILE] [--comment ID | --discrepancy ID] [--commit COMMIT]
hub.py withdraw PROJECT PROPOSAL
hub.py reflect  PROJECT EDIT EVENT [--pr LINK] [--commit COMMIT]
hub.py record   PROJECT CHECKPOINT EVENT --pr LINK
```

- 저마다 새 쓰기 ID와 세션 이름표로 쓰기 하나를 보내며(API-118\~API-123, API-126, API-130), 그 전에 프로젝트의 보낼 편지함을 보냅니다. `--item`이 없는 `comment`는 그림 자체에 다는 의견이고 `--quote`가 있어야 합니다. `reflect`는 사건 `opened`, `merged`, `closed`, `reflected`, `needs-user`를, `record`는 `opened`, `merged`, `closed`를 받습니다([보고](#보고)).
- `decide`는 `https`가 아니거나 비밀값이나 이메일 주소가 든 링크를 보내기 전에 거절합니다(SPEC-132).
- 보내지 못한 쓰기는 보낼 편지함에서 기다리고 종료 코드는 3입니다. 서버의 거절은 그 까닭과 함께 알리고 다시 보내지 않습니다(SPEC-128, SPEC-129).

`show`(API-147):

```txt
hub.py show PROJECT ID
```

의견, 제안, 편집, 확인 지점 하나를 그 `nc_`, `np_`, `ne_`, `nk_` ID로 읽습니다(API-114\~API-117): 모든 답글이 있는 의견, 단계별 원본 글이 있는 제안, 그리고 에이전트가 그 기록의 PR을 병합하기 전에 읽는 확인 지점(SPEC-140). 할 일과 단계 현황은 어긋남을 통째로 담으므로, `nd_` ID는 틀린 명령 줄입니다.

`claim`과 `release`(API-148, API-149):

```txt
hub.py claim   PROJECT ENTRY
hub.py release PROJECT ENTRY
```

세션을 위해 항목을 맡거나, 세션의 맡음을 끝냅니다(API-131, API-132). 맡음은 절대 보낼 편지함에서 기다리지 않습니다: 보내지 못한 맡음은 항목을 맡지 않은 채로 두고, 허브가 그렇다고 말합니다(05단계의 [보낼 편지함](../05-erd/nexus.ko.md#보낼-편지함-tbl-117)).

### 보낼 편지함

`outbox`(API-150):

```txt
hub.py outbox [PROJECT ...] [--send]
```

기다리는 쓰기를 프로젝트별로, 그 요청, 만든 때, 시도 횟수, 마지막 실패와 함께, 글은 빼고 늘어놓습니다. `--send`는 그것을 보냅니다.

- 보내지 못한 쓰기는 간직합니다: 네트워크가 없음, 30초 안에 응답이 없음, `429`, `500`, `502`, `503`, `504`, 기기에 서비스 토큰이 없음, 거절된 토큰, 또는 Access 설정을 고치면 통과할 `403` `access_missing`이나 `access_other_app`(SPEC-129).
- 서버가 `409`나 `404`처럼 다른 까닭으로 거절한 쓰기는 버리고 그 까닭과 함께 알립니다. 다시 보내도 바뀌는 것이 없기 때문입니다. 만든 지 7일이 지난 쓰기도 버립니다. 그것이 답한 할 일이 이미 다른 데로 넘어갔기 때문입니다.
- 프로젝트로 서버에 닿을 때마다, 곧 보내기, `todo`, 쓰기, `show`, `claim`, `release`, `outbox --send`마다, 허브는 먼저 그 프로젝트의 보낼 편지함을 오래된 것부터, 쓰기마다 자기 쓰기 ID와 세션 이름표로 보냅니다. 다시 간직하게 된 첫 쓰기에서 멈추므로, 쓰기는 그 순서를 지킵니다.
- 쓰기마다 `~/.corthex/hub/` 아래의 파일 하나, 곧 `outbox/<project>/<time>.<write>.json`(TBL-117)이며, 계약의 `OutboxFile` 꼴입니다. 한 기기의 허브들은 05단계가 말하는 대로 잠금 `outbox/<project>.lock`으로 프로젝트의 보낼 편지함을 차례로 씁니다.
- 보낼 편지함은 절대 서비스 토큰을 담지 않고, 허브는 간직한 쓰기의 글을 절대 로그에 보이지 않습니다.

## 형식

### 스냅샷 0.2

`corthex-hub/0.2`가 1차의 형식에 더하는 필드는 05단계의 [스냅샷](../05-erd/nexus.ko.md#스냅샷-tbl-114)에 있는 TBL-114의 것이고, 계약의 `Snapshot02`가 그것을 검사합니다. 목록을 줄인 발췌입니다:

```json
{
  "schema": "corthex-hub/0.2",
  "generator": "corthex-nexus 0.2.0",
  "generated_at": "2026-11-03T10:00:00+09:00",
  "project": { "name": "acme-shop", "title": "Acme Shop", "parts": ["orders", "billing"] },
  "repos": {
    ".": {
      "commit": "<full commit id>", "branch": "work", "dirty": true,
      "web": "https://github.com/example/acme-shop", "url": "https://github.com/example/acme-shop",
      "default": { "branch": "main", "commit": "<full commit id>", "time": "2026-11-03T09:40:00+09:00" }
    }
  },
  "replaces": "<the held commit>",
  "records": { "from": "repository", "commit": "<full commit id>", "time": "2026-11-03T09:40:00+09:00" },
  "stages": {
    "05-erd": {
      "state": "in_progress", "source_state": "found",
      "parts": {
        "orders": { "state": "in_progress", "checkpoints": [], "next": "주문을 날짜로 색인하기", "updated": "2026-11-03T09:30:00+09:00" }
      }
    }
  },
  "items": [], "checks": [], "summary": {},
  "pictures": [
    { "part": "orders", "stage": "05-erd", "commit": "<full commit id>", "time": "2026-11-03T09:40:00+09:00",
      "source": { "format": 1, "tables": [], "without_table": [] } }
  ],
  "left_out": [{ "part": "billing", "stage": "07-sitemap", "why": "other-repository" }],
  "ask_before": { "entries": ["releases", "deletions"], "source": "project", "left_out": ["external messages", "deploys", "payments", "publishing"] }
}
```

- 허브는 이것을 압축 JSON으로 보냅니다. 1차의 상한인 항목 3,000개, 점검 2,000개, 1,000,000바이트를 지켜 서버의 1 MiB 아래에 머뭅니다. 그림 자료 때문에 그것을 넘게 되면 가장 큰 것부터 그림을 통째로 빼고, 저마다 `left_out`에 `why: size`로, 그리고 `picture-left-out` 점검으로 적습니다(REQ-192).
- `repos.".".url`은 [보내기](#보내기)의 꼴로 맞춘 `origin` 원격의 주소이고, `repos.".".default`는 SPEC-105가 찾는 대로의 기본 브랜치입니다. 그것이 없으면 스냅샷에는 그림 자료가 없고 `pictures-not-sent` 점검이 있습니다.
- `replaces`는 보내기가 대신하는 쥔 커밋입니다([보내기](#보내기)). `hub.py snapshot`은 이것을 쓰지 않습니다.
- `records`는 단계 기록을 가져온 곳을 말합니다: 그 커밋과 시각이 있는 `repository`, 또는 `status-file`.
- 서버는 스냅샷을 `pictures` 없이 저장하고 그 원본은 그림이 간직하므로(05단계의 고른 것 3), `API-107`은 그것이 빠진 스냅샷, 곧 계약의 `StoredSnapshot02`를 돌려줍니다.

### 그림 자료

그림 자료는 저마다 `format: 1`과 세 가지 꼴 가운데 하나, 곧 계약의 `DomainSource`, `ErdSource`, `SitemapSource`를 지닙니다. 허브는 그것을 기본 브랜치의 커밋에서 한 부분의 단계별 원본 문서로부터 가져옵니다(SPEC-105\~SPEC-108):

- 요소마다 그 커밋에서의 파일과 줄인 `where`가 있으며, `docs/05-erd/nexus.sql:15`처럼 저장소에 대한 상대 경로입니다.
- 요소의 `id`는 그 추적 ID이고, 없으면 `""`입니다. `context`는 CTX ID이거나 `""`입니다. 이름은 120자에서, 다른 글은 제목처럼 300자에서 자르고, 목록마다 계약이 정한 상한에서 멈춥니다.
- 상태가 삭제라고 말하는 요소의 `removed`는 `true`이며, 상태는 [reading.md](../../plugins/corthex-nexus/skills/corthex-hub/references/reading.md)가 읽는 대로 읽습니다.
- 비밀값과 이메일 주소는 `[redacted]`가 됩니다(REQ-191).
- 아래의 양식으로 다 읽을 수 없는 문서는 읽을 수 있었던 것을 주고, 그 자리를 적은 `picture-partial` 점검을 냅니다.

**DDD 보드(`01-domain`).** 01단계 양식 [01-domain.md](../../plugins/corthex/skills/corthex-discover/references/01-domain.md)의 꼴을 영어로, 그리고 [docs/01-domain/nexus.ko.md](../01-domain/nexus.ko.md)처럼 한국어 문서가 쓰는 대로 한국어로 읽습니다. 허브는 표를 그 머리 줄로 찾고, 여기 적은 열을 어느 순서로든 읽으며, 이름은 대소문자와 띄어쓰기를 가리지 않고 견주고, 다른 열은 무시합니다.

| 요소 | 영어 양식 | 한국어 양식 |
| --- | --- | --- |
| 컨텍스트 | `### CTX-001 Ordering`처럼 CTX ID로 시작하고 그 이름이 뒤따르는 제목, 그 아래의 `Purpose: …` 줄과 `- External systems: …` 글머리 | 같은 제목과 `목적: …`, `- 바깥 시스템: …` |
| 그 유형과 애그리거트 | `Context`, `Type`, `Aggregates` 열이 있는 표 | `컨텍스트`, `종류`, `애그리거트` |
| 그 명령 줄 | 컨텍스트의 제목 아래에서 `Given by`, `Read model`, `Command`, `Aggregate`, `Events` 열이 있는 표. `Given by`에 홀로, 또는 주는 다른 쪽 뒤에 `Policy: when …`이 있는 줄은 정책입니다 | `주는 쪽`, `읽기 모델`, `명령`, `애그리거트`, `사건`; `정책: …` |
| 읽기 모델 | 명령 줄의 읽기 모델, 그리고 `Read model`, `Shows` 열이 있는 표 | `읽기 모델`, `보여 주는 것` |
| 의존 | `From`, `To`, `Kind`, `Why`, `Data` 열이 있는 표. `call`로 시작하는 종류는 `call`, `event`로 시작하는 것은 `event`, 그 밖은 `""` | `어디서`, `어디로`, `종류`, `까닭`, `오가는 것`; `바로 묻기`는 `call`, `사건 알림`은 `event` |
| 핫스팟 | `Hotspot`, `Context`, `State`, `Answer or next step` 열이 있는 표. `1.`처럼 글 첫머리의 번호가 핫스팟의 `number`이고, `Context` 아래의 CTX ID가 그 컨텍스트입니다 | `핫스팟`, `컨텍스트`, `상태`, `답이나 다음 할 일` |
| 용어집 | TERM ID가 든 `ID` 열과 `Term` 열이 있는 표 | `ID`, `용어` |
| 삭제된 컨텍스트와 용어 | `ID` 열과 삭제라고 말하는 `Status` 열이 있는 표 | `ID`, `상태`와 `삭제` |

애그리거트나 읽기 모델은 `Picture (TERM-085)`처럼 그 이름 옆에 적은 TERM ID를, 아니면 같은 문서에서 대소문자와 띄어쓰기를 가리지 않고 그 이름이 용어인 용어집 줄의 것을 가져옵니다. 그런 줄이 없거나 둘이면 `board-term-missing` 경고를 받습니다(SPEC-106).

**ERD(`05-erd`).** [reading.md](../../plugins/corthex-nexus/skills/corthex-hub/references/reading.md)와 05단계 양식 [05-erd.md](../../plugins/corthex/skills/corthex-contract/references/05-erd.md)의 SQL입니다:

```sql
-- without a table: TERM-122
-- TBL-101 snapshots (CTX-009, terms: none) ← SPEC-111, SPEC-114
CREATE TABLE snapshots (
  name TEXT PRIMARY KEY,
  revision INTEGER NOT NULL
);
-- TBL-103 pictures (CTX-012, TERM-085) ← SPEC-118
CREATE TABLE pictures (
  project TEXT NOT NULL REFERENCES snapshots (name) ON DELETE CASCADE,
  stage TEXT NOT NULL,
  PRIMARY KEY (project, stage)
);
```

- 표는 TBL ID 주석이 정하는 `CREATE TABLE`입니다. 그 이름 뒤의 괄호가 그 컨텍스트인 CTX ID와, 그 TERM ID나 `terms: none`을 줍니다. 둘 다 없는 주석은 `terms`를 빼며, SPEC-121이 그것을 알립니다.
- 열에는 그 이름, 적힌 그대로의 유형, `null`이 있으며, `null`은 `NOT NULL`인 열과 기본 키의 열에서 `false`입니다. 기본 키는 열이나 표의 `PRIMARY KEY`에서 옵니다. 유일 규칙은 열이나 표의 `UNIQUE`, 또는 `CREATE UNIQUE INDEX … ON`에서 오며, `WHERE`가 있는 것은 `partial: true`입니다. 외래 키는 열이나 표의 `REFERENCES`, 또는 `ALTER TABLE … ADD [CONSTRAINT …] FOREIGN KEY`에서 오며, `on_delete`는 소문자로, 없으면 `""`입니다.
- 부분의 SQL 어디에든 있는, TERM ID가 뒤따르는 주석 줄 `-- without a table:`은 부분이 표 밖에 두는 애그리거트를 적습니다.
- 표지 `terms: none`, `without a table:`, `without a screen:`은 둘레의 코드처럼 모든 언어에서 같습니다.

**사이트맵(`07-sitemap`).** 07단계 양식 [07-sitemap.md](../../plugins/corthex/skills/corthex-screen/references/07-sitemap.md)의 YAML에 `terms`를 더한 것입니다. 아래는 NEXUS 자신의 [nexus.yaml](../07-sitemap/nexus.yaml)에 있는 화면 둘입니다:

```yaml
- id: SCR-104
  name: Stage detail
  path: "/#p={project}&s={stage}"
  access: anyone Cloudflare Access lets in, or the device's user
  flows: [FL-105, FL-113]
  terms: none
  status: active
  children:
    - id: SCR-109
      name: Stage overview
      path: "/overview/{project}/{part}/{stage}"
      access: anyone Cloudflare Access lets in, on the server
      flows: [FL-113]
      terms: [CTX-007, TERM-120]
      status: active
# without a screen: TERM-121
```

- 화면마다 `id`, `name`, `path`, `access`, `flows`, 그리고 `children` 아래의 중첩에서 오는 `parent`, 곧 `screens`에서 그 부모의 자리를 지닙니다. 부분이 갖지 않은 부모는 화면을 맨 위에 두고 `picture-partial` 점검을 냅니다.
- `terms`는 화면의 컨텍스트인 CTX ID와 그것이 나타내는 TERM ID를 담습니다. `terms: none`과 `terms: []`는 아무것도 나타내지 않는다고 말하고, 둘 다 없는 화면은 `terms`를 뺍니다.
- TERM ID가 뒤따르는 주석 줄 `# without a screen:`은 부분이 어느 화면에도 보이지 않는 읽기 모델을 적습니다([앞 단계의 변경](#앞-단계의-변경)).

### 프로젝트 설정

프로젝트 설정 `.corthex/project.json`에 두 필드가 생기며, 핵심 플러그인의 [project.md](../../plugins/corthex/skills/corthex/references/project.md)가 0.2 릴리스와 함께 그것을 더합니다:

| 필드 | 유형 | 뜻 |
| --- | --- | --- |
| `parts` | 글의 목록 | 선택. 허브 페이지가 보이는 차례대로의 프로젝트의 부분: 소문자와 숫자로 된 낱말을 하이픈으로 이은, 저마다 100자까지의 서로 다른 이름 1\~50개. 문서는 단계별 원본에서 그 경로가 부분의 이름과 `/`, `.`, `-` 가운데 하나로 시작하는 부분에 속하고, 그런 이름 가운데 가장 긴 것이 이깁니다: 단계별 원본이 `docs/01-domain/`이면 `nexus.md`와 `nexus/board.md`는 `nexus`에 속합니다 |
| `ask_before` | 글의 목록 | 선택. 이 프로젝트에서 먼저 물을 일이며, 프로필의 목록을 대신합니다(SPEC-110) |

다른 꼴의 `parts`는 없는 것으로 치고 `parts-invalid` 경고를 냅니다. 허브는 핵심 플러그인의 기본 `ask_before` 목록, 곧 그 예시 프로필에 있는 `["external messages", "deploys", "payments", "deletions", "publishing"]`의 사본을 지니며, 기억의 컨텍스트가 그렇게 하듯 시험 하나가 둘을 견줍니다.

### 단계 기록

단계 기록은 05단계의 [단계 기록](../05-erd/nexus.ko.md#단계-기록-tbl-115)에 있는 TBL-115의 파일이고, 계약의 `StageRecords`가 그것을 검사합니다: `parts`가 적은 부분마다 `.corthex/stages/<part>.json`, 또는 부분이 없는 프로젝트에서는 `.corthex/stages.json`. 허브는 그것을 기본 브랜치의 커밋에서 Git의 객체 읽기로 읽고, `status`(API-134)로 작업 트리에 씁니다. 올바른 JSON이 아니거나, 다른 `format`이거나, 네 가지가 아닌 상태가 있는 파일은 `records-invalid` 경고를 받고, 그 단계는 `unknown`으로 보입니다(SPEC-109).

### 보낼 편지함의 파일

보낼 편지함의 파일은 저마다 05단계의 [보낼 편지함](../05-erd/nexus.ko.md#보낼-편지함-tbl-117)에 있는 TBL-117이며, 그 `path`, 곧 요청의 경로가 시도마다 첫 시도가 간 곳으로 가게 합니다. 계약의 `OutboxFile`이 그것을 검사합니다:

```json
{
  "format": 1,
  "write": "nw_6t9w2z5c8f1j",
  "project": "corthex",
  "request": "reply",
  "path": "/api/spaces/corthex/comments/nc_3a6d9g2j5m8r/replies",
  "session": "claude-code-4f2a91",
  "made": "2026-11-03T07:00:00.000Z",
  "body": { "text": "표는 부분마다 줄 하나를 간직합니다." },
  "tries": 1,
  "failure": "no network"
}
```

`request`는 에이전트의 [요청 이름](#요청-이름) 가운데 하나입니다. 파일은 쓰기 ID를 따옴표 없이 간직하고, 허브가 헤더에 따옴표를 더합니다.

### 페이지 자료

- 허브 페이지는 `<script id="hub-data" type="application/json">`에 `corthex-hub-page/0.2`, 곧 계약의 `HubPageData`를 담습니다: 1차의 멤버와 `spaces`이며, `spaces`는 공간이 있는 프로젝트마다 그 그림, 열린 것의 개수, 기록을 기다리는 확인 지점, 경고를 담습니다. `lang`은 1차처럼 서버의 `NEXUS_LANGUAGE`에서, 기기에서는 프로필에서 옵니다.
- 그림 보기와 단계 현황은 `<script id="view-data" type="application/json">`에 `corthex-view-page/0.2`, 곧 계약의 `ViewPageData`를 담습니다: `picture`나 `overview`인 `view`; API-111이나 API-112의 응답인 `data`; 그리고 서버가 그것을 읽지 못했을 때의 문제 세부 정보인 `problem`, 이를테면 `picture_not_found`. 쓰기 뒤에 보기 화면은 그 요청으로 자료를 다시 읽습니다.

## 점검 규칙

허브의 새 규칙이며, 허브의 [reading.md](../../plugins/corthex-nexus/skills/corthex-hub/references/reading.md)가 0.2 릴리스와 함께 이것을 더합니다:

| 규칙 | 수준 | 뜻 |
| --- | --- | --- |
| `pictures-not-sent` | warn | 저장소에 허브가 읽을 수 있는 기본 브랜치가 없습니다: `origin` 원격이 없거나, 그 head가 기록되지 않았거나, Git이 없습니다. 스냅샷에는 그림 자료가 없고, 메시지는 `git remote set-head origin --auto`를 돌리라고 말합니다(SPEC-105) |
| `picture-left-out` | warn | `left_out`이 말하는 대로, 그 크기 때문에 또는 그 단계별 원본이 다른 저장소에 있어서 그림 하나를 통째로 뺐습니다(SPEC-105) |
| `picture-partial` | warn | 그림으로 그리는 문서를 다 읽지 못해, 그 그림에는 읽을 수 있었던 것만 있습니다. 점검은 그 자리와 까닭을 적습니다: 이를테면 어느 컨텍스트 제목 아래에도 없는 표, 컨텍스트가 없는 문서, 부모가 없는 화면, 양식의 꼴이 아닌 YAML(SPEC-105, SPEC-106, SPEC-108) |
| `part-unknown` | info | 그림으로 그리는 문서가 어느 부분에도 속하지 않아, 프로젝트 전체의 그림에 그립니다(SPEC-105) |
| `parts-invalid` | warn | 프로젝트 설정의 `parts`가 서로 다른 부분 이름 1\~50개가 아니어서, 프로젝트를 부분 없이 읽습니다 |
| `board-term-missing` | warn | 애그리거트나 읽기 모델에 그 이름의 용어집 줄이 없거나 둘이어서, 용어가 없거나 첫 것을 씁니다(SPEC-106) |
| `records-invalid` | warn | 단계 기록 파일이 올바른 JSON이 아니거나 아는 형식이 아니거나, 기록에 네 가지가 아닌 상태, 확인 지점과 그 날짜가 없는 `done`, 13개가 아닌 단계 키, 설정이 적지 않은 부분이 있습니다. 점검은 그 파일과 무엇이 잘못됐는지 적습니다(SPEC-109) |
| `records-in-status-file` | info | 기본 브랜치의 커밋에서 저장소에 단계 기록이 없어 기기의 진행 기록 파일에서 가져왔으며, 저장소로 옮겨야 합니다(SPEC-109) |
| `ask-before-invalid` | warn | 프로젝트나 프로필의 `ask_before`가 글의 목록이 아니거나 프로필을 읽을 수 없어, 다음 목록을 씁니다(SPEC-110) |
| `ask-before-long` | info | 목록에 값이 30개보다 많아 앞의 30개를 간직합니다(SPEC-110) |

서버는 단계를 읽을 때, 곧 단계 현황과 허브 페이지에서 그 단계에 규칙 하나를 더하고, 저장된 스냅샷에는 절대 더하지 않습니다: NEXUS에서 철회한 확인 지점을 적은 저장된 단계 기록에 대한 `checkpoint-withdrawn`, `warn`입니다. 기록이 그것을 더는 적지 않는 보내기까지 단계의 기록된 상태 옆에 보입니다(SPEC-140).

## 상한

05단계의 [상한](../05-erd/nexus.ko.md#상한)이 그대로이고, 이 단계가 다음을 더합니다:

| 상한 | 값 |
| --- | --- |
| 쓰기의 본문 | 256 KiB |
| 서버의 시계보다 앞선 시각의 스냅샷 | 1차처럼 10분 |
| 읽기의 목록 | [읽기](#읽기)가 적은 대로 |
| 보내기 응답의 목록 | 저마다 20개와 그 개수 |
| 허브의 요청 | 30초 안의 응답 |

## 경우의 수

| 종류 | 계약이 적는 것 |
| --- | --- |
| 접근 | 모든 요청의 보안. Access가 답하므로 `401`은 절대 Worker의 것이 아닙니다. `access_missing`, `access_other_app`, `cross_site`, `user_only`, `agent_only`, `no_kind`가 있는 `403` |
| 입력 | `invalid_request`, `invalid_snapshot`, `clock_ahead`, `unknown_item`이 있는 `400`, 그리고 글과 본문의 `413`. 필드마다 05단계의 상한이 있습니다 |
| 대상 | 항목의 종류마다 코드가 있는 `404`. 꼴이 다른 경로 값도 같은 `404`를 받습니다 |
| 상태 변화 | `comment_closed`, `proposal_not_open`, `edit_state`, `checkpoint_recorded`처럼 까닭마다 코드가 있는 `409` |
| 되풀이 | 쓰기 ID: 다시 보낸 쓰기는 첫 응답을 받고, 다른 요청의 ID는 `409` `write_id_reused`를 받습니다. 보내기는 커밋 규칙을 따르고, 두 번 보낸 지우기는 `404`를 받습니다 |
| 동시성 | 쓰기는 하나씩 차례로 받습니다. 다른 보내기에 앞질린 보내기는 `409` `commit_not_replaced`를, 다른 세션이 맡은 항목은 `409` `claimed`를 받습니다 |
| 상한 | 공간의 상한에는 `409`, 크기에는 `413`. 서버 자신의 `429`는 없습니다: Cloudflare의 한도를 따르고, 허브는 `429`를 받은 에이전트의 쓰기를 보낼 편지함에 간직합니다 |
| 바깥 서비스 | 없음: 서버는 다른 서비스를 부르지 않습니다. D1의 실패는 `500` `internal`이고, 허브는 그것을 받은 에이전트의 쓰기를 간직합니다 |
| 자료 노출 | 응답에는 쓴 쪽의 종류 말고는 신원이 없고, 저장된 스냅샷에는 그림 자료가 없으며, 목록에는 제안의 단계별 원본 글 대신 그 길이가 있습니다 |
| 빈 응답과 스트림 | 목록마다 `nothing`이나 `empty` 예시가 보이듯 총수 0인 빈 목록. `204`와 스트림은 없습니다 |
| 화면 상태 | 더할 것 없음. 08단계가 응답마다 상태로 잇습니다 |
| AI 응답 | 없음: NEXUS는 AI 모델을 부르지 않습니다(REQ-121) |

## 오류 코드

계약의 `components.x-corthex.errors`가 적는 대로의 모든 요청의 코드이며, `code` 멤버는 다른 것을 받지 않습니다. 더하는 멤버는 그 코드가 [오류의 모양](#오류)에 더하는 것입니다. 사용자가 보는 말은 계약에 영어로 있는 초안을 옮긴 것이고, 08단계가 보기 화면의 상태를 위해 영어와 한국어로 최종 문구를 정합니다. 뜻과 클라이언트가 하는 일은 이 단계의 것입니다.

| 코드 | 상태 | 뜻 | 더하는 멤버 | 사용자가 보는 말 | 클라이언트가 하는 일 |
| --- | --- | --- | --- | --- | --- |
| `invalid_request` | 400 | 필드, 헤더, 본문이 제 꼴이 아닙니다. field가 그것을 적습니다 | `field` | 올바르지 않습니다. 표시한 칸을 확인해 주세요 | 보기 화면은 그 필드 옆에 말을 보여 줍니다. 허브는 필드를 알리고 그 쓰기를 보낼 편지함에서 버립니다 |
| `invalid_snapshot` | 400 | 스냅샷이 corthex-hub/0.1이나 0.2 형식이 아닙니다. field가 처음 잘못된 필드를 적습니다 | `field` | 스냅샷이 올바르지 않습니다 | 허브는 필드를 알리고, 다시 보내려고 간직하는 것은 없습니다 |
| `clock_ahead` | 400 | 스냅샷의 시각이 서버의 시계보다 10분 넘게 앞섭니다 | 없음 | 스냅샷의 시각이 미래입니다. 기기의 시계를 확인해 주세요 | 허브가 그것을 알립니다 |
| `unknown_item` | 400 | 제안이 그 그림에 없고 adds도 적지 않은 항목을 적습니다. items가 그것을 적습니다 | `items` | 제안이 그림에 없는 항목을 적었습니다 | 허브는 그 항목을 알리고, 에이전트는 단계별 원본을 확인합니다 |
| `access_missing` | 403 | Cloudflare Access가 요청을 검사하지 않았습니다 | 없음 | Cloudflare Access가 이 요청을 검사하지 않았습니다. 먼저 Access로 서버를 지켜 주세요 | 허브는 거절된 토큰으로 알립니다. 보기 화면은 로그인이 없다고 말하고 다시 불러오자고 합니다 |
| `access_other_app` | 403 | ACCESS_AUD가 적은 것이 아닌 다른 Access 애플리케이션이 요청을 검사했습니다 | 없음 | 이 요청은 다른 Access 애플리케이션을 위해 검사됐습니다 | access_missing과 같습니다 |
| `cross_site` | 403 | 브라우저가 다른 사이트에서 변경을 보냈습니다 | 없음 | 다른 사이트에서 온 변경은 받지 않습니다 | 보기 화면은 서버 자신의 주소에서 페이지를 열자고 합니다 |
| `user_only` | 403 | 요청에 사람 자신의 로그인이 필요합니다. needs는 user입니다 | `needs` | 직접 로그인한 본인만 할 수 있습니다 | 허브는 사용자가 보기 화면에서 이것을 한다고 알립니다 |
| `agent_only` | 403 | 요청에 서비스 토큰이 필요합니다. needs는 agent입니다 | `needs` | 이것은 에이전트만 허브를 거쳐 합니다 | 보기 화면은 절대 보내지 않습니다. 허브는 없거나 거절된 서비스 토큰을 알립니다 |
| `no_kind` | 403 | Access가 요청을 들여보냈지만, 그 신원이 사람의 로그인도 서비스 토큰도 아닙니다 | 없음 | 이 로그인으로는 여기에 쓸 수 없습니다 | 보기 화면과 허브가 그것을 알리고, 사용자가 Access 정책을 확인합니다 |
| `not_found` | 404 | 그런 경로가 없거나, 보기 화면의 코드에 그런 파일이 없습니다 | 없음 | 찾을 수 없습니다 | 보기 화면은 허브 페이지로 잇습니다 |
| `project_not_found` | 404 | 서버에 그 프로젝트의 스냅샷이 없습니다 | 없음 | 이 프로젝트는 서버에 없습니다 | 허브는 지우거나 읽을 것이 없다고 알립니다. 보내기는 프로젝트를 새것으로 저장합니다 |
| `space_not_found` | 404 | 0.1의 허브만 보냈으므로 프로젝트에 공간이 없습니다 | 없음 | 이 프로젝트에는 아직 서버에 그림이 없습니다. corthex-nexus 0.2로 보내 주세요 | 허브는 그렇다고 말하고 아무것도 보내지 않습니다 |
| `part_not_found` | 404 | 저장된 스냅샷에 그 부분이 없습니다 | 없음 | 이 부분은 프로젝트의 스냅샷에 없습니다 | 보기 화면은 허브 페이지로 잇습니다 |
| `picture_not_found` | 404 | 공간에 그 부분과 단계의 그림이 없습니다. why가 아직 그리지 않았는지, 스냅샷이 크기 때문에 뺐는지, 그 원본이 다른 저장소에 있는지 말합니다 | `why` | 이 단계와 부분에는 아직 그린 그림이 없습니다 | 보기 화면은 why와 함께 빈 상태를 보여 줍니다 |
| `comment_not_found` | 404 | 공간에 그런 의견이 없습니다 | 없음 | 이 의견은 서버에 없습니다 | 보기 화면은 그림을 다시 불러옵니다. 허브는 그것을 알리고 쓰기를 버립니다 |
| `discrepancy_not_found` | 404 | 부분에 그런 어긋남이 없습니다 | 없음 | 이 어긋남은 서버에 없습니다 | comment_not_found와 같습니다 |
| `proposal_not_found` | 404 | 공간에 그런 제안이 없습니다 | 없음 | 이 제안은 서버에 없습니다 | comment_not_found와 같습니다 |
| `edit_not_found` | 404 | 공간에 그런 편집이 없습니다 | 없음 | 이 반영은 서버에 없습니다 | comment_not_found와 같습니다 |
| `checkpoint_not_found` | 404 | 공간에 그런 확인 지점이 없습니다 | 없음 | 이 확인 지점은 서버에 없습니다 | 단계 현황은 다시 불러옵니다. 허브는 그것을 알리고, 에이전트는 그 기록을 쓰지 않습니다 |
| `entry_not_found` | 404 | 공간에 그 ID의 의견, 어긋남, 편집, 확인 지점이 없습니다 | 없음 | 이 항목은 서버에 없습니다 | 허브는 그것을 알리고 그 항목을 둡니다 |
| `method_not_allowed` | 405 | 경로가 그 메서드를 받지 않습니다. Allow가 받는 메서드를 적습니다 | 없음 | 여기서는 이 요청을 할 수 없습니다 | 허브는 자기 잘못으로 알립니다 |
| `older_snapshot` | 409 | 쥔 커밋의, 또는 쥔 커밋이 없는 프로젝트의 스냅샷이 저장된 것보다 일찍 찍혔습니다. stored_at이 저장된 것을 찍은 때를 말합니다 | `stored_at` | 서버에 더 새로운 스냅샷이 있습니다 | 허브는 새 스냅샷을 찍어 다시 보냅니다 |
| `commit_not_replaced` | 409 | 쥔 커밋을 대신한다고 적지 않은 다른 커밋의 스냅샷, 저장된 스냅샷에는 커밋이 있는데 커밋이 없는 스냅샷, 또는 다른 보내기에 앞질린 보내기입니다. held_commit이 쥔 커밋을 적습니다 | `held_commit` | 서버에 다른 커밋이 있습니다. 기본 브랜치를 가져와 다시 보내 주세요 | 에이전트는 가져와서 한 번 다시 보냅니다 |
| `too_many_projects` | 409 | 서버에 프로젝트가 30개 있고, 스냅샷은 새 프로젝트의 것입니다 | `limit` | 서버에 프로젝트가 30개 있습니다. 먼저 하나를 지워 주세요 | 허브가 그것을 알립니다 |
| `repository_mismatch` | 409 | 스냅샷의 저장소 주소가 공간이 묶인 주소가 아닙니다. bound가 그 주소를 적습니다 | `bound` | 이 프로젝트의 공간은 다른 저장소에 묶여 있습니다 | 허브는 두 주소를 적고, 지우기가 공간의 묶임을 푼다고 말합니다 |
| `comment_limit` | 409 | 공간에 의견이 2,000개 있습니다 | `limit` | 이 프로젝트는 의견을 더 담을 수 없습니다 | 보기 화면은 글을 간직하고 그렇다고 말합니다 |
| `reply_limit` | 409 | 의견에 답글이 200개 있습니다 | `limit` | 이 의견은 답글을 더 담을 수 없습니다. 새 의견을 남겨 주세요 | 보기 화면은 글을 간직하고 새 의견을 권합니다 |
| `proposal_limit` | 409 | 공간에 열린 제안이 500개 있습니다 | `limit` | 이 프로젝트는 열린 제안을 더 담을 수 없습니다 | 허브는 그것을 알리고, 에이전트는 단계별 원본이 이미 넘어선 제안을 철회합니다 |
| `reflection_limit` | 409 | 공간에 반영 대기가 500개 있습니다 | `limit` | 이 프로젝트는 반영 대기를 더 담을 수 없습니다 | 보기 화면은 그렇다고 말하고, 제안은 열린 채로 남습니다 |
| `space_full` | 409 | 쓰기가 공간의 글을 8 MiB 넘게 만듭니다 | `limit` | 이 프로젝트의 공간이 찼습니다 | 보기 화면은 글을 간직합니다. 허브는 그것을 알립니다 |
| `comment_closed` | 409 | 에이전트가 닫힌 의견에 썼습니다. 닫힌 의견은 사용자의 답글만 다시 엽니다 | 없음 | 이 의견은 닫혔습니다 | 허브는 그것을 알리고, 에이전트는 그 의견을 둡니다 |
| `proposal_not_open` | 409 | 제안을 이미 받았거나, 버렸거나, 철회했습니다. state가 어느 것인지 말합니다 | `state` | 이 제안은 더는 열려 있지 않습니다 | 보기 화면은 그 상태를 보여 줍니다 |
| `edit_state` | 409 | 보고나 버림이 편집의 상태에 맞지 않습니다. state가 그 상태를 말합니다 | `state` | 이 반영은 다른 상태에 있습니다 | 보기 화면은 다시 불러옵니다. 허브는 그 상태를 알립니다 |
| `pull_request_reported` | 409 | 보고된 다른 PR이 아직 그 반영이나 확인 지점을 붙들고 있습니다. pull_request가 그것을 적습니다 | `pull_request` | 이미 PR이 이것을 붙들고 있습니다 | 허브는 그 PR을 알리고, 에이전트는 그 항목을 둡니다 |
| `pull_request_mismatch` | 409 | 보고가 그 항목에 보고된 PR이 아닌 다른 PR을 적습니다. pull_request가 보고된 PR을 적습니다 | `pull_request` | 보고된 PR이 아닙니다 | 허브는 두 PR을 알립니다 |
| `claimed` | 409 | 다른 에이전트 세션이 그 항목을 맡았습니다. ends_at이 언제까지인지 말합니다 | `ends_at` | 다른 세션이 이것을 맡고 있습니다 | 허브는 맡음이 끝날 때까지 그 항목을 건너뜁니다 |
| `entry_closed` | 409 | 닫힌 항목을 맡으려 했습니다 | 없음 | 이 항목은 닫혔습니다 | 허브는 그것을 건너뜁니다 |
| `checkpoint_recorded` | 409 | 저장된 단계 기록이 그 확인 지점을 적으므로, 철회하면 기록된 결정이 바뀝니다 | 없음 | 이 확인 지점은 기록됐습니다. 이것을 바꾸는 것은 새 결정입니다 | 단계 현황은 그 기록을 보여 줍니다 |
| `checkpoint_withdrawn` | 409 | 확인 지점을 철회했으므로, 새 기록 PR이 그것을 쓸 수 없습니다 | 없음 | 이 확인 지점은 철회됐습니다 | 허브는 그것을 알리고, 에이전트는 기록을 쓰지 않습니다 |
| `write_id_reused` | 409 | 다른 요청이 그 쓰기 ID를 가졌습니다 | 없음 | 이것을 보내지 못했습니다. 다시 해 주세요 | 보기 화면은 새 ID를 만듭니다. 허브는 자기 잘못으로 알립니다 |
| `snapshot_too_large` | 413 | 스냅샷이 1 MiB보다 큽니다 | `limit` | 스냅샷이 서버가 받는 것보다 큽니다 | 허브가 그것을 알립니다. 허브 자신의 상한이 스냅샷을 그보다 작게 지킵니다 |
| `body_too_large` | 413 | 쓰기의 본문이 256 KiB보다 큽니다 | `limit` | 서버가 받는 것보다 큽니다 | 보기 화면과 허브가 그것을 알립니다 |
| `text_too_long` | 413 | 글이 그 상한보다 깁니다. field와 limit이 그것을 적습니다 | `field`, `limit` | 글이 너무 깁니다 | 보기 화면은 필드 옆에서 남은 글자 수를 셉니다. 허브는 그 필드를 알립니다 |
| `json_required` | 415 | application/json으로 보내지 않은 본문입니다 | 없음 | 이것을 보내지 못했습니다 | 허브는 자기 잘못으로 알립니다 |
| `internal` | 500 | 서버 안의 오류입니다. 그 로그에는 오류의 종류와 추적 ID만 있습니다 | 없음 | 문제가 생겼습니다. 다시 해 주세요 | 보기 화면은 가진 것을 간직하고 다시 보내자고 합니다. 허브는 그 쓰기를 보낼 편지함에 간직합니다 |

## 호환되지 않는 변경

허브의 [snapshot.md](../../plugins/corthex-nexus/skills/corthex-hub/references/snapshot.md)가 설명하는 1차와 견주어:

1. 거절은 `application/problem+json`으로 보내는 문제 세부 정보이고, 멤버가 더 있습니다. `error`를 그대로 두므로, 어느 JSON 응답이든 읽고 `error`를 보여 주는 0.1의 허브도 여전히 까닭을 보여 주며, 까닭의 말은 새로 씁니다.
2. 0.1의 허브는 0.2의 허브가 보낸 프로젝트를 보낼 수 없습니다: 저장된 스냅샷에는 커밋이 있는데 그 스냅샷은 커밋을 적지 않으므로, 서버가 `409` `commit_not_replaced`로 거절합니다. 그런 프로젝트를 다시 보내기 전에 모든 기기의 허브가 0.2로 옮겨 갑니다.
3. 0.2의 허브는 1차의 서버에 보내지 않습니다. 1차의 서버는 0.2의 스냅샷을 `400`으로 거절하므로, 허브는 쥔 커밋을 묻는 질문에서 멈춥니다. 1차의 서버는 그 질문에 `code`가 없는 `404`로 답합니다. 그래서 0.2의 서버를 허브보다 먼저 배포합니다.
4. `push`는 저장한 스냅샷을 보내지 않고 새 스냅샷을 찍으며(SPEC-111), `remove --dry-run`은 서버를 읽으므로 서비스 토큰이 필요합니다.
5. 지우기는 스냅샷과 함께 프로젝트의 공간을 지우고(SPEC-115), `GET /api/snapshots/{project}`는 그림 자료가 없는 0.2의 스냅샷을 돌려줍니다.
6. 페이지 자료는 0.2의 페이지가 읽는 `corthex-hub-page/0.2`이고, 다른 것은 그것을 읽지 않습니다.

확인 지점이 2026-11-03에 이것을 받아들였으므로, 0.2는 이대로 나갑니다. 서버가 먼저이고, 그다음 모든 기기의 허브입니다.

## 앞 단계의 변경

2026-11-03에 확인 지점을 통과하며 반영했습니다. 1, 2, 6은 기능 명세에, 3\~5와 7은 서버의 자료에 들어갔습니다.

1. SPEC-113은 어떤 응답도 캐시하면 안 된다고 말합니다. 보기 화면의 코드 파일은 캐시해도 됩니다: 프로젝트 자료가 없고, 이름마다 그 내용의 다이제스트가 있으며, 휴대폰에서 보기 화면이 빠르려면 그것을 간직해야 합니다(REQ-149).
2. SPEC-108은 맨 위의 `without a screen` 목록을 적습니다. 07단계 양식의 YAML은 화면의 목록이어서 키를 둘 자리가 없으므로, SQL의 `-- without a table:`처럼 그 목록은 주석 줄 `# without a screen:`입니다.
3. TBL-117에 `path`가 생겨, 간직한 쓰기의 시도마다 첫 시도가 간 곳으로 갑니다.
4. 05단계의 읽기는 그림의 열린 의견을 그 답글과 결정과 함께 줍니다. 그림의 응답은 열린 의견마다 그 답글 수와 마지막 답글을 주고 의견 자신의 읽기(API-114)가 그 모두를 주어, 그림의 응답이 작게 머뭅니다. 제안의 단계별 원본 글도 같습니다(API-115).
5. 05단계의 그림 자료는 핫스팟의 번호를 줍니다. 양식의 핫스팟 표에는 번호 열이 없으므로, `number`는 선택이고 글 첫머리의 번호에서 가져옵니다.
6. SPEC-116은 보기 화면에서 의견을 다시 여는 것을 사용자의 쓰기에 세고, 기능 명세의 06단계 메모는 그것을 요청에 적습니다: 그것은 닫힌 의견에 단 사용자의 답글이며(SPEC-127), 따로 된 요청이 없습니다.
7. 05단계의 상한에 쓰기 본문의 256 KiB가 더해집니다.

## 이 단계가 고른 것

1. 꼴이 다른 경로 값은 서버가 갖지 않은 값의 `404`를 받고 절대 `400`을 받지 않습니다. 1차가 프로젝트 이름에 그렇게 답하는 것과 같습니다: 모든 경로에는 그것이 가리키는 것에 대한 거절이 하나 있고, 경로의 꼴은 그 이상을 알려 주지 않습니다.
2. 꼴이 맞지 않는 입력은 1차처럼 모든 요청에서 `400`을 받고 절대 `422`를 받지 않습니다. 상한을 넘은 글은 SPEC-126이 말하는 대로 `413`을, 상한에 닿은 공간은 `409`를 받습니다. 요청은 제 꼴이고, 찬 것은 공간이기 때문입니다.
3. 결과가 이미 그렇게 된 쓰기는 아무것도 바꾸지 않고 `changed: false`로 성공합니다. 다른 결과가 닫은 쓰기는 그 상태와 함께 `409`로 거절합니다([바꾸는 것이 없는 응답](#바꾸는-것이-없는-응답)). 기능 명세가 적은 경우는 기능 명세가 정합니다: 닫힌 의견에 답했음을 표시하는 것은 아무것도 바꾸지 않고(SPEC-127), 다른 탭에서 버린 제안을 받는 것은 거절합니다(SPEC-131).
4. 서버는 자기 속도 제한을 두지 않습니다. Access 뒤에서 한 사용자와 그 에이전트를 Cloudflare의 한도 안에서 맡고, Cloudflare의 `429`를 받은 에이전트의 쓰기는 보낼 편지함에 간직합니다.
5. 쓰기 ID는 Idempotency-Key 초안의 헤더에 담습니다. 페이지와 허브가 모든 쓰기에 같은 방법으로 보내고 서버가 본문보다 먼저 읽게 하려는 것이며, [쓰기 ID](#쓰기-id)가 적은 세 가지가 다릅니다.
6. 어느 요청도 `401`을 적지 않습니다: Access가 Worker보다 먼저 그것에 답합니다. 로그인에 대한 Worker의 거절은 1차처럼 코드가 있는 `403`입니다.
7. 오류는 1차의 `error`를 그대로 둔 문제 세부 정보여서, 0.1의 허브도 여전히 까닭을 보여 줍니다.
8. 의견, 제안, 편집, 확인 지점 하나마다 자기 읽기가 있어, 그림, 단계 현황, 할 일의 목록이 작게 머뭅니다.
9. 허브의 명령은 두 번째 도구를 두지 않고 1차의 `hub.py`를 넓히며, MEMORY의 명령이 결과를 주듯 종료 코드 0\~3과 `--json`을 둡니다.
10. 계약은 MEMORY의 인터페이스 옆에 YAML, 곧 `nexus.openapi.yaml`로 둡니다: 허브는 JSON처럼 YAML도 읽고, MEMORY의 시험은 이 폴더의 JSON 파일에 `id`라는 필드가 있는지 검사하는데, OpenAPI 계약의 예시에는 그런 필드가 있습니다.
11. SQL과 YAML에 있는 그림 자료의 표지 `terms: none`, `without a table:`, `without a screen:`은 둘레의 코드처럼 모든 언어에서 영어입니다. DDD 보드의 표는 사람들이 쓰는 대로 영어와 한국어로 읽습니다.

## 돌린 검사

2026-11-02에 계약과 이 파일에 대해:

- openapi-spec-validator 0.7.1: 계약은 올바른 OpenAPI 3.1입니다.
- 저장소 밖에 두는, PyYAML과 jsonschema로 쓴 이 단계의 Python 검사: 모든 작업에 API ID, 그 SPEC ID, 상태가 있고, 단계의 표가 적는 응답마다 그것을 적거나 `omit`에 까닭과 함께 적으며, 모든 응답에 그 스키마가 받는 이름 붙은 예시가 있고, 모든 오류 예시의 코드가 같은 상태로 목록에 있으며, 모든 쓰기가 쓰기 ID를 받고 다른 요청이 가져간 ID에는 `409` `write_id_reused`로 답합니다. 문제 없음.
- Prism 5.16.0, `prism mock`: 계약이 그 32개 작업과 함께 불러와집니다. 큰따옴표 안의 쓰기 ID는 통과하고, 따옴표가 없는 것은 `400`을 받습니다.
- 그 모의 서버에 대한 Schemathesis 3.39.16, 검사 `not_a_server_error`, `status_code_conformance`, `content_type_conformance`, `response_schema_conformance`와 작업마다 예시 25개: 32개 작업이 모두 요청 858개에서 통과합니다. 도구의 두 버릇은 저장소 밖에 두는 훅으로 비켜 두었고, 실행마다 그것을 셉니다: 도구는 `CF_Authorization` 쿠키를 아무 글자로나 만드는데 Node의 HTTP 서버가 모의 서버가 보기 전에 그것을 맨 `400`으로 거절하므로, 훅이 쿠키에 출력할 수 있는 대신 값을 줍니다. 그리고 도구는 경로 값을 응답 예시의 같은 이름 멤버로, 이를테면 `{edit}`을 `edit` 객체로 채우므로, 훅이 매개변수 자신의 예시를 되돌려 놓습니다. 스냅샷의 큰 본문 때문에 그 상태 검사 `data_too_large`는 껐습니다.
- 모의 서버는 이것들 대부분을 설계상 통과하므로, 계약을 증명하는 것은 실제 서버뿐입니다: 11단계는 같은 도구를 사용자 자신의 서버가 아니라 Access 뒤의 개발 서버에 돌립니다.
- 이 파일들을 둔 채로 돌린 저장소의 검사: `python -m unittest discover -s tests`(시험 725개, 건너뜀 12개), 마켓플레이스와 그 세 플러그인의 `claude plugin validate --strict`, `node --test nexus/test/*.test.js`(시험 15개)가 통과합니다. 허브가 찍은 이 저장소의 스냅샷은 API-101\~API-150을 한 번씩 읽고 점검이 없으며, 이 파일과 영어 원문의 링크는 모두 이어집니다.

2026-11-03에 확인 지점의 변경을 넣은 뒤, 같은 도구로:

- 이 단계의 검사와 openapi-spec-validator: 문제 없음. 계약의 예시 72개가 모두 쓰이며, 그중에 페이지의 HTML 응답이 있습니다.
- Prism의 모의 서버는 요청의 `Accept`가 `text/html`을 적으면 API-101\~API-103에 그 코드의 말을 담은 페이지로 답하고, 아니면 문제 세부 정보로 답합니다.
- 도구가 OpenAPI 3.1 계약에 요구하는 `--experimental=openapi-3.1`을 붙인 Schemathesis: 32개 작업이 모두 요청 858개에서 통과하고, 그중 Pages 아래의 네 작업, 곧 세 페이지와 보기 화면의 코드는 요청 103개에서 통과합니다. 세 번째 버릇도 같은 방법으로 비켜 두었습니다: 도구는 서비스 토큰의 두 헤더 `CF-Access-Client-Id`와 `CF-Access-Client-Secret`을 아무 글자로나 만드는데, Node의 HTTP 서버가 이것도 맨 `400`으로 거절하므로 훅이 저마다 출력할 수 있는 대신 값을 줍니다.
- 저장소의 검사가 통과하며, 이제 시험은 727개(건너뜀 12개)입니다. 허브가 찍은 이 저장소의 스냅샷은 항목 996개를 읽고 점검이 없습니다.

## 확인할 것

2026-11-03 11:39(KST)에 03\~05단계, 07·08단계와 함께 통과했습니다: 관리자가 프로젝트 스레드의 결정 카드에서 모든 추천을 골라(‘모두 추천대로’), 요청, 명령, 형식이 08단계의 변경과 함께 쓴 대로 섭니다. 로그인(3)은 그 시험 때까지 열려 있습니다. 확인 지점이 다룬 것:

1. [호환되지 않는 변경](#호환되지-않는-변경), 특히 한 기기가 0.2로 보낸 뒤에는 모든 기기의 허브가 0.2로 옮겨 가야 한다는 것과 서버를 먼저 배포한다는 것.
2. [앞 단계의 변경](#앞-단계의-변경), 특히 보기 화면 코드의 캐시(1)와 `# without a screen:` 줄(2).
3. 실제 Access 설정에서 시험할 때까지 열린 채로 두는 로그인([로그인](#로그인)). 시험은 11단계가 요청을 만들기 전에 합니다.
4. 초안의 헤더에 담는 쓰기 ID와 그 세 가지 차이([쓰기 ID](#쓰기-id)), 그리고 바꾸는 것이 없는 응답(고른 것 3).
5. 단계 스킬이 에이전트에게 돌리라고 할 허브의 명령 18개와 그 이름([허브의 명령](#허브의-명령)).

## 다음 단계를 위한 메모

### 07·08단계: 화면

- 화면마다의 요청: 허브 페이지는 API-101; 그림 보기는 불러오기에 API-102와 API-104, 다시 읽기에 API-111, 의견이나 제안을 열기에 API-114와 API-115, 그림이 더는 늘어놓지 않는 닫히거나 버려진 반영을 읽어 제안의 패널에 그 PR을 보이기에 API-116, 쓰기에 API-118\~API-120, API-124, API-125, API-127; 단계 현황은 불러오기에 API-103과 API-104, 다시 읽기에 API-112, 쓰기에 API-128과 API-129.
- 오류가 이끄는 상태: `why`가 있는 `picture_not_found`는 빈 상태; `access_missing`, `access_other_app`, `no_kind`, `opaqueredirect` 응답은 권한이나 끝난 로그인; `cross_site`는 서버 자신의 주소를 권하는 오류; `comment_limit`, `reply_limit`, `space_full`, `text_too_long`은 글을 간직함; `proposal_not_open`, `edit_state`, `checkpoint_recorded`는 낡은 상태이며 보기 화면이 다시 읽습니다. 보기 화면은 보내지 못한 글을 그 쓰기 ID와 함께 간직합니다(SPEC-126).
- [오류 코드](#오류-코드)의 말마다 영어와 한국어로 최종 문구를 정합니다.

### 10단계: 작업 분해

- 서버가 먼저입니다: store.js의 변환, 그다음 계약의 순서대로 요청을 만듭니다. 쥔 커밋이 있는 보내기와 지우기, 읽기, 논의, 편집, 맡음이 있는 단계 진행 순입니다. 허브가 뒤따릅니다: 그림 자료, 단계 기록, 설정이 있는 스냅샷 0.2, `status`, `push`, 그다음 보낼 편지함이 있는 쓰기. 보기 화면이 마지막입니다.
- 릴리스는 이 파일의 형식과 규칙을 허브의 [snapshot.md](../../plugins/corthex-nexus/skills/corthex-hub/references/snapshot.md)와 [reading.md](../../plugins/corthex-nexus/skills/corthex-hub/references/reading.md)로, `parts`와 `ask_before`를 핵심 플러그인의 [project.md](../../plugins/corthex/skills/corthex/references/project.md)로 옮기며, 허브의 명령을 돌리는 단계 스킬의 절차도 함께 옮깁니다.

### 11단계: 개발

- 실제 Access 설정에서 두 가지 로그인을 시험하는 것이 먼저이며, 그것이 [로그인](#로그인)의 열린 질문을 닫습니다.
- 계약 시험은 [돌린 검사](#돌린-검사)의 훅을 저장소에 두고 Access 뒤의 개발 Worker에 Schemathesis를 돌립니다. 서버를 만들기 전에는 Prism의 모의 서버가 보기 화면의 작업을 맡습니다.
- 부분들을 함께 묶는 시험: 서버의 오류 코드와 계약의 목록, 허브의 요청 이름과 계약의 `OutboxFile`, 허브가 지닌 기본 `ask_before` 목록의 사본과 핵심 플러그인의 예시 프로필, 그리고 [어느 거절이 먼저인지](#어느-거절이-먼저인지)의 거절 순서.

### 12단계: QA

- 요청마다 응답마다 그 이름 붙은 예시로 `API-118#409`처럼 적는 시험 사례 하나, 그리고 명령마다 결과마다 Linux, macOS, Windows에서 하나씩.
- 위의 경우의 수: 두 번, 그리고 7일 뒤에 다시 보낸 쓰기, 다른 요청의 쓰기 ID, 한 항목에 두 세션, 다른 보내기에 앞질린 보내기, 0.2의 보내기 뒤의 0.1 허브, 보기 화면에서 끝나는 로그인, 그리고 네트워크 없이, 토큰 없이, 7일 뒤의 보낼 편지함.
