# 구조 설명

[English](architecture.md)

CORTHEX가 어떻게 짜여 있고 왜 그렇게 했는지 설명합니다. 파일 형식은 입구 스킬의 참고 문서에 한 번만 정의되어 있고, 이 문서는 그 내용을 되풀이하지 않고 링크합니다.

상태: 0.1.0. 핵심 플러그인 `corthex`가 있고, `corthex-memory`의 첫 부분(세션 시작 문맥)과 `corthex-nexus`의 첫 부분(로컬 프로젝트 허브와 직접 배포하는 NEXUS 서버)이 있습니다. 둘의 나머지는 계획 중입니다([앞으로](#앞으로) 참고).

## 목표

- 누구나 공개 Git 저장소에서 Claude Code와 Codex에 각 도구의 플러그인 명령으로 설치할 수 있습니다.
- 한 사람이 여러 프로젝트를 진행할 수 있고, 같은 플러그인을 파일을 고치지 않고 프로필만으로 사람마다 맞춥니다.
- 각 단계는 다음 단계로 추적할 수 있는 결과물을 넘깁니다.
- 따로 돌아가는 서비스나 갱신기를 더하지 않습니다. 설치와 갱신은 각 도구의 마켓플레이스가 맡고, 지침은 스킬이며, 선택해서 쓰는 기억 플러그인은 각 도구의 훅을 씁니다.

다루지 않는 것: 자체 갱신기나 기기 동기화, 사용자 전역 지침 파일 수정, 비밀값 저장.

## 저장소 배치

```text
.
├── .claude-plugin/marketplace.json      Claude Code용 마켓플레이스
├── .agents/plugins/marketplace.json     Codex용 마켓플레이스
├── plugins/
│   ├── corthex/                         핵심 플러그인, 스킬만 담음
│   │   ├── .claude-plugin/plugin.json   Claude Code용 매니페스트
│   │   ├── plugin.json                  Agent Plugins 1.0 매니페스트, Codex가 읽음
│   │   ├── LICENSE, NOTICE
│   │   └── skills/
│   │       ├── corthex/                 입구 스킬
│   │       │   ├── references/          원칙, 프로필, 프로젝트, 단계 계약
│   │       │   └── assets/              profile.json과 project.json 예시
│   │       ├── corthex-discover/ …      단계 스킬, 단계마다 참고 문서 하나
│   │       └── corthex-record/          회의록, 결정, 진행 기록
│   ├── corthex-memory/                  세션 시작 문맥, 훅이 있음
│   │   ├── .claude-plugin/plugin.json   Claude Code용 매니페스트
│   │   ├── .codex-plugin/plugin.json    Codex용 매니페스트, 루트 plugin.json은 없음
│   │   ├── hooks/hooks.json             세션 시작 훅 하나, 두 도구가 함께 읽음
│   │   ├── scripts/session_start.py     문맥을 만듦, Python 표준 라이브러리만 씀
│   │   ├── context/principles.md        일하는 원칙의 짧은 판
│   │   └── LICENSE, NOTICE
│   └── corthex-nexus/                   프로젝트 허브, 스크립트가 든 스킬
│       ├── .claude-plugin/plugin.json   Claude Code용 매니페스트
│       ├── plugin.json                  Agent Plugins 1.0 매니페스트, Codex가 읽음
│       ├── skills/corthex-hub/
│       │   ├── scripts/hub.py           스냅샷, 점검, 페이지, 보내기와 지우기, Python 표준 라이브러리만 씀
│       │   ├── assets/hub.html          네트워크에서 아무것도 불러오지 않는 페이지 틀
│       │   └── references/              허브가 읽고 점검하는 것, 파일 형식
│       └── LICENSE, NOTICE
├── nexus/                               NEXUS 서버, Cloudflare Worker, 플러그인 아님
│   ├── src/                             Worker, D1 저장, 스냅샷 검사, 허브 페이지 사본
│   ├── test/                            메모리 안의 D1 대역으로 돌리는 Node 검사
│   ├── wrangler.jsonc                   Worker 설정, 배포할 때 wrangler.local.jsonc로 복사
│   └── README.md                        Cloudflare Access 뒤에 배포하는 방법
├── tests/                               검사, Python 표준 라이브러리만 씀
└── docs/
```

## 매니페스트 둘, 스킬 한 벌

Claude Code는 플러그인 매니페스트를 `.claude-plugin/plugin.json`에서 읽습니다. Codex와 다른 Agent Plugins 클라이언트는 플러그인 루트의 `plugin.json`을 읽고, Codex는 그 파일의 `extensions.com.openai`에서 자기 설정을 가져갑니다. Agent Plugins 1.0의 호환 클라이언트 목록에 Claude Code가 없어서 두 파일을 함께 둡니다. `skills/` 폴더는 하나를 같이 씁니다.

훅이 든 플러그인은 예외입니다. Codex CLI 0.164.0은 플러그인 루트에 `plugin.json`이 있으면 `.codex-plugin/plugin.json`을 함께 둬도 그 플러그인의 훅을 돌리지 않습니다([openai/codex#39895](https://github.com/openai/codex/issues/39895), 2026-10-23에 재현). 루트 `plugin.json`이 없으면 Codex는 `.codex-plugin/plugin.json`을 읽고 `hooks/hooks.json`을 스스로 찾습니다. 그래서 `corthex-memory`는 `.claude-plugin/plugin.json`과 `.codex-plugin/plugin.json`을 두고 루트 `plugin.json`은 두지 않습니다. 이 때문에 다른 Agent Plugins 클라이언트에는 가지 않고, OpenAI 디렉터리는 원래 훅이 든 플러그인을 받지 않습니다. `corthex-nexus`는 훅이 없어서 핵심 플러그인처럼 두 파일을 모두 둡니다.

`tests/test_manifests.py`가 매니페스트를 맞춰 둡니다.

- `name`, `version`, `description`, `author`, `homepage`, `repository`, `license`, `keywords`는 Claude Code 매니페스트와 Codex 매니페스트에서 같아야 합니다.
- 플러그인마다 Codex 매니페스트는 하나이고, 훅이 든 플러그인에는 루트 `plugin.json`이 없습니다.
- 루트 `plugin.json`은 `$schema`에 스키마를 밝히고, 그 스키마가 허용하는 항목만 씁니다.
- 버전은 마켓플레이스 항목이 아니라 매니페스트에 둡니다.

## 마켓플레이스 둘

| 파일 | 읽는 곳 | 설치 |
| --- | --- | --- |
| `.claude-plugin/marketplace.json` | Claude Code. Codex도 호환용으로 읽습니다. | `claude plugin marketplace add kodonghui/corthex` 다음 `claude plugin install corthex@corthex` |
| `.agents/plugins/marketplace.json` | Codex | `codex plugin marketplace add kodonghui/corthex` 다음 `codex plugin add corthex@corthex` |

두 파일은 같은 마켓플레이스 이름 아래 같은 플러그인을 싣습니다. 그래서 두 도구 모두 설치 이름이 `corthex@corthex`입니다.

선택 플러그인도 같은 방식으로 `corthex-memory@corthex`, `corthex-nexus@corthex`를 설치합니다. 둘 다 `corthex`를 의존 플러그인으로 밝혀 두어 Claude Code는 `corthex`도 함께 설치하고, Codex에서는 `corthex`를 먼저 추가합니다.

## 핵심 플러그인을 스킬만으로 만드는 이유

스킬만 담은 플러그인은 고치지 않고 그대로 Claude Code, Codex, OpenAI 플러그인 디렉터리, 다른 Agent Plugins 클라이언트에 갑니다. OpenAI 디렉터리는 훅이 든 플러그인을 받지 않고, Codex는 Claude Code의 `userConfig`를 실행하지 않습니다. 스킬 하나를 따로 쓸 수도 있습니다. 예를 들어 claude.ai에 올려 쓸 수 있습니다.

그래서 핵심 플러그인에는 훅, 명령, 에이전트, MCP 서버, 사용자 설정을 넣지 않습니다. 이런 것이 필요한 기능은 별도 플러그인으로 만들고, `tests/test_manifests.py`가 이 규칙을 검사합니다.

## 스킬

| 스킬 | 단계 |
| --- | --- |
| `corthex` | 입구: 프로필, 프로젝트, 원칙, 단계 안내 |
| `corthex-discover` | 01 도메인 탐색 |
| `corthex-define` | 02 PRD, 03 유저 플로우, 04 기능 명세 |
| `corthex-contract` | 05 ERD, 06 API |
| `corthex-screen` | 07 사이트맵, 08 화면 상태, 09 목업 |
| `corthex-build` | 10 WBS, 11 개발, 12 QA |
| `corthex-present` | 13 발표 |
| `corthex-record` | 회의록, 결정, 진행 기록. 어느 단계에서나 |

`corthex-nexus`는 스킬 `corthex-hub` 하나를 더합니다([프로젝트 허브](#프로젝트-허브) 참고).

- **14개가 아니라 8개입니다.** 도구는 세션마다 모든 스킬의 설명을 보여 주고, Codex는 이 첫 목록을 문맥 창의 2%(창 크기를 모르면 8,000자)로 제한합니다. 묶어서 목록을 짧게 유지합니다. 단계별 내용은 `references/`에 두고 필요할 때만 읽습니다.
- **이름은 `corthex-`로 시작합니다.** 스킬을 플러그인 밖에서 따로 써도 이름이 겹치지 않게 하려는 것입니다. 플러그인 안에서는 두 도구 모두 `corthex:<스킬>`로 보여 줍니다.
- **앞머리는 어디서나 쓸 수 있게 씁니다.** Agent Skills 형식의 항목(`name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools`)만 씁니다. claude.ai 업로드와 Skills API가 특정 도구 전용 항목을 거부하기 때문입니다. 본문은 500줄 아래로 두고, 링크는 스킬 자기 폴더 안에서 한 단계까지만 겁니다.
- **스킬 본문은 영어입니다.** 답변 언어는 사용자 프로필을 따릅니다.

0.1.0을 로컬에 설치해 잰 값: `claude plugin details`(Claude Code 2.1.309)는 스킬 설명 8개가 늘 차지하는 양을 약 1,000토큰으로 보고하고, Codex CLI 0.164.0에서는 스킬 목록 가운데 약 3,200자를 씁니다.

## 일하는 원칙

Claude Code는 플러그인 루트의 `CLAUDE.md`를 맥락으로 읽지 않고, 그런 지시는 스킬에 두라고 안내합니다. 그래서 원칙은 입구 스킬의 [principles.md](../plugins/corthex/skills/corthex/references/principles.md)에 두고, CORTHEX 스킬을 쓰는 동안 적용합니다.

`corthex-memory` 플러그인을 설치하면 세션이 시작될 때마다 짧은 원칙을 훅으로 넣습니다([세션 시작 문맥](#세션-시작-문맥) 참고). CORTHEX 자체는 사용자 전역 지침 파일을 고치지 않습니다.

## 단계 계약

모든 단계는 여섯 칸을 채웁니다: 입력, 산출물, 사람 화면, 동기화, 사람 확인 지점, 추적 ID. 각 단계의 텍스트 원본은 제품 저장소에 두고, 사람이 보는 화면(Notion, Miro, ERD 도구, Figma 등)은 팀마다 다를 수 있습니다. 어느 쪽이 정본인지는 단계마다 프로젝트 설정이 정합니다.

AI는 도구에 MCP 서버, 커넥터, API가 있으면 그것으로 사람 화면을 읽고 고칩니다. 가져오기와 내보내기만 되는 도구는 사람이 내보낸 파일에 기대므로, AI는 자기 사본이 언제 것인지 밝힙니다. ERD는 다이어그램을 저장소에 두고 MCP 서버가 있는 ERD Editor를 새 프로젝트에 권합니다. 도메인 탐색은 Miro의 MCP 서버를 통해 Miro 보드에서 AI와 사용자가 이벤트 스토밍을 단계마다 프레임 하나씩 진행합니다. 기본은 AI가 단계마다 초안을 그리고 사람이 보드에서 고치는 방식이며, 결과는 도메인 설계서 한 파일로 남깁니다.

- 계약, 단계 키, 추적 ID 규칙: [stage-contract.md](../plugins/corthex/skills/corthex/references/stage-contract.md)
- 각 단계의 여섯 칸, 진행 순서, 점검, 산출물 틀: 단계 스킬의 `references/<단계>.md`. 예: [02-prd.md](../plugins/corthex/skills/corthex-define/references/02-prd.md)
- `tests/test_stages.py`는 모든 단계가 여섯 칸을 채우는지, 단계 스킬이 자기 단계를 링크하는지, 단계 스킬들이 같은 진행 순서를 쓰는지, 진행 순서와 계약이 AI가 닿지 못하는 사람 화면의 규칙을 지키는지, 06·08·11·12단계가 모든 응답을 다루고 오류 코드를 한 목록에 두는지, 응답마다 화면 상태와 테스트 케이스를 잇는지, 운영 서버에서 테스트하지 않는지, 04·06·08·12단계와 계약이 같은 경우의 수 목록을 쓰는지, QA의 브라우저 에이전트 실행이 그 규칙을 지키는지 검사합니다. 모든 단계에 기본 사람 화면이 있는지, 다른 도구를 고르면 결정으로 기록하게 하는지, MCP 서버를 어느 파일에서나 같은 방법으로 추가하는지, 09단계의 리졸버 예시가 스키마를 따르는지도 검사합니다.

06·08·11·12단계는 코드보다 먼저 쓴 API 계약을 기준으로 일합니다. 각 API 동작은 돌려줄 수 있는 응답(200, 401, 422 등)을 예시와 함께 모두 적고, 돌려줄 수 없는 응답은 그 이유를 적습니다. 오류는 모두 한 가지 모양(Problem Details, RFC 9457)에 한 목록의 오류 코드를 씁니다. 프런트엔드는 계약으로 만든 목 서버에 대고 먼저 만들고, 응답마다 보여 줄 화면 상태가 정해져 있습니다. 백엔드는 개발이나 스테이징 서버에서 계약 테스트로 계약과 맞는지 확인합니다. QA는 응답과 화면 상태마다 테스트 케이스를 쓰고, `API-001#401`, `SCR-002#permission`처럼 이름을 붙이며, 목록에 있는 응답 가운데 실제 서버가 일부러 돌려주게 할 수 있는 것은 모두 쏘아 보는 API 테스트를 저장소에 둡니다. 출시 전에는 Aside 같은 브라우저 에이전트가 localhost나 시험용 사이트에서 모든 사용자 흐름을 돌고, 되는 것, 안 되는 것, 느낀 점을 보고합니다. 잘 되는 흐름은 풀 리퀘스트마다 도는 E2E 테스트로 고정합니다. 04·06·08·12단계는 권한과 입력부터 AI 답변까지 열두 가지 경우의 수 목록을 함께 써서, 기능 명세가 적은 경우마다 응답, 화면 상태, 테스트가 생기게 합니다.

프로젝트를 등록하거나 단계를 처음 설정할 때 AI는 계약에 적힌 단계별 기본 사람 화면을 제안합니다. 도메인 탐색은 Miro 보드, PRD·사용자 흐름·기능 명세는 Notion 데이터베이스, ERD는 ERD Editor, API는 Swagger UI, 사이트맵과 화면 상태는 AI가 파일에서 그리는 화면, 목업은 Figma나 Claude Design, WBS는 GitHub Projects나 Notion, 개발은 풀 리퀘스트, QA는 테스트 계획·테스트 보고서·실행 보고서·버그 트래커, 발표는 장면 표로 만든 슬라이드입니다. 사용자나 팀이 다른 도구를 고르면 AI는 그 선택을 결정으로 기록하고 단계 설정에 적어, 기록된 결정 없이 다른 도구로 옮겨 가는 단계가 없게 합니다. 기본 도구를 연결하고 텍스트 원본과 맞추는 방법은 각 단계의 참조 파일에 있습니다.

## 프로필과 프로젝트

| 파일 | 위치 | 담는 것 |
| --- | --- | --- |
| `profile.json` | 기기마다 `~/.corthex/` | 사용자 호칭, 언어, 기록 위치, 먼저 물어볼 일 |
| `project.json` | 제품 저장소마다 `.corthex/`, 커밋함 | 이름, 팀 또는 개인, 기록 위치, 원본이 있는 다른 저장소, ID 형식, 단계별 사람 화면·원본·정본 |
| `projects.json` | 기기마다 `~/.corthex/` | 이 기기에 있는 프로젝트와 그 저장소들의 로컬 경로 |

항목은 [profile.md](../plugins/corthex/skills/corthex/references/profile.md)와 [project.md](../plugins/corthex/skills/corthex/references/project.md)에 있습니다.

- Claude Code의 `userConfig` 대신 일반 파일을 씁니다. 파일은 두 도구가 모두 읽을 수 있기 때문입니다.
- 프로필에는 비밀값을 넣지 않습니다. 키는 도구의 보안 저장소나 환경 변수에 둡니다.
- `project.json`은 팀원 모두가 같은 설정을 보도록 커밋합니다. `projects.json`은 기기마다 경로가 달라서 기기에만 둡니다.
- 모르는 항목은 지우지 않고 무시합니다. 그래서 새 판이 항목을 더해도 옛 판이 깨지지 않습니다.

## 세션 시작 문맥

`corthex-memory` 0.1.0에는 훅이 하나 있습니다. 세션이 시작될 때마다 `scripts/session_start.py`가 짧은 문맥을 넣습니다. 새로 시작할 때, 이어 열 때, `/clear` 뒤, 문맥 압축 뒤, 세션을 갈라 낼 때입니다. 이어 연 세션과 갈라 낸 세션은 기록에 예전 문맥을 이미 갖고 있고, 새 문맥이 그 뒤에 바뀐 파일 내용을 들여옵니다. 문맥에는 이것이 들어갑니다.

- 일하는 원칙의 짧은 판. `tests/test_memory.py`가 입구 스킬의 목록과 같게 유지합니다.
- `~/.corthex/profile.json`의 프로필. 없으면 기본 `ask_before` 목록을 포함한 기본값을 알립니다. 파일이 있는데 읽을 수 없으면 그렇다고 알리고, 파일을 새로 만들어 덮어쓰지 말라고 한 뒤 기본값을 알립니다.
- 프로젝트: 저장소 루트까지 올라가며 찾은 가장 가까운 `.corthex/project.json`, 없으면 `~/.corthex/projects.json`에서 지금 폴더를 경로나 저장소로 가진 프로젝트. 단계마다 사람 화면, 정본, 원본을 알립니다. 이 기기의 다른 프로젝트는 이름만 적습니다.

이 파일들만 읽고, 아무것도 쓰지 않으며, 네트워크에 연결하지 않습니다. 무엇이든 실패하면 훅은 아무것도 넣지 않고 세션은 평소대로 시작합니다.

- **저장소 설정은 정해진 형식만 보여 줍니다.** `project.json`은 아직 살펴보지 않은 저장소에서 올 수 있고, Codex는 훅 문맥을 개발자 메시지로 넣습니다. 그래서 이 파일에서는 공백 없는 짧은 ASCII 값만 보여 줍니다. 이름, 도구 이름, 경로, 링크, `truth` 값입니다. 제목과 단계 메모 같은 자유 글은 보여 주지 않고, 메모가 있는 단계는 표시만 해서 에이전트가 파일에서 읽게 합니다. 형식에 맞지 않는 다른 값은 뺐다고 표시합니다. 프로필과 프로젝트 목록은 사용자 자신의 파일이므로 값마다 한 줄로 펴서 그대로 보여 줍니다.
- **크기.** 문맥은 UTF-8 8,000바이트 아래로 둡니다. Claude Code는 10,000자를 넘는 훅 문맥을 파일로 돌리고, Codex는 핸들러의 `additionalContextLimit`을 넘는 문맥을 그렇게 합니다. `hooks/hooks.json`은 이 값을 기본값 2,500 대신 8,000토큰으로 둡니다. 글자 하나도 토큰 하나도 1바이트 이상이므로 어느 도구도 문맥을 파일로 돌리지 않습니다. 설정이 더 크면 글을 자르고 잘랐다고 적습니다.
- **Codex는 신뢰를 묻습니다.** Codex는 `/hooks`에서 검토하고 신뢰한 플러그인 훅만 돌립니다. 설치한 뒤 한 번, 갱신으로 훅이 바뀌면 다시 신뢰합니다.
- **끄는 법.** 플러그인을 끄거나 지웁니다. Claude Code는 `claude plugin disable corthex-memory@corthex`를 실행합니다. Codex는 `~/.codex/config.toml`의 `[plugins."corthex-memory@corthex"]`에 `enabled = false`를 두거나 `codex plugin remove corthex-memory@corthex`를 실행합니다. 훅이 저장하는 것이 없어서 따로 되돌릴 것은 없습니다.
- **Windows.** 훅 명령은 둘입니다. `command`는 `python3`, `python`, `py` 실행기를 차례로 쓰도록 `||`로 잇습니다. Claude Code는 어느 체제에서나 이 명령을 돌리는데, Windows에서는 Git Bash로, Git Bash가 없으면 PowerShell로 돌리고 플러그인 폴더는 환경 변수로 넘깁니다. PowerShell 7은 `||`를 받지만 Windows PowerShell 5.1은 받지 않으므로, Windows의 Claude Code에서는 Git for Windows나 PowerShell 7이 있어야 합니다. 둘 다 없으면 훅이 실패하고 세션은 문맥 없이 시작합니다. Windows의 Codex는 그 대신 `commandWindows`를 돌리고, Git Bash가 있어도 늘 PowerShell로 돌립니다. PowerShell 7이 있으면 그것으로, 없으면 Windows PowerShell 5.1로 돌립니다. 이 명령은 5.1도 아는 `if ($LASTEXITCODE -ne 0)`로 `python` 다음에 `py -3`을 쓰고, Codex가 넣어 주는 `CLAUDE_PLUGIN_ROOT` 변수로 스크립트를 찾습니다.
- **지금까지 확인한 것.** 2026-10-23에 Linux에서 Claude Code 2.1.309와 Codex CLI 0.164.0을 격리된 설정과 로컬 가짜 모델 API로 돌려 확인했습니다.
  - 두 도구 모두 첫 모델 요청에 문맥이 실렸고, 프로젝트 파일의 제목과 메모는 실리지 않았습니다. Codex는 훅을 신뢰했을 때만 돌렸고, 시험에서는 검토 대신 `--dangerously-bypass-hook-trust`를 썼습니다.
  - 프로필을 바꾼 뒤 이어 연 세션(`claude -p --resume`, `codex exec resume`)과 갈라 낸 세션(`claude -p --resume … --fork-session`)에는 기록에 있던 예전 문맥과 함께 새 문맥이 실렸습니다.
  - Codex에서 28,872바이트짜리 시험 문맥은 `additionalContextLimit`을 8,000으로 두면 그대로 모델에 갔고, 두지 않으면 미리보기로 바뀌었습니다.
  - 2026-10-24에 Windows Server 2025 실행기에서 Claude Code 2.1.310, Codex CLI 0.164.0, 같은 가짜 모델 API로 확인했습니다(`.github/workflows/windows-hook-check.yml`). Git Bash가 있을 때와, Git Bash 없이 PowerShell 7만 있을 때는 두 도구 모두 모델에 문맥이 실렸습니다. Windows PowerShell 5.1만 있을 때는 `||` 명령을 읽지 못해 Claude Code는 문맥 없이 시작했고, Codex는 `commandWindows`로 문맥을 받았습니다.

  Codex의 세션 갈라 내기와 macOS는 아직 시험하지 않았습니다. 훅을 돌리는 셸의 PATH에 `python3`, `python`, Windows의 `py` 실행기 중 하나가 있어야 합니다.

## 프로젝트 허브

`corthex-nexus` 0.1.0에는 스킬 `corthex-hub` 하나와 스크립트 `scripts/hub.py` 하나가 있습니다. 프로젝트마다 이미 있는 파일로 모든 프로젝트를 한 페이지에 모으고, 서버는 쓰지 않습니다. `nexus/`의 NEXUS 서버는 선택이고, 같은 페이지를 사용자의 주소에 올립니다.

- **스냅샷.** `~/.corthex/projects.json`의 프로젝트마다 `.corthex/project.json`이 가리키는 단계별 원본을 읽습니다. 프로젝트의 다른 저장소에 있는 원본도 읽습니다. 그 원본이 정의하고 잇는 것을 저장합니다: 추적 ID와 제목·항목 값, 각 ID가 있는 파일과 줄, ID 사이의 링크, 점검 결과. 프로젝트는 등록된 이름으로만 읽습니다. `.corthex/project.json`이 다른 이름을 적었거나, 등록되지 않은 폴더가 등록된 프로젝트의 이름을 적었으면 아무것도 읽지 않고 이유를 알리므로, 저장소 설정으로 자기 항목을 다른 프로젝트 이름으로 저장하거나 보낼 수 없습니다. 글자만 읽고 프로젝트 코드를 실행하지 않습니다. Git은 PATH의 절대 경로 폴더에서만 찾고 현재 폴더에서는 찾지 않으며, 저장소의 fsmonitor 훅, clean 필터, 선택적 잠금 없이 돌리고 하위 모듈 안은 보지 않으므로, 저장소 상태를 읽어도 그 저장소의 프로그램을 띄우거나 무엇을 다시 쓰지 않습니다. 추적 중인 파일이 Git LFS 같은 clean 필터를 쓰면, 스냅샷은 작업 트리에 바뀐 것이 있는지 적지 않습니다. 이름이 비밀값처럼 보이는 파일과 그런 이름의 폴더 안에 있는 파일은, 링크로 이어져도 건너뜁니다. `spec.md` 옆의 `spec.ko.md`처럼 원문 옆에 둔 번역이 원문의 ID만 정의하면 그 번역도 건너뛰어, 같은 ID를 두 번 정의하지 않습니다. 읽는 형식과 점검은 [reading.md](../plugins/corthex-nexus/skills/corthex-hub/references/reading.md)에 있습니다.
- **진행 상태.** 단계의 상태, 마지막 확인 지점, 다음 행동은 `hub.py status`로 기록한 것만 씁니다. 파일이 있다고 단계가 끝난 것은 아니기 때문입니다. `done`은 확인 지점과 그 날짜 없이는 기록하지 않습니다. 검토에서 찾은 점도 같은 방법으로 기록합니다.
- **페이지.** `hub.py build`가 `~/.corthex/hub/index.html`을 씁니다. 프로젝트마다 13단계의 상태와 개수, 점검 결과, 단계별 설정과 항목, ID마다 앞뒤로 이어진 항목을 보여 주는 추적 화면, 검색이 있습니다. 자료는 페이지 안에 들어 있고, 콘텐츠 보안 정책이 모든 요청을 막으며, 글은 글로만 보여 줍니다. 그래서 디스크에서 바로, 오프라인에서도 열립니다. 언어는 프로필을 따라 한국어나 영어로, 밝은 화면과 어두운 화면은 시스템 설정을 따릅니다. `~/.corthex/projects.json`에서 빠진 프로젝트의 저장된 스냅샷은 디스크에 남지만 페이지에는 넣지 않습니다.
- **기기 밖으로 나가는 것.** 사용자가 `hub.py push`를 실행하지 않으면 아무것도 나가지 않습니다. 스냅샷에는 ID, 제목, 항목 값, 점검 결과, 저장소 기준의 파일 위치, 커밋 ID가 들어갑니다. 그 밖의 파일 내용과 로컬 경로는 들어가지 않고, 제목에 든 비밀값과 이메일 주소는 `[redacted]`로 바꾸며, 그런 값이 든 링크는 넣지 않습니다. 형식은 [snapshot.md](../plugins/corthex-nexus/skills/corthex-hub/references/snapshot.md)에 있습니다.
- **보내기.** `hub.py push`는 프로필의 `nexus.push`에 적은 프로젝트의 스냅샷만 `nexus.url`로 보냅니다. HTTPS를 쓰고, Cloudflare Access 서비스 토큰은 환경 변수에서 읽습니다. 리다이렉트를 따라가지 않아서, 토큰이 거절되면 다른 곳으로 보내지 않고 알립니다. 서버가 스냅샷을 거절하면 서버가 밝힌 이유를 보여 줍니다. `hub.py remove`는 서버에서 프로젝트를 지웁니다.
- **서버.** `nexus/`는 Cloudflare D1 데이터베이스를 쓰는 Cloudflare Worker로, 사용자가 자기 Cloudflare 계정에 배포합니다. Cloudflare Access가 확인한 요청에만 `ctx.access`로 답하므로, Access가 없는 Worker는 아무것도 보여 주지 않습니다. `workers.dev` 주소, 미리보기 주소, 정적 자산이 없습니다. 이것들이 있으면 그 확인이 Worker에 오지 않습니다. 스냅샷마다 형식을 검사하고, 프로젝트마다 더 새 스냅샷을 두며, 1MiB짜리 30개 프로젝트까지 받습니다. 같은 페이지를 자기 스크립트만 해시로 허용하는 정책과 함께 보여 줍니다. 데이터베이스 코드는 파일 하나에 모여 있어, 나중에 D1을 다른 데이터베이스로 바꿀 수 있습니다. 설정 방법: [nexus/README.ko.md](../nexus/README.ko.md).

지금까지 확인한 것: `tests/test_hub.py`는 단계 스킬의 산출물 틀 그대로 프로젝트를 만들고, 허브가 거기서 읽은 항목, 링크, 점검 결과를 모두 확인합니다. 이어서 원본 형식마다, 진행 기록 파일, 페이지, 로컬 가짜 서버를 상대로 한 보내기를 확인합니다. Linux의 Python 3.8과 3.13에서 통과합니다. 페이지는 Chromium에서 1440과 320픽셀 폭, 밝은 화면과 어두운 화면으로 열어 스크립트 오류, 가로 스크롤, 네트워크 요청이 없는 것을 봤습니다. 저장소 세 곳에 나뉘고 요구사항을 Notion에서 내보낸 실제 프로젝트도 바꾸지 않고 읽었습니다. Windows와 macOS는 아직 돌려 보지 않았습니다.

서버는 `nexus/test/`가 메모리 안의 SQLite로 D1을 대신해 Worker를 검사하고, `tests/test_nexus.py`가 서버를 그 컴퓨터에서 돌립니다. `hub.py`가 단계 틀로 만든 프로젝트를 보내고, 다시 읽고, 더 오래된 스냅샷은 거절되는지 보고, 프로젝트를 지웁니다. Access가 없으면 모든 요청이 `403`을 받는 것도 봅니다. Wrangler 4.152.0으로 `wrangler deploy --dry-run`이 Worker를 묶었고, `wrangler dev`로 Workers 실행 환경에서 Access를 흉내 내어 같은 단계를 돌렸으며, Access가 없을 때는 `403`을 받았습니다. 실제 프로젝트의 스냅샷(항목 92개, 약 40KB)도 서버 검사를 통과하고 그대로 돌아왔습니다. 2026-10-24에는 관리자 자신의 주소에 Cloudflare Access를 앞에 두고 서버를 배포했습니다. 로그인하지 않은 요청은 Access 로그인으로 돌려보내졌고, 휴대폰에서 로그인해 페이지까지 열렸으며, 서비스 토큰으로 보낸 예시 프로젝트가 저장됐습니다.

## 버전과 릴리스

- 버전은 유의적 버전을 씁니다. 버전은 두 매니페스트와 모든 스킬의 `metadata.version`에 있고, 검사가 셋을 같게 유지합니다.
- 릴리스는 `<플러그인>--v<버전>` 이름의 Git 태그입니다. 예: `corthex--v0.1.0`. `claude plugin tag`가 매니페스트와 마켓플레이스 항목이 맞는지 확인한 뒤 태그를 만듭니다.
- 사용자는 각 도구의 마켓플레이스 명령으로 갱신을 받습니다.

## 검사

| 검사 | 명령 | 범위 |
| --- | --- | --- |
| 저장소 검사 | `python -m unittest discover -s tests -v` | 매니페스트와 마켓플레이스, 스킬 형식, 단계 계약, 기억 훅과 그 스크립트, 허브 스크립트와 페이지와 보내기, Node 22.13 이상이 있을 때 `hub.py`와 NEXUS 서버, 설명서 링크와 번역 짝, 비밀값과 개인 정보 |
| 서버 검사 | `node --test nexus/test/*.test.js` | NEXUS Worker: Access 확인, 스냅샷 검사, 저장, 페이지와 보안 헤더 |
| Claude Code 검증 | `claude plugin validate --strict .` 다음 플러그인마다 `claude plugin validate --strict plugins/<플러그인>` | 마켓플레이스와 플러그인에 대한 Claude Code 자체 스키마 |

CI는 모든 풀 리퀘스트와 `main`에 올라오는 모든 push에서 저장소 검사와 서버 검사를 Linux, Windows, macOS에서, Claude Code 검증과 서버의 Wrangler 빌드를 Linux에서 돌립니다. `corthex-memory`나 Windows 훅 검사를 바꾸는 풀 리퀘스트는 Windows에서 Claude Code와 Codex로 기억 훅도 돌립니다. Git Bash가 있을 때, PowerShell 7만 있을 때, Windows PowerShell 5.1만 있을 때를 로컬 가짜 모델 API로 돌립니다.

## 앞으로

0.1.0에는 없고 계획만 있습니다. 둘 다 핵심 플러그인에 넣지 않는 구성 요소가 필요합니다.

- `corthex-memory`의 다음 판: 대화 기록을 모아 프로젝트마다 현재 상태로 정리하고, 필요한 것을 다시 꺼내는 훅. 그 현재 상태도 세션 시작 문맥에 넣습니다. 요구사항: [docs/02-prd/memory.ko.md](02-prd/memory.ko.md). 사용자 흐름: [docs/03-user-flow/memory/](03-user-flow/memory/README.ko.md). 기능 명세: [docs/04-functional-spec/memory.ko.md](04-functional-spec/memory.ko.md). 기억 폴더: [docs/05-erd/memory.ko.md](05-erd/memory.ko.md).
- `corthex-nexus`의 다음 판: 요구사항 [docs/02-prd/nexus.ko.md](02-prd/nexus.ko.md)로 정합니다. NEXUS 서버의 사이트맵·유저 플로우 편집 화면과 같은 자료를 쓰는 MCP 서버는 거기서 후보입니다(결정 D5). 기억을 여러 기기에서 함께 쓰게 되면 서버 저장소를 D1에서 Postgres로 옮길 수 있습니다.

## 근거

2026-10-23에 확인했습니다.

- Claude Code: [Plugin manifest reference](https://code.claude.com/docs/en/plugins/manifest-reference), [Marketplace reference](https://code.claude.com/docs/en/plugins/marketplace-reference), [Plugin dependencies](https://code.claude.com/docs/en/plugins/dependencies), [Publish and distribute a plugin](https://code.claude.com/docs/en/plugins/publish), [Skills](https://code.claude.com/docs/en/skills)
- OpenAI: [Codex plugins](https://developers.openai.com/codex/plugins/build), [Submit your Claude Code plugin to OpenAI](https://developers.openai.com/plugins/guides/submit-claude-plugin), [Build skills](https://learn.chatgpt.com/docs/build-skills)
- Agent Plugins: [Plugin manifest](https://agent-plugins.org/plugin-authors/manifest), [Client extensions](https://agent-plugins.org/plugin-authors/client-extensions), [Compatible clients](https://agent-plugins.org/compatible-clients)
- 훅: [Claude Code hooks reference](https://code.claude.com/docs/en/hooks), [Codex hooks](https://learn.chatgpt.com/docs/hooks), [openai/codex#39895](https://github.com/openai/codex/issues/39895)
- Cloudflare Access: [Authenticate agents](https://developers.cloudflare.com/cloudflare-one/access-controls/authenticate-agents/), [Service tokens](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/)
- Cloudflare Workers와 D1: [Cloudflare Access for Workers](https://developers.cloudflare.com/workers/configuration/cloudflare-access/), [Custom Domains](https://developers.cloudflare.com/workers/configuration/routing/custom-domains/), [Workers limits](https://developers.cloudflare.com/workers/platform/limits/), [D1 limits](https://developers.cloudflare.com/d1/platform/limits/)
- [Agent Skills specification](https://agentskills.io/specification)
