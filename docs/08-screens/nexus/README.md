# NEXUS: screen states

[한국어](README.ko.md)

Stage 08 of CORTHEX's own project, for NEXUS 0.2: one definition for each of the nine screens of the [sitemap](../../07-sitemap/nexus.md), with the data that it shows and the request that each piece comes from, its actions with their results and failures, and every state with the responses that lead to it; and in this file the rules that hold on every screen, the final words of the messages, and the [wireframes](wireframes.html), drawn from the definitions. Status: draft of 2026-11-03, written while the memory plugin is being built, as the maintainer chose on 2026-11-02, and on the recommendations of the user flows, the functional spec, the server's data, the interfaces and the sitemap, whose checkpoint is still open. The maintainer checks it together with them. When a file and its Korean translation differ, the English file is the source.

Inputs: the sitemap in [docs/07-sitemap/nexus.yaml](../../07-sitemap/nexus.yaml) (SCR-101 to SCR-109), with its [notes for stage 08](../../07-sitemap/nexus.md#stage-08-screen-states); the functional spec in [docs/04-functional-spec/nexus.md](../../04-functional-spec/nexus.md), above all SPEC-119, SPEC-122 to SPEC-127, SPEC-131 to SPEC-134, SPEC-138 and SPEC-139 and its [notes for stages 07 and 08](../../04-functional-spec/nexus.md#stages-07-and-08-screens); the interfaces in [docs/06-api/nexus.md](../../06-api/nexus.md) and the contract [nexus.openapi.yaml](../../06-api/nexus.openapi.yaml), whose responses and [error codes](../../06-api/nexus.md#error-codes) the states follow, with the [notes for stages 07 and 08](../../06-api/nexus.md#stages-07-and-08-screens); the server's data in [docs/05-erd/nexus.md](../../05-erd/nexus.md), for the marks that come from it; the user flows that run in a browser, FL-105 to FL-107, FL-109, FL-110, FL-113 and FL-115, in [docs/03-user-flow/nexus/](../../03-user-flow/nexus/README.md); and phase 1's hub page as it runs, [hub.html](../../../plugins/corthex-nexus/skills/corthex-hub/assets/hub.html), whose states the hub page and its views keep. The memory plugin has no screens, so this stage has no file for it.

The stage's default human view is grayscale wireframes drawn from the definitions. Here they are one page, [wireframes.html](wireframes.html), with a frame for each state at 320 and 1440 pixels, and people look at it as a private published page whose link is in the project's records, since the repository is public. The definitions are read in the Korean copy in the project's Notion records, with the tables as databases. `.corthex/project.json` records the choice.

## The screens

- [SCR-101 Hub page](SCR-101-hub-page.md), `/`: normal, empty, stale, error and permission.
- [SCR-102 Search results](SCR-102-search-results.md), `/#q={words}`: normal and empty.
- [SCR-103 Trace view](SCR-103-trace-view.md), `/#p={project}&id={id}`: normal and error.
- [SCR-104 Stage detail](SCR-104-stage-detail.md), `/#p={project}&s={stage}`: normal, empty, stale and error.
- [SCR-105 Picture view](SCR-105-picture-view.md), `/pictures/{project}/{part}/{stage}`: loading, normal, large, empty, stale, error, code-failed and permission.
- [SCR-106 Item](SCR-106-item.md), `#item={id}`: normal, empty, loading, error, permission and gone.
- [SCR-107 Comment](SCR-107-comment.md), `#comment={comment}`: loading, normal, stale, error, permission and gone.
- [SCR-108 Proposal](SCR-108-proposal.md), `#proposal={proposal}`: loading, normal, stale, error, permission and gone.
- [SCR-109 Stage overview](SCR-109-stage-overview.md), `/overview/{project}/{part}/{stage}`: loading, normal, empty, stale, error and permission.

## How to read a definition

- **Purpose**: one sentence, from the flows that pass through the screen, with their FL IDs. Then the screen's path, who can see it, and whether it was built in phase 1 or is new in NEXUS 0.2.
- **Data**: what the screen shows and where each piece comes from: a request of the contract by its API ID, the page's own data, the page's address or the browser's storage.
- **Actions**: each with its result and its failure, which names the state that the failure leads to.
- **States**: each state's ID, written as `SCR-105#empty`, what the user sees and can do, and the responses that lead to it, written as `API-111#404`, with the error codes that decide it in brackets. Every response that the contract lists for a request of the screen leads to a state, and every code that the contract gives for that response is named. Under the table, the states of the stage that do not apply, with why.
- **Kinds of cases**: the 12 kinds that stages 04, 06 and 12 use, each with what the screen shows, or why it does not reach the screen.
- **Layout**: the screen's regions at 320 and 1440 pixels, the narrowest and widest widths that NEXUS supports (REQ-101, REQ-146), which the wireframes draw.

## Every screen

1. **Text only.** The projects' text, the comments, replies, reasons and stage source text show only as text: nothing in them is read as markup or runs (REQ-098, REQ-148). Long text wraps, and a long word or ID breaks rather than widening the page, so nothing scrolls the page sideways at any width from 320 to 1440 pixels (REQ-101, REQ-146). A picture larger than its frame moves inside the frame, and a proposal's stage source text scrolls inside its own box.
2. **Language and theme.** Every screen speaks the language of its page's data, `lang`, which comes from the server's `NEXUS_LANGUAGE` or, on a device, from the profile, English or Korean, and follows the system's light or dark mode (REQ-099, REQ-100, REQ-150). Times show in the browser's time zone, as phase 1 shows them.
3. **Messages.** A refusal or an error shows the message of its code from [Messages](#messages), in the page's language, never the reply's `detail`, and under it, in smaller text, "Trace ID {traceId}", which the server's log holds too ([choice 4](#choices-this-stage-made)).
4. **Writes.** A write's button is disabled while its request runs and says "Sending…". The view makes one write ID, an `nw_` ID, for each write and sends it with each try of that write, so that a try after a lost reply leaves one result (SPEC-126); after `write_id_reused`, the next try has a new ID. Its requests go only to the server, as JSON, with `redirect: "manual"`.
5. **Unsent text.** The text of a comment or a reply, up to 4,000 characters, and a checkpoint's words, up to 2,000, stay in their box and in the browser's storage for that picture and item, that comment, or that part and stage, with the write ID, until the server has taken them; after a reload they come back (SPEC-126). From 90 per cent of its limit the box shows how many characters are left, and it does not send past the limit. A comment or a reply that is empty or only spaces is not sent; a checkpoint's words may stay empty: words that are empty or only spaces are left out of the request, and the checkpoint passes without words (SPEC-139). Where the browser keeps no storage, as in some private windows, the text stays in the page only.
6. **Reading again.** After a write, the view reads its data again, the picture (API-111) or the overview (API-112), and an open panel its comment (API-114) or its proposal (API-115). Meanwhile "Updating…" shows, and the screen stays usable. A newer picture than the one drawn is offered, not drawn under the user (SCR-105#stale). A reading that fails leaves what the screen shows, with "Could not update. What you see may be out of date." and Try again.
7. **Sign-in.** On the server every page and request is behind Cloudflare Access, whose login page and refusals are its own, outside the sitemap. When a sign-in expires while a view is open, a request gets Access's redirect, which the view sees as an `opaqueredirect` reply, or a `401`. The view then says that the sign-in expired, keeps what the user wrote and offers Sign in again, which loads the page again through Access's login and comes back to the same address, with its panel.
8. **Connection.** No network, no answer within 30 seconds, or a `429` or `503` from Cloudflare: an error with its message from [Messages](#messages) and Try again, while the rest of the screen still works and what the user wrote is kept.
9. **Page refusals.** The three pages, the hub page (API-101), the picture view (API-102) and the stage overview (API-103), answer a browser's request that they refuse or fail as a small HTML page of one message in the server's language, with the trace ID, Load again and a link to the hub page ([change 1](#changes-to-earlier-stages)). A view's own data holds Problem Details in `problem`.
10. **Panels and addresses.** The item, comment and proposal panels open from their address after `#`, `item=`, `comment=` or `proposal=`, at once and on a phone too. A part that no item holds opens the item panel without an address of its own ([choice 12](#choices-this-stage-made)). The focus moves to the panel's heading; Escape, Close and the browser's back button close the panel and leave the picture's address. The hub page keeps phase 1's addresses, `q`, and `p` with `id` or `s`.
11. **The same for everyone.** A screen shows the same to everyone whom it shows, the user and anyone else whom Access lets in. What someone may do follows the requests' sign-ins: accepting or dismissing a proposal, dismissing a reflection and passing or withdrawing a checkpoint need a person's own sign-in (API-124, API-125, API-127 to API-129), and a refusal shows its message. No screen shows an email address, a name or any other part of an identity: an entry shows its author's kind, "User" or "Agent" (REQ-163, [choice 9](#choices-this-stage-made)).
12. **Lists and limits.** A list that a read caps shows how many it holds of its total, such as "50 of 73"; the stage overview lists 50 of each and links the picture view, which lists 500. Counts over 999 show as `999+` (SPEC-123).

## Responses and states

The stage's defaults, as NEXUS's requests answer. Each definition names the responses of its own requests.

| Response | State | What the user sees |
| --- | --- | --- |
| `200` or `201` with data | normal | The data; after a write, its result and the data read again |
| `200` with empty lists, or the problem `picture_not_found` | empty | What will appear and how it gets there |
| `200` with `changed: false` | stale | That it was done already, in another tab or by the agent, with the data read again |
| `400` `invalid_request` | error | The message by the field that `field` names, with the input kept |
| `401`, or Access's redirect as an `opaqueredirect` reply | permission | The sign-in expired: Sign in again, with the input kept (rule 7) |
| `403` `access_missing`, `access_other_app`, `user_only` or `no_kind` | permission | Why, from the code's message, and a way back, with the input kept |
| `403` `cross_site` | error | The message, with a link to the page at the server's own address |
| `404` for the project, its space, the part or the stage | error | The code's message and a link to the hub page |
| `404` for an entry: a comment, a discrepancy, a proposal, a reflection or a checkpoint | gone, on a panel, or error | That it is not on the server; the view reads again |
| `409` for a state: `proposal_not_open`, `edit_state` or `checkpoint_recorded` | stale | What it is now, with the data read again |
| `409` for a limit: `comment_limit`, `reply_limit`, `reflection_limit` or `space_full` | error | The limit, with the text kept; for `reply_limit`, a new comment offered |
| `409` `write_id_reused` | error | Try again, which makes a new write ID |
| `413` `text_too_long` or `body_too_large` | error | The limit by the box, with the text kept |
| `415`, `500` and other errors | error | The message and Try again, with what the screen holds kept |
| `429` or `503` from Cloudflare, no network, or no answer in 30 seconds | error | The message and Try again (rule 8) |

Where NEXUS differs from the stage's defaults: a `401` is Access's, not the server's, and only an expired sign-in brings it to a view; a `404` for an entry leads to a panel's own state, `gone`; and a `409` for a limit is an error that keeps the text, since the request was in its form and the space is what is full.

## Messages

The final words of the messages of stage 06's [error codes](../../06-api/nexus.md#error-codes) that the screens show, and of the screens' own messages. `{limit}`, `{state}` and the other names in braces are filled from the reply or the data. Korean is written in the polite form, as phase 1's hub page is.

### Error codes

| Code | Status | English | Korean |
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
| `picture_not_found`, `why` `not-drawn` | 404 | No picture is drawn yet for this stage and part. It appears after a push that holds the stage's document. | 이 단계와 부분의 그림은 아직 없습니다. 단계 문서를 담은 스냅샷을 올리면 나타납니다. |
| `picture_not_found`, `why` `size` | 404 | This picture was left out: its source is larger than a snapshot may hold. | 원본이 스냅샷에 담을 수 있는 크기보다 커서 이 그림은 빠졌습니다. |
| `picture_not_found`, `why` `other-repository` | 404 | This picture was left out: its source is in another repository. | 원본이 다른 저장소에 있어서 이 그림은 빠졌습니다. |
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

The states in `{state}`: for a proposal, accepted, dismissed or withdrawn (받음, 버림, 철회됨); for a reflection, not yet reflected, in review, waiting for the user, reflected or dismissed (반영 전, 검토 중, 사용자를 기다림, 반영됨, 버림), for `pending`, `in-review`, `needs-user`, `closed` and `dismissed`.

No screen shows the other codes. `agent_only`, `claimed` and `comment_closed` refuse only the agent's writes, and `invalid_snapshot`, `clock_ahead`, `unknown_item`, `older_snapshot`, `commit_not_replaced`, `too_many_projects`, `repository_mismatch`, `proposal_limit`, `pull_request_reported`, `pull_request_mismatch`, `entry_closed`, `checkpoint_withdrawn`, `snapshot_too_large` and `entry_not_found` reach only the hub, which shows `detail` in the session; their messages stay as stage 06 drafted them.

### The screens' own messages

| Message | Where | English | Korean |
| --- | --- | --- | --- |
| Sign-in expired | Every view (rule 7) | Your sign-in has expired. Sign in again: what you wrote stays here. | 로그인이 끝났습니다. 다시 로그인해 주세요. 쓴 글은 여기 남아 있습니다. |
| No connection | Every view (rule 8) | No connection to the server. Check the network, then try again. | 서버에 연결되지 않습니다. 네트워크를 확인한 뒤 다시 시도해 주세요. |
| No answer in time | Every view (rule 8) | The server did not answer in time. Try again. | 서버가 제때 답하지 않았습니다. 다시 시도해 주세요. |
| Busy | Every view (rule 8) | The server is busy. Wait a moment, then try again. | 서버가 바쁩니다. 잠시 뒤 다시 시도해 주세요. |
| Trace ID | Under every error (rule 3) | Trace ID {traceId} | 추적 ID {traceId} |
| Updating | Every view (rule 6) | Updating… | 새로 읽는 중… |
| Could not update | Every view (rule 6) | Could not update. What you see may be out of date. | 새로 읽지 못했습니다. 보이는 내용이 최신이 아닐 수 있습니다. |
| Sending | Every write (rule 4) | Sending… | 보내는 중… |
| Characters left | Every box (rule 5) | {n} characters left | {n}자 남음 |
| Page data unreadable | SCR-101 | This page's data could not be read. Load the page again. On a device: Build the hub again. | 이 페이지의 데이터를 읽지 못했습니다. 페이지를 다시 불러와 주세요. 기기에서는 허브를 다시 만들어 주세요. |
| Empty server | SCR-101 | Nothing has been pushed to this server yet. It shows each pushed project's stages, checks and pictures. To push a project: register it with the corthex skill; list it in `nexus.push` with this server's address in `nexus.url`; set the service token's two environment variables, `CORTHEX_NEXUS_CLIENT_ID` and `CORTHEX_NEXUS_CLIENT_SECRET`; then have the agent show a dry run and push. | 아직 이 서버에 올라온 프로젝트가 없습니다. 이 서버는 올라온 프로젝트마다 단계, 점검, 그림을 보여 줍니다. 프로젝트를 올리려면 corthex 스킬로 등록하고, `nexus.push`에 넣고 `nexus.url`에 이 서버의 주소를 적고, 서비스 토큰의 환경 변수 두 개 `CORTHEX_NEXUS_CLIENT_ID`와 `CORTHEX_NEXUS_CLIENT_SECRET`을 설정한 뒤, 에이전트에게 미리 보기를 보이고 올려 달라고 하세요. |
| On the server | SCR-101, SCR-104, on a device | The pictures, comments and stage overviews are on the NEXUS server. | 그림, 의견, 단계 현황은 NEXUS 서버에 있습니다. |
| Project not on the page | SCR-103, SCR-104 | This project is not on this page. | 이 프로젝트는 이 페이지에 없습니다. |
| Not a stage | SCR-104 | This stage is not one of the 13. | 13단계에 없는 단계입니다. |
| Loading the view | SCR-105, before its code runs | Loading the picture view. If it does not appear, load the page again. | 그림 보기를 불러오는 중입니다. 나타나지 않으면 페이지를 다시 불러와 주세요. |
| Drawing | SCR-105 | Drawing the picture… | 그림을 그리는 중… |
| Large | SCR-105 | This picture is large ({n} elements), so drawing it may take longer. | 이 그림은 요소가 {n}개로 커서 그리는 데 시간이 더 걸릴 수 있습니다. |
| Not current | SCR-105 | This picture shows commit {commit}: its newest source is larger than a snapshot may hold. Or: its newest source is gone from the repository. Or: its newest source is in another repository. | 이 그림은 커밋 {commit}의 그림입니다. 최신 원본이 스냅샷에 담을 수 있는 크기보다 큽니다. 또는: 최신 원본이 저장소에서 사라졌습니다. 또는: 최신 원본이 다른 저장소에 있습니다. |
| Not current, by a link | SCR-104, SCR-109 | Not current: its newest source is larger than a snapshot may hold. Or: is gone from the repository. Or: is in another repository. | 최신 아님: 최신 원본이 스냅샷에 담을 수 있는 크기보다 큼. 또는: 저장소에서 사라짐. 또는: 다른 저장소에 있음. |
| Newer version | SCR-105 | A newer version of this picture is on the server. Show it | 서버에 이 그림의 새 판이 있습니다. 보기 |
| Code failed | SCR-105 | The picture could not be drawn here, so its items are listed instead. | 여기서는 그림을 그리지 못해 항목을 목록으로 보여 드립니다. |
| Apart | SCR-105 | Apart: comments whose item is gone ({n}) | 따로: 항목이 없어진 의견 ({n}) |
| Waits | SCR-105, SCR-106 | Waits for a current picture | 최신 그림을 기다림 |
| Accepted | SCR-105, SCR-108 | Accepted, not yet reflected | 받음, 아직 반영 전 |
| No comments | SCR-106 | No comments on {id} yet. | {id}에는 아직 의견이 없습니다. |
| Not in the picture | SCR-106 | {id} is not in this picture. | {id} 항목은 이 그림에 없습니다. |
| No ID | SCR-106 | No ID: comments on it are kept on the picture, with its name as the quote. | ID가 없어, 의견은 이 이름을 인용으로 붙여 그림에 남습니다. |
| A comment's state | SCR-107 | Waiting for the agent. Waiting for the user. Settled by the user, waiting for the agent's record. A proposal was dismissed. Closed as answered. Closed with a decision. | 에이전트를 기다림. 사용자를 기다림. 사용자가 정함, 에이전트의 기록을 기다림. 제안을 버림. 답이 나서 닫힘. 결정으로 닫힘. |
| No replies | SCR-107 | No replies yet. | 아직 답글이 없습니다. |
| Settles it | SCR-107 | This settles it | 이것으로 정함 |
| Open again | SCR-107 | Reply and open again | 답글 달고 다시 열기 |
| Already closed | SCR-107 | This comment was already closed. | 이 의견은 이미 닫혀 있었습니다. |
| Could not load | SCR-107, SCR-108 | Could not load this comment. Or: Could not load this proposal. | 이 의견을 불러오지 못했습니다. 또는: 이 제안을 불러오지 못했습니다. |
| A reflection's state | SCR-108 | Accepted, not yet reflected. In review: {pull request}. The change no longer fits the stage source; the agent asks you on its comment. Reflected by {pull request}. Reflected: already in the stage source at commit {commit}. The reflection was dismissed. | 받음, 아직 반영 전. 검토 중: {pull request}. 단계 원본이 바뀌어 이 변경이 더는 맞지 않습니다. 에이전트가 의견에서 묻습니다. {pull request}로 반영됨. 반영됨: 커밋 {commit}의 단계 원본에 이미 있음. 반영을 버렸습니다. |
| Dismissed, withdrawn | SCR-108 | Dismissed on {date}; its comment stays open. Withdrawn by the agent on {date}. | {date}에 버림. 의견은 열린 채로 남습니다. {date}에 에이전트가 철회함. |
| Already dismissed | SCR-108 | The reflection was already dismissed. | 이 반영은 이미 버려져 있었습니다. |
| Earlier picture | SCR-108 | Made on the picture of commit {commit}; the stage source may have changed since. | 커밋 {commit}의 그림에서 낸 제안입니다. 그 뒤 단계 원본이 바뀌었을 수 있습니다. |
| Loading the overview | SCR-109, before its code runs | Loading the stage overview. If it does not appear, load the page again. | 단계 현황을 불러오는 중입니다. 나타나지 않으면 페이지를 다시 불러와 주세요. |
| Nothing left | SCR-109 | Nothing is left in this stage. | 이 단계에 남은 것이 없습니다. |
| Not read | SCR-109 | This project does not read this stage: {why}. You can still pass its checkpoint. | 이 프로젝트는 이 단계를 읽지 않습니다: {why}. 그래도 확인 지점은 통과시킬 수 있습니다. |
| Waiting for its record | SCR-101, SCR-104, SCR-109 | Passed in NEXUS on {date}, waiting for its record | {date}에 NEXUS에서 통과, 기록을 기다림 |
| Pass again | SCR-109 | Pass again | 다시 통과 |
| Withdrawn, recorded | SCR-101, SCR-104, SCR-109 | The record names a checkpoint that was withdrawn in NEXUS. The agent corrects the record. | 기록에 NEXUS에서 철회한 확인 지점이 적혀 있습니다. 에이전트가 기록을 고칩니다. |
| Already withdrawn | SCR-109 | This checkpoint was already withdrawn. | 이 확인 지점은 이미 철회되어 있었습니다. |
| Withdrawn | SCR-109 | Withdrawn on {date} | {date}에 철회함 |
| Not opened | SCR-109 | {n} discrepancies could not be opened, since the space holds 1,000 open ones. | 공간에 열린 어긋남이 1,000개라 {n}개를 열지 못했습니다. |

The hub page and its views keep phase 1's other messages, such as "No projects yet. Register a project with the corthex skill, then build the hub again." and "Nothing matches “{q}”.", in English and Korean as hub.html holds them.

### Words the mockups added

The mockups of stage 09, in [direction A](../../09-mockup/nexus/README.md#the-choice), needed these words, which stage 08 had not written. They were added on 2026-11-03 with the mockups and can change at the checkpoint. A word between `·` marks is a label of its own.

| Words | Where | English | Korean |
| --- | --- | --- | --- |
| Open counts | SCR-101, on the server | 1 open comment · {n} open comments · 1 open proposal · {n} open proposals · 1 open discrepancy · {n} open discrepancies | 열린 의견 {n} · 열린 제안 {n} · 열린 어긋남 {n} |
| Picture mark | SCR-101, on the server: after the stages' legend, and in the name of a stage that has a picture | picture in NEXUS | NEXUS에 그림 |
| Waiting checkpoints | SCR-101, on the server | Waiting for their records ({n}) | 기록을 기다리는 확인 지점 ({n}) |
| In NEXUS | SCR-101#stale, on the server: the heading of a card's rows when a picture is not current or a record names a withdrawn checkpoint | In NEXUS | NEXUS에서 |
| Asks first | SCR-101, on the server (SPEC-125) | Asks first ({source}) · {list} and {n} more in the settings · Not asked in this project: {list} · Anything that cannot be undone is asked in any case. · Only what cannot be undone is asked. | 먼저 묻는 일 ({source}) · {list} 외 {n}개는 설정에 있음 · 이 프로젝트에서 묻지 않는 일: {list} · 되돌릴 수 없는 일은 어쨌든 묻습니다. · 되돌릴 수 없는 일만 묻습니다. |
| The list's source | SCR-101, in Asks first | the project's list · the profile's list · the default list | 프로젝트의 목록 · 프로필의 목록 · 기본 목록 |
| All projects | SCR-103, SCR-104: the link to the projects | All projects | 모든 프로젝트 |
| Zoom | SCR-105: the names of the zoom buttons | Zoom out · Zoom in · Whole picture | 축소 · 확대 · 그림 전체 |
| Merged marks | SCR-105: the name of a context's marks, merged at the whole picture | 1 mark in {context}: zoom in · {n} marks in {context}: zoom in | {context}의 표시 {n}개: 확대하기 |
| Legend | SCR-105: the legend's name | Legend of the marks | 표시의 설명 |
| List of items | SCR-105 | With marks ({n}) · The rest ({n}) · Part without an ID | 표시가 있는 것 ({n}) · 나머지 ({n}) · ID 없는 부분 |
| Item panel | SCR-106 | Proposals ({n}) · Comments ({n}) · Closed ({n}) · 1 reply · {n} replies | 제안 ({n}) · 의견 ({n}) · 닫힌 의견 ({n}) · 답글 {n}개 |
| Back to the picture | SCR-106, SCR-107 and SCR-108, when their item, comment or proposal is gone | Back to the picture | 그림으로 돌아가기 |
| Loading the replies | SCR-107#loading, for screen readers | Loading the replies… | 답글을 불러오는 중… |
| New reply | SCR-107#stale: a reply that came after the panel opened | New | 새 답글 |
| Proposal panel | SCR-108 | Change · Reason · Stage source text · Made on commit {commit} · Answers | 변경 · 까닭 · 단계 원본의 글 · 커밋 {commit}에서 낸 제안 · 답하는 의견 |
| Loading the source text | SCR-108#loading, for screen readers | Loading the stage source text… | 단계 원본의 글을 불러오는 중… |
| Overview's headings | SCR-109 | Recorded state · Updated {time} · Discrepancies ({n}) · Comments ({n}) · Pending reflections ({n}) · Words (optional) | 기록된 상태 · 갱신 {time} · 어긋남 ({n}) · 의견 ({n}) · 반영 대기 ({n}) · 남길 말 (선택) |

## Choices this stage made

The earlier stages left these to stage 08. Each can change at the checkpoint.

1. One file for each screen, named by its ID and a short name, in a folder for NEXUS, with this file for the rules of every screen and the messages, as stage 03's flows are kept; the stage's default is one file for each screen, named by its ID alone, in `docs/08-screens/`.
2. Three states of the screens' own, besides the stage's six: `large` and `code-failed` on the picture view, which SPEC-119 names, and `gone` on the three panels, for an item, a comment or a proposal that the address or the panel names and that is no longer there, which the stage's defaults would call an error.
3. The panels open beside the picture, 400 pixels wide, from a width of 1,024 pixels, the width from which phase ② edits (SPEC-134), and below it as a sheet from the bottom, up to 85 per cent of the height, so that the picture stays in sight on a phone.
4. Every error shows its trace ID in smaller text under its message, so that the user can report it and the server's log can be searched for it, since the message never shows `detail`.
5. A request of a view has 30 seconds, as a request of the hub (stage 06's [limits](../../06-api/nexus.md#limits)); then the view says that the server did not answer in time.
6. A newer picture, after a write or a reading again, is offered with Show it rather than drawn under the user, so that the item that the user is reading does not move away.
7. An address after `#` whose project or stage the hub page does not hold shows a note with a link to the projects, where phase 1 shows nothing.
8. A hub page whose data cannot be read says so, where phase 1 shows the empty page, "No projects yet", which would send the user to register projects that exist.
9. An entry's author shows as "User" or "Agent", the kinds that the server keeps (REQ-163), rather than "You", since anyone whom Access lets in sees the same screen.
10. The messages say what happened and what the user can do, in the page's language and in the form of phase 1's, English sentences and Korean in the polite form. The codes that only the hub sees keep stage 06's drafts.
11. The human view: the wireframes on one page, published as a private page whose link is in the project's records, as the repository is public, and the definitions in the Korean copy in Notion with the tables as databases.
12. A part that no item holds, such as a table or a screen drawn without an ID, opens the item panel for the picture itself, with the part's name as its heading and as the quote of the comments left there (SPEC-126). No ID names the part, so this panel has no address of its own: a reload shows the picture, the part's mark opens the panel again, and its unsent text comes back once the part is selected.

## Changes to earlier stages

They wait for the checkpoint together with this stage, and the earlier files change once it is passed, apart from the last, which corrects two slips of stage 07.

1. Stage 06: the three pages, API-101 to API-103, answer a refusal or an error as `text/html` when the request accepts it, as a browser's does: a small page of one message in the server's language, with the trace ID, Load again and a link to the hub page, under the policy `default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`, with the same status. Today the contract gives them only `application/problem+json`, which a browser shows as raw text. Other clients keep Problem Details, and the `/api/` requests are unchanged; the pages get responses of their own in the contract, with both types.
2. Stage 06's [Reads](../../06-api/nexus.md#reads) say that the picture view of a project without a space shows `picture_not_found`, while the contract answers that page with `404` `space_not_found`. The sentence follows the contract, and this stage words that code's message so that it also fits a checkpoint's pass (API-128).
3. Stage 06's notes for stages 07 and 08 list each screen's requests. The stage overview loads its code from API-104 too, as its policy says, and the proposal's panel reads its reflection with API-116 once the picture no longer lists it, closed or dismissed, to show its pull request.
4. Stage 07's notes for stage 08 named REQ-099, the hub page's language, for the widths, which are REQ-101 and REQ-146; and its account of stage 06's examples named the template's two example screen IDs, which the hub then reported as mentioned but not defined. This change corrects both there, which changes no rule.

## Checks run

On 2026-11-03, on the nine definitions, this file, their Korean translations and the wireframes:

- The stage's checks, by a script kept outside the repository: every piece of data names its request or where it comes from; every action has a result and a failure; every response that the contract lists for each request that a screen calls, 97 in all, leads to a state, and every error code that the contract gives for those responses is named in that state; each screen describes each of the stage's six states or says why it does not apply; each definition has the 12 kinds of cases in order and a layout at both widths; every state that a file names, such as `SCR-105#stale`, is defined; the states that this file lists match the definitions; and the Korean translations hold the same states, responses, codes and named states as the English files.
- Every link of these files resolves, with its anchor, including each screen's place in the wireframes.
- The wireframes have a frame for each of the 45 states at 320 and 1440 pixels, and none for a state that is not defined. In Chromium at widths of 320, 390, 1,280 and 1,440 pixels, in light and dark mode and in both languages, the page does not scroll sideways, no element leaves its frame, and the console shows no error. Looked at as images: `SCR-101#normal`, `SCR-106#error` and `SCR-109#stale` at both widths, in light mode and Korean, and `SCR-107#normal` at 320 pixels in dark mode and Korean; the other frames were measured, not looked at.
- The hub's snapshot of this repository reads the nine definitions as the screen definitions of SCR-101 to SCR-109, with their 45 states, and adds no check result; with the correction of change 4, the two warnings that stage 07's text gave on `main` are gone too.
- The repository's checks with these files pass: `python -m unittest discover -s tests`, `claude plugin validate --strict` for the marketplace and its three plugins, `node --test nexus/test/*.test.js` and `git diff --check`.

## For the checkpoint

Waiting, together with the checkpoint of the user flows, the functional spec, the server's data, the interfaces and the sitemap. Most worth a look:

1. The pages' refusals as HTML (change 1), which changes the contract's three pages.
2. The picture view's states, above all `large`, `code-failed` and the newer version that is offered rather than drawn (choices 2 and 6), the panels beside the picture or under it (choice 3) and the panel of a part without an ID (choice 12).
3. The final words of the messages, in English and Korean.
4. The wireframes at 320 pixels, as on a phone.

## Notes for later stages

### Stage 09: mockups

- Two candidates for each new screen, SCR-105 to SCR-109, the phone first, at 320 pixels, from these frames; each state is a frame to design. The hub page keeps phase 1's design, with the additions of 0.2 on SCR-101 and SCR-104.
- The marks on a picture's items, and "Accepted, not yet reflected", need a form that reads on a full DDD board and in both themes, and a size that a finger can select.

### Stage 10: work breakdown

- The message page of change 1 comes with the server's pages; the views' states with the views; the hub page's states of 0.2 in [hub.html](../../../plugins/corthex-nexus/skills/corthex-hub/assets/hub.html), which [nexus/src/hub.html](../../../nexus/src/hub.html) copies.

### Stage 11: development

- Each state is built against Prism's mock, which returns any response that the contract lists on request, before the server is ready.
- The view's requests: `redirect: "manual"`, an abort after 30 seconds, the write ID kept with the text in the browser's storage, and an `opaqueredirect` reply read as an expired sign-in.
- The static line in each view's HTML, which the core file hides when it runs, and the editor loaded on its own, so that its failure leaves the list of items.
- Tests open each panel from its address, lead each state from its response, and bring unsent text back after a reload.

### Stage 12: QA

- A test case for each state, such as `SCR-105#large`, at 320 and 1440 pixels, walked by the stage's browser agents, first with the mock's responses and then on a development server behind Access.
- By hand: a sign-in that expires in an open view, a reply that is lost, a second tab that closes a comment, and a request that waits more than 30 seconds.
