# 구조 설명

[English](architecture.md)

CORTHEX가 어떻게 짜여 있고 왜 그렇게 했는지 설명합니다. 파일 형식은 입구 스킬의 참고 문서에 한 번만 정의되어 있고, 이 문서는 그 내용을 되풀이하지 않고 링크합니다.

상태: 핵심 `corthex`는 0.8.0, MEMORY 0.2.1은 프로젝트별 확인 목록을 반영하며 출시 결정과 알려진 한계는 MEMORY 작업·시험 계획에서 추적하고 NEXUS는 0.2.2입니다. 기억에는 세션 문맥·로컬 기록·관리 명령이 있으며 모델 정리·회상은 C2 작업입니다. NEXUS에는 로컬 프로젝트 허브와 직접 배포하는 서버가 있습니다. 남은 작업은 [앞으로](#앞으로)에 있습니다.

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
│   │       ├── corthex-record/          회의록, 결정, 진행 기록, 회고
│   │       └── corthex-uxui/            화면·모션·영상을 만드는 법
│   │           ├── references/          용어, 값, 영상, 점검과 그 출처
│   │           └── scripts/             읽기만 하는 점검 둘: 페이지 안의 page-check.js, FFmpeg를 쓰는 media-check.py
│   ├── corthex-memory/                  세션 문맥과 C1 훅
│   │   ├── .claude-plugin/plugin.json   Claude Code용 매니페스트
│   │   ├── .codex-plugin/plugin.json    Codex용 매니페스트, 루트 plugin.json은 없음
│   │   ├── hooks/hooks.json             C1 훅 네 개, 두 도구가 함께 읽음
│   │   ├── scripts/hook.py              C1 훅 공통 진입점, Python 표준 라이브러리만 씀
│   │   ├── context/principles.md        일하는 원칙의 짧은 판
│   │   ├── skills/corthex-memory/scripts/memory_lib/   C1 공용 저장·문맥·훅 모듈
│   │   └── LICENSE, NOTICE
│   └── corthex-nexus/                   프로젝트 허브, 스크립트가 든 스킬
│       ├── .claude-plugin/plugin.json   Claude Code용 매니페스트
│       ├── plugin.json                  Agent Plugins 1.0 매니페스트, Codex가 읽음
│       ├── skills/corthex-hub/
│       │   ├── scripts/hub.py           스냅샷, 점검, 페이지, 보내기와 지우기, Python 표준 라이브러리만 씀
│       │   ├── assets/hub.html          네트워크에서 아무것도 불러오지 않는 페이지 틀
│       │   └── references/              허브가 읽고 점검하는 것, 파일 형식
│       └── LICENSE, NOTICE
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

그래서 핵심 플러그인에는 훅, 명령, 에이전트, MCP 서버, 사용자 설정을 넣지 않습니다. 이런 것이 필요한 기능은 별도 플러그인으로 만들고, `tests/test_manifests.py`가 이 규칙을 검사합니다. 스킬이 자기 `scripts/` 폴더에 스크립트를 두는 것은 Agent Skills 형식이 허용하는 일입니다. `corthex-uxui`에는 읽기만 하는 점검 둘이 있고, 에이전트가 다른 명령처럼 실행합니다.

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
| `corthex-record` | 회의록, 결정, 진행 기록, 회고. 어느 단계에서나 |
| `corthex-uxui` | 화면·모션·영상을 만드는 법과 그 점검. 08·09·13단계에서, 또는 단독으로 |

`corthex-nexus`는 스킬 `corthex-hub` 하나를 더합니다([프로젝트 허브](#프로젝트-허브) 참고).

- **단계마다 하나씩이 아니라 9개입니다.** 도구는 세션마다 모든 스킬의 설명을 보여 주고, Codex는 이 첫 목록을 문맥 창의 2%(창 크기를 모르면 8,000자)로 제한합니다. 묶어서 목록을 짧게 유지합니다. 단계별 내용은 `references/`에 두고 필요할 때만 읽습니다. `corthex-uxui`는 단계 스킬에 넣지 않고 따로 둡니다. 08·09·13단계에 쓰이면서 CORTHEX 프로젝트 밖의 화면·영상 작업에도 쓰이는데, 그런 작업에서 도구가 찾아 쓰려면 자기 설명이 있어야 하기 때문입니다.
- **이름은 `corthex-`로 시작합니다.** 스킬을 플러그인 밖에서 따로 써도 이름이 겹치지 않게 하려는 것입니다. 플러그인 안에서는 두 도구 모두 `corthex:<스킬>`로 보여 줍니다.
- **앞머리는 어디서나 쓸 수 있게 씁니다.** Agent Skills 형식의 항목(`name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools`)만 씁니다. claude.ai 업로드와 Skills API가 특정 도구 전용 항목을 거부하기 때문입니다. 본문은 500줄 아래로 두고, 링크는 스킬 자기 폴더 안에서 한 단계까지만 겁니다.
- **스킬 본문은 영어입니다.** 답변 언어는 사용자 프로필을 따릅니다.

0.1.0을 로컬에 설치해 잰 값: `claude plugin details`(Claude Code 2.1.309)는 스킬 설명 8개가 늘 차지하는 양을 약 1,000토큰으로 보고했고, Codex CLI 0.164.0에서는 스킬 목록 가운데 약 3,200자를 썼습니다. `corthex-uxui`를 더한 9개는 Claude Code 2.1.310에서 약 1,240토큰이고, 같은 판에서 8개는 약 1,050토큰입니다. 이 스킬의 설명은 Codex 목록에 약 580자를 더하며, Codex에서는 다시 재지 않았습니다.

## 일하는 원칙

Claude Code는 플러그인 루트의 `CLAUDE.md`를 맥락으로 읽지 않고, 그런 지시는 스킬에 두라고 안내합니다. 그래서 원칙은 입구 스킬의 [principles.md](../plugins/corthex/skills/corthex/references/principles.md)에 두고, CORTHEX 스킬을 쓰는 동안 적용합니다.

`corthex-memory` 플러그인을 설치하면 세션이 시작될 때마다 짧은 원칙을 훅으로 넣습니다([세션 시작 문맥](#세션-시작-문맥) 참고). CORTHEX 자체는 사용자 전역 지침 파일을 고치지 않습니다.

## 단계 계약

모든 단계는 여섯 칸을 채웁니다: 입력, 산출물, 사람 화면, 동기화, 사람 확인 지점, 추적 ID. 각 단계의 텍스트 원본은 제품 저장소에 두고, 사람이 보는 화면(Notion, Miro, ERD 도구, Figma 등)은 팀마다 다를 수 있습니다. 어느 쪽이 정본인지는 단계마다 프로젝트 설정이 정합니다.

AI는 도구에 MCP 서버, 커넥터, API가 있으면 그것으로 사람 화면을 읽고 고칩니다. 가져오기와 내보내기만 되는 도구는 사람이 내보낸 파일에 기대므로, AI는 자기 사본이 언제 것인지 밝힙니다. ERD는 다이어그램을 저장소에 두고 MCP 서버가 있는 ERD Editor를 새 프로젝트에 권합니다. 도메인 탐색은 Miro의 MCP 서버를 통해 Miro 보드에서 AI와 사용자가 이벤트 스토밍을 단계마다 프레임 하나씩 진행합니다. 기본은 AI가 단계마다 초안을 그리고 사람이 보드에서 고치는 방식이며, 결과는 도메인 설계서 한 파일로 남깁니다.

01단계는 AI의 확신도를 표시하고, 확인 지점 메모를 추측 항목·질문 두세 개·확인 지점 2와 3의 핵심 컨텍스트 애그리거트 규칙으로 줄입니다. 설계서에는 애그리거트별 규칙을 적고, 핵심 컨텍스트에는 근거와 Given–When–Then 예시를 붙이며, 바깥 시스템 연결의 관계 유형을 밝힌 Mermaid 컨텍스트 지도를 둡니다. 기존 제품에 기능을 더할 때는 바뀌는 컨텍스트만 단계를 다시 진행합니다.

- 계약, 단계 키, 추적 ID 규칙: [stage-contract.md](../plugins/corthex/skills/corthex/references/stage-contract.md)
- 각 단계의 여섯 칸, 진행 순서, 점검, 산출물 틀: 단계 스킬의 `references/<단계>.md`. 예: [02-prd.md](../plugins/corthex/skills/corthex-define/references/02-prd.md)
- `tests/test_stages.py`는 모든 단계가 여섯 칸을 채우는지, 단계 스킬이 자기 단계를 링크하는지, 단계 스킬들이 같은 진행 순서를 쓰는지, 진행 순서와 계약이 AI가 닿지 못하는 사람 화면의 규칙을 지키는지, 06·08·11·12단계가 모든 응답을 다루고 오류 코드를 한 목록에 두는지, 응답마다 화면 상태와 테스트 케이스를 잇는지, 운영 서버에서 테스트하지 않는지, 04·06·08·12단계와 계약이 같은 경우의 수 목록을 쓰는지, QA의 브라우저 에이전트 실행이 그 규칙을 지키고 QA 때마다 ego lite, Aside, Playwright 순서로 도는지, 리서치가 로그인이 필요한 페이지를 에이전트 브라우저로 열고 로그인은 사용자에게 맡기는지 검사합니다. 모든 단계에 기본 사람 화면이 있는지, 다른 도구를 고르면 결정으로 기록하게 하는지, MCP 서버를 어느 파일에서나 같은 방법으로 추가하는지, 09단계의 리졸버 예시가 스키마를 따르는지도 검사합니다.

06·08·11·12단계는 코드보다 먼저 쓴 API 계약을 기준으로 일합니다. 각 API 동작은 돌려줄 수 있는 응답(200, 401, 422 등)을 예시와 함께 모두 적고, 돌려줄 수 없는 응답은 그 이유를 적습니다. 오류는 모두 한 가지 모양(Problem Details, RFC 9457)에 한 목록의 오류 코드를 씁니다. 프런트엔드는 계약으로 만든 목 서버에 대고 먼저 만들고, 응답마다 보여 줄 화면 상태가 정해져 있습니다. 백엔드는 개발이나 스테이징 서버에서 계약 테스트로 계약과 맞는지 확인합니다. QA는 응답과 화면 상태마다 테스트 케이스를 쓰고, `API-001#401`, `SCR-002#permission`처럼 이름을 붙이며, 목록에 있는 응답 가운데 실제 서버가 일부러 돌려주게 할 수 있는 것은 모두 쏘아 보는 API 테스트를 저장소에 둡니다. QA를 할 때마다 프로젝트의 기존 테스트에 더해, 브라우저 에이전트가 ego lite를(ego lite를 쓸 수 없으면 Aside를) 몰고 localhost나 시험용 사이트에서 이번 변경이 닿는 사용자 흐름을, 출시 전에는 모든 흐름을 돌며 되는 것, 안 되는 것, 느낀 점을 보고합니다. 잘 되는 흐름은 풀 리퀘스트마다 도는 E2E 테스트로 고정합니다. 04·06·08·12단계는 권한과 입력부터 AI 답변까지 열두 가지 경우의 수 목록을 함께 써서, 기능 명세가 적은 경우마다 응답, 화면 상태, 테스트가 생기게 합니다.

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

Notion 기록은 프로젝트마다 기록 데이터베이스 하나에 둡니다. 여러 기록에 걸쳐 쫓는 결정과 할 일은 별도 항목 데이터베이스에 두고, 단계별 항목은 그 단계의 데이터베이스를 유지합니다. 기록 페이지는 데이터베이스의 한 행이고, 안의 표는 인라인 데이터베이스이며, 서술은 그 행의 본문에 씁니다. 프로젝트의 `records.location`이나 프로필의 `records.hub`가 기록 데이터베이스를 가리킵니다.

## 세션 시작 문맥

`corthex-memory` 0.2.1은 `scripts/hook.py`로 C1의 세션 시작·프롬프트·최종 답변·세션 종료 훅 네 개를 맡습니다. 새로 시작하거나 이어 열기·초기화·압축·갈라 내기를 할 때 시작 훅이 아래 기본 문맥과 허용된 C1 안내를 넣습니다. 동의와 켠 프로젝트가 있어야 기록하며 모델 정리·회상은 C2 작업입니다. 기본 문맥에는 이것이 들어갑니다.

- 일하는 원칙의 짧은 판. `tests/test_memory.py`가 입구 스킬의 목록과 같게 유지합니다.
- `~/.corthex/profile.json`의 프로필. 현재 프로젝트가 유효한 `ask_before` 목록을 주면 빈 목록을 포함해 프로필의 확인 목록을 대신합니다. 없으면 기본 `ask_before` 목록을 포함한 기본값을 알립니다. 파일이 있는데 읽을 수 없으면 그렇다고 알리고, 파일을 새로 만들어 덮어쓰지 말라고 한 뒤 기본값을 알립니다.
- 프로젝트: 저장소 루트까지 올라가며 찾은 가장 가까운 `.corthex/project.json`, 없으면 `~/.corthex/projects.json`에서 지금 폴더를 경로나 저장소로 가진 프로젝트. 단계마다 사람 화면, 정본, 원본을 알립니다. 이 기기의 다른 프로젝트는 이름만 적습니다.

기본 문맥 생성기는 이 로컬 파일들을 읽으며 네트워크에 연결하지 않습니다. C1 훅 실행은 아래에서 설명하는 기억 저장소 안에 허용된 가린 기록과 안전한 메타데이터를 씁니다. 훅은 없는 저장소를 만들지 않고 문맥 단계가 실패해도 세션은 평소대로 시작합니다.

- **저장소 설정은 정해진 형식만 보여 줍니다.** `project.json`은 아직 살펴보지 않은 저장소에서 올 수 있고, Codex는 훅 문맥을 개발자 메시지로 넣습니다. 그래서 이 파일에서는 공백 없는 짧은 ASCII 값만 보여 줍니다. 이름, 도구 이름, 경로, 링크, `truth` 값입니다. 예외인 `ask_before`의 유효한 행동 범주는 출처와 대체 규칙을 붙여 JSON 글자로 인용하고, 잘못된 목록이면 프로필 목록을 유지합니다. 긴 목록은 UTF-8 2,000바이트 안에서 보여 주며 행동 전에 파일의 전체 목록을 읽도록 알립니다. 저장소 데이터이며 사용자 지시나 되돌릴 수 없는 행동의 확인을 덮어쓰는 권한은 아닙니다. 다른 자유 글인 제목과 단계 메모는 보여 주지 않고, 메모가 있는 단계는 표시만 해서 에이전트가 파일에서 읽게 합니다. 형식에 맞지 않는 다른 값은 뺐다고 표시합니다. 프로필과 프로젝트 목록은 사용자 자신의 파일이므로 값마다 한 줄로 펴서 그대로 보여 줍니다.
- **크기.** 문맥은 UTF-8 8,000바이트 아래로 둡니다. Claude Code는 10,000자를 넘는 훅 문맥을 파일로 돌리고, Codex는 핸들러의 `additionalContextLimit`을 넘는 문맥을 그렇게 합니다. `hooks/hooks.json`은 이 값을 기본값 2,500 대신 8,000토큰으로 둡니다. 글자 하나도 토큰 하나도 1바이트 이상이므로 어느 도구도 문맥을 파일로 돌리지 않습니다. 설정이 더 크면 글을 자르고 잘랐다고 적습니다.
- **Codex는 신뢰를 묻습니다.** Codex는 `/hooks`에서 검토하고 신뢰한 플러그인 훅만 돌립니다. 설치한 뒤 한 번, 갱신으로 훅이 바뀌면 다시 신뢰합니다.
- **끄는 법.** 플러그인을 끄거나 지웁니다. Claude Code는 `claude plugin disable corthex-memory@corthex`를 실행합니다. Codex는 `~/.codex/config.toml`의 `[plugins."corthex-memory@corthex"]`에 `enabled = false`를 두거나 `codex plugin remove corthex-memory@corthex`를 실행합니다. 플러그인을 끄거나 지워도 기억 저장소는 남습니다. 기억 관리 명령으로 프로젝트를 끄거나, 보여 준 로컬 저장소 삭제를 확인합니다.
- **Windows.** 훅 명령은 둘입니다. `command`는 `python3`, `python`, `py` 실행기를 차례로 쓰도록 `||`로 잇습니다. Claude Code는 어느 체제에서나 이 명령을 돌리는데, Windows에서는 Git Bash로, Git Bash가 없으면 PowerShell로 돌리고 플러그인 폴더는 환경 변수로 넘깁니다. PowerShell 7은 `||`를 받지만 Windows PowerShell 5.1은 받지 않으므로, Windows의 Claude Code에서는 Git for Windows나 PowerShell 7이 있어야 합니다. 둘 다 없으면 훅이 실패하고 세션은 문맥 없이 시작합니다. Windows의 Codex는 그 대신 `commandWindows`를 돌리고, Git Bash가 있어도 늘 PowerShell로 돌립니다. PowerShell 7이 있으면 그것으로, 없으면 Windows PowerShell 5.1로 돌립니다. 이 명령은 5.1도 아는 `if ($LASTEXITCODE -ne 0)`로 `python` 다음에 `py -3`을 쓰고, Codex가 넣어 주는 `CLAUDE_PLUGIN_ROOT` 변수로 스크립트를 찾습니다.
- **지금까지 확인한 것.** 2026-10-23에 Linux에서 Claude Code 2.1.309와 Codex CLI 0.164.0을 격리된 설정과 로컬 가짜 모델 API로 돌려 확인했습니다.
  - 두 도구 모두 첫 모델 요청에 문맥이 실렸고, 프로젝트 파일의 제목과 메모는 실리지 않았습니다. Codex는 훅을 신뢰했을 때만 돌렸고, 시험에서는 검토 대신 `--dangerously-bypass-hook-trust`를 썼습니다.
  - 프로필을 바꾼 뒤 이어 연 세션(`claude -p --resume`, `codex exec resume`)과 갈라 낸 세션(`claude -p --resume … --fork-session`)에는 기록에 있던 예전 문맥과 함께 새 문맥이 실렸습니다.
  - Codex에서 28,872바이트짜리 시험 문맥은 `additionalContextLimit`을 8,000으로 두면 그대로 모델에 갔고, 두지 않으면 미리보기로 바뀌었습니다.
  - 2026-10-24에 Windows Server 2025 실행기에서 Claude Code 2.1.310, Codex CLI 0.164.0, 같은 가짜 모델 API로 확인했습니다(`.github/workflows/windows-hook-check.yml`). Git Bash가 있을 때와, Git Bash 없이 PowerShell 7만 있을 때는 두 도구 모두 모델에 문맥이 실렸습니다. Windows PowerShell 5.1만 있을 때는 `||` 명령을 읽지 못해 Claude Code는 문맥 없이 시작했고, Codex는 `commandWindows`로 문맥을 받았습니다.

  Codex의 세션 갈라 내기와 macOS는 아직 시험하지 않았습니다. 훅을 돌리는 셸의 PATH에 `python3`, `python`, Windows의 `py` 실행기 중 하나가 있어야 합니다.

## 기억 저장 라이브러리

아래는 TASK ID 순서로 C1을 만든 기록이며, 나중에 연결한다는 문장은 해당 구현 단계의 설명입니다. 현재 패키지에는 위에서 설명한 C1 훅과 관리 명령이 구현되어 있고 C2·C3는 계획 단계입니다.

C1은 `plugins/corthex-memory/skills/corthex-memory/scripts/memory_lib/`의 공용 라이브러리부터 만듭니다(TASK-001, TASK-002). 앞으로 만들 기억 스킬 안에 두면 스킬만 따로 복사해도 필요한 코드가 함께 가고, Agent Skills 규칙대로 링크도 그 폴더 안에 둘 수 있습니다. 앞으로 만들 `scripts/memory.py`는 옆의 `memory_lib`를 가져옵니다. 플러그인의 `scripts/hook.py`와 `scripts/worker.py`는 작업 폴더나 설치된 패키지 대신, 자기 파일의 실제 위치에서 플러그인 루트 아래 `skills/corthex-memory/scripts`를 찾아 같은 라이브러리를 가져오게 합니다. 라이브러리 복사본이나 전역 Python 설치가 필요하지 않습니다. 스킬 실행기와 훅·작업 프로세스의 가져오기는 해당 작업에서 더합니다.

`base.py`는 무작위 ID의 접두사 넷, UTC 시각과 날짜, C1 기록의 일정한 UTF-8 JSON 형식, 비공개 폴더와 파일, 저장소 위치, 모든 OS에서 같은 Windows 장치 이름 변환을 정합니다. `CORTHEX_MEMORY_HOME`을 찾거나 라이브러리를 가져오는 것만으로는 아무것도 만들지 않습니다. 저장소는 앞으로 만들 `on` 명령만 만들 수 있고, 파일을 쓰려면 부모 폴더가 이미 있어야 합니다. `files.py`는 JSONL 객체 하나를 한 번의 쓰기로 더하고, 손상된 줄을 넘기며 세고, 같은 폴더의 임시 파일과 백업으로 파일을 교체하고, 읽을 수 있는 백업을 복원하며, Windows 이동·삭제 재시도를 1초로 제한합니다. 읽기는 Windows 공유 오류를 1초 동안 다시 시도하되 옛 백업을 되살리지 않으며, 없거나 해석할 수 없는 내용만 호출자의 기록 잠금 아래에서 원본 재확인 뒤 복원합니다. 잠금 없는 읽기는 파일을 옮기지 않고 `RestoreNeeded`를 올립니다. `read_json()`과 `read_jsonl()`의 `holding_lock=True`는 호출자가 그 잠금을 쥔 동안만 쓰며, 추가는 없는 원본을 먼저 복원한 뒤 항목을 더합니다. `reading.py`가 잠금 없는 읽기의 짧은 잠금 시도를 연결합니다(TASK-003). 짧은 덧붙이기는 호출자의 기록 잠금 아래에서 fstat으로 잰 이전 크기로 되돌립니다. `delete_file()`은 파일 전체와 백업·임시 파일을 함께 지우며, macOS의 내구성 있는 쓰기는 `F_FULLFSYNC`를 먼저 시도하고 fsync로 돌아갑니다. 빈 저장소 경로 설정은 기본값을 쓰고 상대 경로는 경로 없는 구조화된 `configuration-invalid`를 올려 뒤의 훅·명령·상태 처리가 받게 합니다. 없는 폴더 루트는 끝없이 걷지 않고 곧바로 실패합니다. 안전한 알림을 전달해 뒤에 만들 실패 기록기가 경로나 오류 원문 없이 `damaged-line`과 그 수, `restored`를 남기게 합니다. 호출하는 쪽에서 먼저 기록을 가리고 검사하며, TASK-003의 잠금을 잡고, 로그를 다시 쓸 때 그동안 더해진 줄을 옮겨야 합니다. 다시 만들 수 있는 파일은 디스크 쓰기 확정과 백업을 생략합니다. C1 훅은 현재 분기 진입점에서 이 라이브러리를 사용합니다.

파일 시험은 임시 홈·저장소와 만들어 낸 ID·문장으로 TC-001–005와 TC-316–317을 검사합니다. 표의 순서와 바이트 일치, 경로와 권한, 손상되거나 잘린 줄, 강제로 끝낸 추가 프로세스, 교체 단계마다 멈춘 프로세스, 호출자의 기록 잠금 아래의 복원, 통째 삭제와 Darwin flush 분기의 모의 시험을 다룹니다. Windows 시험은 다른 프로세스가 대상을 열어 둡니다. 실제 기억 저장소나 호스트 설정은 읽지 않습니다.

Windows 폴더는 기본 생성 모드로 부모의 권한을 상속합니다. Python 3.13은 `mkdir(0700)`에 상속을 막은 ACL을 주므로 라이브러리는 POSIX에서만 0700을 요청합니다. Windows 시험은 임시 자식 폴더의 ACL 제어 플래그를 읽어 상속을 확인합니다([Python의 mkdir 계약](https://docs.python.org/3.13/library/os.html#os.mkdir)).

`memory_lib/locks.py`는 TASK-003의 파일 임대를 제공합니다. 배타적으로 만들며 `pid`, `device`, UTC `at`, 무작위 `token`을 기록하고, 05의 여섯 주기대로 수정 시각을 기준으로 만료와 백그라운드 갱신을 처리하며, 보호된 변경 직전에 토큰을 확인합니다. 오래된 잠금은 전용 `.stale` 이름으로 옮긴 뒤 파일의 동일성·토큰·만료를 다시 확인합니다. 경쟁 중에 새로 생긴 잠금이면 하드링크나 배타적 복사로 복원해 더 새로운 잠금을 덮지 않습니다. 갱신은 연 파일 기술자(Windows에서는 표준 라이브러리로 얻은 네이티브 파일 핸들)의 시각을 바꾸므로 경로가 교체되어도 다른 파일을 건드리지 않습니다. 한 프로세스의 스레드 전체에서 기다리는 획득도 포함해 순서를 지키고 fork 뒤에는 그 기록을 비웁니다. 같은 종류에서는 기억 폴더의 상대 경로 문자열 순서로 잡고 Windows의 대소문자를 가리지 않습니다. 물려받은 임대는 인스턴스 뮤텍스를 잡기 전에 자식 PID를 거부하므로 사라진 부모 스레드 때문에 확인·갱신·해제가 멈추지 않습니다. 호출하는 쪽이 단조 시계의 유한한 기한을 주고 기다리지 않는 한 번의 시도를 고를 수 있습니다. 즉시 인수는 사용자 확인을 받은 전체 삭제·프로젝트 삭제에서만 요청합니다. 뒤에 만들 적용·지운 기록 확인이나 추가된 줄 보존을 이 임대가 대신하지 않습니다. TC-006–008과 TC-318은 실제 프로세스로 검사하며 수정 시각을 앞당겨 수 분을 기다리지 않고 만료를 시험합니다. 훅과 명령 연결은 여전히 뒤의 작업에서 합니다.

`memory_lib/reading.py`는 JSON·JSONL·사용자 해석기 읽기를 임대 없이 먼저 시도하고, 읽을 수 있는 백업의 복원만 해당 기록 임대 아래 다시 확인합니다. 일반 호출자는 절대 기한 안에서 잠금을 잡고 확인·읽기·이동을 마칩니다. 기록 길만 TASK-060의 선택 인자를 켜, 지우기 처리 뒤 50ms를 잠금 기다림에 쓰고 기한 뒤에도 한 번 시도하며 획득 뒤 복원을 마칩니다. Windows 공유 위반은 보통의 1초 재시도를 쓰고 변경 전에는 토큰과 기기를 확인합니다. 다른 호출자와 기한 뒤 진단의 배타적 만들기 한 번은 바꾸지 않습니다. 잠금 획득 실패는 원본·백업을 그대로 두며 해제는 독립적인 1초 재시도로 끝난 읽기의 결과를 지킵니다. 훅은 다른 임대 없이 복원 잠금만 잠시 잡습니다.

`memory_lib/configuration.py`는 TASK-004의 엄격한 오프라인 설정 검사와 적용할 기본값을 제공합니다. 함께 담는 `configuration.schema.json`은 06의 스키마와 바이트까지 같음을 시험하므로 저장소의 docs 없이도 스킬을 옮길 수 있습니다. 검사기는 지원하지 않는 스키마 키워드와 원격 참조를 거절합니다. 기본값과 호스트에서 얻은 임시 기기 여부는 원문과 따로 두며, 동의가 없거나 동의 버전이 맞지 않거나 프로젝트가 꺼져 있으면 기록을 켜지 않습니다. 잘못된 필드는 값과 동적 맵의 키를 빼고 일정한 경로로 알립니다. JSON Schema의 정수에는 `1.0`처럼 소수 부분이 없는 유한한 수도 들어가며, 적용할 정수 필드는 Python 정수로 바꿉니다.

`memory_lib/store.py`는 설정에 접근하기 전에 `store.json`을 읽고 검사하며, 읽을 수 있는 백업을 복원하고, 모르는 형식·진행 중인 이동·복원할 수 없는 정보에서는 저장소의 다른 접근을 막습니다. 내용을 해석할 수 없는 새 형식의 정보를 옛 백업으로 되돌리지 않으며, 스키마에 맞지 않는 설정도 백업에서 옛 동의를 되살리지 않습니다. 설정 쓰기는 저장소 임대를 잡고 파일 이동의 재시도까지 공유 파일의 변경 전에 토큰과 기기 ID를 확인합니다. `memory_lib/diagnostics.py`는 TASK-005의 날짜별 실패 줄과 훅 소요 시간을 각각의 기록 임대 아래 제공합니다. 정해 둔 코드나 내장 예외 종류와 검사한 정보만 받아 오류 원문이나 경로를 남기지 않고, 폴더를 만들지 않으며, 기한이나 임대를 잃으면 쓰기를 넘깁니다. 호출하는 쪽은 여전히 동의와 켠 프로젝트를 확인하고 훅 시작 시각을 넘겨야 합니다. 차단된 저장소에서는 진단을 읽거나 쓰지 않으며, 명령이 `store-newer` 또는 `store-damaged`를 돌려주고, 읽을 수 있는 저장소 백업은 복원한 뒤에야 `restored`를 기록할 수 있습니다. 이 시험들은 라이브러리와 출력 없이 끝나는 하위 프로세스 호출을 검사하며, C1 훅과 명령 연결은 뒤의 작업에서 합니다.

저장소 읽기는 호출자의 절대 작업 기한을 필수로 받습니다. 복원은 공개 읽기·파일 파서 함수와 store.lock을 쓰며, 이미 그 임대를 쥔 호출자는 이를 명시해 넘깁니다. 권한·다른 운영 입출력 오류는 명령의 internal 처리를 위해 올리고, 복원할 수 없는 없거나 해석 불가인 기록만 store-damaged입니다. RuntimeError인 RestoreNeeded를 명시해 처리하며, 잠금 경합은 lock-busy로 남습니다.

진단의 저장소 읽기와 복원은 로그 임대를 잡기 전에 끝냅니다. 임대 안에서는 원본을 읽거나 되살리지 않고 파일 동일성·크기·수정 시각을 확인해 기한·토큰·변경 방어를 유지합니다. LockBusy·LostLock 예외와 클래스 이름 알림은 lock-busy·lost-lock으로 바꾸고, 다른 이름은 기존 고정 코드·내장 예외 규칙을 따릅니다. 설정·소요 시간 임대의 해제 실패는 호출자 기한이 허용하면 실패 기록기에 넘기며, 실패 기록 자체의 해제는 재귀 알림을 하지 않습니다.

설정 패턴은 엔진에 따라 뜻이 갈리지 않는 문자 집합을 쓰며 가격 페이지 주소는 ASCII 인쇄 글자로 받습니다. Node ECMA-u 대조 시험은 Python과 같은 경계값을 확인합니다. TC-011·012·014는 통과한 라이브러리 증거를 남기되 훅·status 진입점 작업에서 실행할 때까지 실행 전입니다. 실패 기록기는 작업 프로세스의 코드 문자열 lost-lock도 받으며 추가 모델·동기화 코드는 뒤 작업에 남깁니다.

복원 읽기는 선택적으로 잠금 획득 뒤와 이동 전에 호출자 상태를 다시 확인합니다. 설정 복원은 잠금 아래 설정을 읽기 전에 저장소 차단 상태와 임대 기기를 검사하며, 헤더 백업의 기기가 달라졌으면 복원하기 전에 거절합니다. 날짜별 진단 덧붙이기·복원·열기 재시도에는 Windows 백업 공유 오류까지 원래의 절대 기한을 넘깁니다.

`memory_lib/projects.py`는 사용자의 프로젝트 목록과 폴더 정보만으로 TASK-006을 준비합니다. 세션 폴더와 등록한 기본·저장소 폴더의 실제 경로를 구하고, 세션의 실제 상위 폴더를 깊은 곳부터 보며, 철자나 대소문자 변환 없이 장치·파일 동일성을 비교합니다. 이기는 폴더를 두 프로젝트가 함께 쓰면 `project-clash`이며, 한 프로젝트의 별칭들은 주인 하나입니다. `find()`는 현재 동의와 켠 프로젝트도 요구하므로 꺼진 하위 프로젝트에서 켠 상위 프로젝트로 넘어가지 않습니다. `locate()`는 뒤에 만들 보관 기간 작업 프로세스의 판단을 위해 등록된 일치를 남깁니다. 없거나 읽을 수 없는 목록은 `no-project-list`이며 저장소 안의 프로젝트 설정은 열지 않습니다. 제외는 종류와 프로젝트의 기본 폴더에 상대적인 폴더를 쓰고 폴더 동일성으로 확인하며, 없는 제외 폴더를 만들지 않고 그 폴더가 생기면 적용합니다. 호출자는 먼저 저장소·설정을 확인하고 안전한 오류를 진단에 넘겨야 합니다. 기존 프로젝트 목록은 옛 읽기와 같이 UTF-8 BOM 하나를 받으며 기억 저장소 JSON은 엄격한 UTF-8 그대로입니다. 이름 문자열이 규칙에 맞지 않는 항목도 폴더 맞춤에 참여하며, 가장 깊은 항목의 이름이 잘못됐으면 켠 부모로 넘어가지 않고 프로젝트 없음입니다.

`memory_lib/redaction.py`는 06의 순서대로 TASK-007의 여섯 단계를 준비합니다. (1) 짝 없는 서로게이트를 U+FFFD로 바꾸고 올바른 쌍을 보존하며 정규화한 UTF-8 바이트를 세고 520KiB 여유 구간으로 자르기, (2) ASCII 대소문자를 가리지 않는 비공개 구간, (3) 개인 키 블록, (4) 같은 정규화를 적용해 긴 값부터 처리하는 12자 이상 환경 값의 정확한 일치와 기억 전용 키의 별도 표시, (5) 정본 패턴, (6) 마지막 512KiB 글자 경계 자르기입니다. 여유 구간이 원문을 잘랐으면 6단계는 원문 512KiB 지점 뒤에서 온 출력을 먼저 버리고 그 앞에서 시작한 표시는 남깁니다. 앞 단계가 줄여도 불확실한 여유 구간 조각이 기록에 들어오지 않습니다. 원문을 자르지 않았으면 기존 마지막 자르기를 유지합니다. 어느 단계든 잘랐으면 cut은 1단계의 자르기 전 정규화한 바이트 수입니다. 오류는 전파하며 뒤 호출자는 실패한 원문을 쓰거나 보내면 안 됩니다. 변환기 자체는 쓰기·보내기·기록을 하지 않습니다. BEGIN과 END의 개인 키 이름 칸은 각각 40자까지이고 JWT는 앞 글자가 base64url 알파벳 밖이어야 합니다. 코드 패턴은 06 영·한과 바이트까지 같습니다. 시험의 키 모양 값은 메모리에서만 만듭니다. tests/bench_memory_redaction.py는 확인한 각 OS/Python에서 입력마다 정확히 UTF-8 524,288바이트를 빈 환경으로 처리하며 준비 한 번 뒤 호출 전체를 열 번 잽니다. 이름·수·중앙값·최댓값만 내보냅니다. 느린 입력 넷은 개인 키 BEGIN·END 이름, eyJ 반복, 점 없는 base64 JSON입니다. import와 입력 만들기는 제외합니다. 크기 증가 시험은 여유 구간이 증가를 가리지 않게 패턴을 확인하며 훅 전체 기한은 뒤 통합 QA에서 봅니다. 0.1.0 바탕 요약 생성기는 유지합니다.

`memory_lib/raw_log.py`는 TASK-008의 호스트·세션별 덧붙이기와 턴 표지에 TASK-060의 완료 규칙을 적용합니다. 한 번 가린 뒤 시작하는 50ms는 원문·저장소 기록 복원 잠금 기다림에만 쓰고, 기한 뒤에도 잠금마다 한 번은 시도합니다. 원문 임대를 잡으면 끝 줄·덧붙이기·표지를 훅 기한 뒤에도 마칩니다. 뒤에서 8MiB까지만 새 블록을 나누고 조각을 한 번 이어 읽으며 블록·줄마다 임대·헤더를 열지 않습니다. 원문 파일이 없으면 백업도 같은 한도로 읽고 기존 잠금 아래 다시 확인과 변경 직전 방어를 거쳐 복원합니다. 빈 파일은 seq 1입니다. 완전한 양의 seq 줄이 없고 창이 파일 처음에 닿지 않으면 쓰지 않고 damaged-line/error이며, 파일 전체를 읽었으면 새 줄에서 seq 1부터 쓰고 손상을 건너뛰고 세며 ok를 돌려줍니다. 완전한 seq 줄이 있으면 해석 가능한 잘린 끝·턴 형식이 잘못된 줄의 seq도 재사용하지 않습니다. 턴을 잇는 항목이 범위 안에 없으면 답은 새 턴입니다. 공유 변경의 열기·쓰기·되돌리기·표지 생성 직전에 임대와 저장소 동일성을 확인하며 Windows 공유 위반에는 보통의 1초 재시도를 씁니다. 새 턴 표지는 배타적으로 만들고, 붙는 답은 알려진 표지를 바로 확인하거나 이름 목록으로 찾습니다. 기록 결과에는 deadline이 없고 남의 잠금을 얻지 못하면 lock-busy입니다. 반환한 덧붙이기는 표지 실패에도 남습니다. 알림은 임대를 놓은 뒤 호출자가 기록하며 폴더를 만들지 않습니다. TC-029–032, TC-322–324와 TC-326은 실제 쓰기 중단·경합, 늦은 완료, 첫 시도와 크기 한도를 확인합니다.

`memory_lib/start_memory.py`는 훅 분배와 독립적으로 TASK-013·014를 준비합니다. 생성기는 기본 글, 종류가 붙은 알림 글, 고정 순서로 고른 현재 항목과 TBL-013 줄 값을 받아 요약 전체와 보여 준 핀 ID를 돌려줍니다. 상태·핀·항목 파일은 열지 않습니다. 출력의 마지막 관문에서 항목·인용 ID와 항목의 종류·말한 이를 검사하고 잘못된 값은 자리 개수에 세지 않고 뺍니다. 상태 인용은 올바른 항목 ID 처음 셋만 보입니다. 항목·상태의 짝 없는 서로게이트는 가리기처럼 바꾸고 Cf는 보존합니다. 알림 종류는 06 표 순서이며, 읽을 수 없는 기억은 한 줄짜리 절 하나만 냅니다. 개수 줄까지 자리에 세며 현재 상태와 오래된 핀을 기본 글보다 먼저 빼고, 기억 부분은 4,000바이트·요약 전체는 7,999바이트 이하입니다. C1 알림 선택은 기존 저장소 기록·설정 읽기와 정제된 첫 오류 필드를 사용합니다. configuration.CONSENT_VERSION 하나를 동의 검사와 알림이 같이 씁니다. context.shorten과 build_context는 바이트 한도를 받되 기본값 8,000에서는 0.1.0 출력을 바이트까지 유지합니다. build_context(limit=None)이 원래 기초를 주며 build_summary는 줄임 표시가 붙은 기초를 거부하고 기존 방식으로 한 번만 자릅니다. 훅 연결·기한 초과 줄·시작 경계·작업 프로세스는 TASK-017에서 합니다. tests/bench_memory_start_memory.py는 상태 10,000바이트, 최대 크기 글의 핀 50개, 알림 일곱 개와 기본 글 7,000바이트로 생성 전체와 새 인터프리터의 import를 따로 재며 수치 메타데이터만 냅니다.

`memory_lib/context.py`는 0.1.0 바탕 요약 생성기를 담습니다. 현재 scripts/hook.py는 memory_lib/hooks.py로 문서의 네 이벤트를 나눕니다. 입력은 BOM 하나를 허용하는 엄격한 UTF-8의 JSON 객체 하나입니다. 호스트는 플러그인 폴더 ID, CLAUDECODE, turn/prompt 필드 순으로 판별합니다. 진단보다 저장소 기록을 먼저 확인하며 bad-input·unknown-host는 동의 없이도 실패 기록을 남길 수 있지만 원문·표지·훅 시간의 켠 프로젝트 문턱은 유지합니다. 기록만 하는 훅은 네트워크 클라이언트나 SQLite를 읽지 않습니다. 기한 뒤 진단은 미리 확인하고 다시 맞춘 저장소 ID와 로그 잠금의 배타적 만들기 한 번, 이미 지난 파일 작업 기한을 써 새 예산을 두지 않습니다. 늦은 실패도 본래 코드를 유지하며, finish는 받은 결과를 바꾸지 않고 ms로 늦음을 보입니다. 훅은 진단을 부르기 전부터 기한 뒤 시도를 허용하므로 저장소 확인이나 잠금 생성 중 기한이 지나도 기다리지 않는 획득 시도 한 번과 획득한 임대 아래 줄 하나를 마칩니다. 바쁜 늦은 잠금은 낡은 잠금 넘겨받기나 새 예산 없이 건너뛰며 일반 진단 호출자의 기한은 엄격하게 유지합니다. run은 기한이 지났어도 process를 부릅니다. 훅 전체 기한은 가리기·기록을 건너뛰지 않으며, 뒤 단계가 06 기한 표의 일을 실제로 건너뛰거나 줄였을 때만 deadline을 명시적으로 돌려줍니다. 해제의 별도 다시 시도는 유지하고 TC-321으로 경합과 저장소 변경을 시험합니다. TASK-010–012가 프롬프트·최종 답변·종료 경계 기록을 공통 처리기에 연결합니다. 프롬프트는 기록 제외 여부보다 먼저 한 번 가리고, 답변 없음과 답변·경계 제외는 먼저 끝냅니다. 훅 기한이 지난 뒤 단계에 닿아도 가리기·기록을 하며, 끝난 C1 기록은 받은 결과를 유지합니다. 회상·정리 시작 조건·작업 프로세스 시작은 후속 작업에 둡니다. 공통 처리기는 저장소나 프로젝트 폴더를 만들지 않습니다. 기록의 50ms는 잠금 기다림에만 쓰며, raw/나 unprocessed/가 사라지면 폴더를 만들지 않고 클래스 이름 실패 줄만 남기고 훅 시간은 쓰지 않습니다.


기록 훅은 원문 임대를 놓은 뒤 알림 목록을 받아 진단을 기록합니다. 원문 라이브러리의 선택적인 알림 수집 인자는 기존 라이브러리 호출의 기록 동작을 유지하며, 훅이 실패 뒤에 남길 진단과 남은 단계를 정하게 합니다.

기한과 훅 경과 시간은 `memory_lib/clock.py`의 `now()`가 `time.perf_counter()`로 잽니다. 진입점은 제품 모듈을 불러오기 전에 같은 카운터의 첫 값을 잡아 그 불러오기 비용도 포함합니다. UTC 시각과 임대의 오래됨 판정은 기존 벽시계를 유지합니다.

## 프로젝트 허브

`corthex-nexus` 0.2.2에는 스킬 `corthex-hub` 하나와 스크립트 `scripts/hub.py` 하나가 있습니다. 프로젝트마다 이미 있는 파일로 모든 프로젝트를 한 페이지에 모으고, 서버는 쓰지 않습니다. 선택 사항인 NEXUS 서버와 브라우저 화면은 [제품 저장소](https://github.com/kodonghui/corthex-nexus)에 있고, 허브 플러그인은 여기에 남습니다.

- **스냅샷.** `~/.corthex/projects.json`의 프로젝트마다 `.corthex/project.json`이 가리키는 단계별 원본을 읽습니다. 프로젝트의 다른 저장소에 있는 원본도 읽습니다. 그 원본이 정의하고 잇는 것을 저장합니다: 추적 ID와 제목·항목 값, 각 ID가 있는 파일과 줄, ID 사이의 링크, 점검 결과. 프로젝트는 등록된 이름으로만 읽습니다. `.corthex/project.json`이 다른 이름을 적었거나, 등록되지 않은 폴더가 등록된 프로젝트의 이름을 적었으면 아무것도 읽지 않고 이유를 알리므로, 저장소 설정으로 자기 항목을 다른 프로젝트 이름으로 저장하거나 보낼 수 없습니다. 글자만 읽고 프로젝트 코드를 실행하지 않습니다. Git은 PATH의 절대 경로 폴더에서만 찾고 현재 폴더에서는 찾지 않으며, 저장소의 fsmonitor 훅, clean 필터, 선택적 잠금 없이 돌리고 하위 모듈 안은 보지 않으므로, 저장소 상태를 읽어도 그 저장소의 프로그램을 띄우거나 무엇을 다시 쓰지 않습니다. 추적 중인 파일이 Git LFS 같은 clean 필터를 쓰면, 스냅샷은 작업 트리에 바뀐 것이 있는지 적지 않습니다. 이름이 비밀값처럼 보이는 파일과 그런 이름의 폴더 안에 있는 파일은, 링크로 이어져도 건너뜁니다. `spec.md` 옆의 `spec.ko.md`처럼 원문 옆에 둔 번역이 원문의 ID만 정의하면 그 번역도 건너뛰어, 같은 ID를 두 번 정의하지 않습니다. 읽는 형식과 점검은 [reading.md](../plugins/corthex-nexus/skills/corthex-hub/references/reading.md)에 있습니다.
- **진행 상태.** 단계의 상태, 마지막 확인 지점, 다음 행동은 `hub.py status`로 기록한 것만 씁니다. 파일이 있다고 단계가 끝난 것은 아니기 때문입니다. `done`은 확인 지점과 그 날짜 없이는 기록하지 않습니다. 검토에서 찾은 점도 같은 방법으로 기록합니다.
- **페이지.** `hub.py build`가 `~/.corthex/hub/index.html`을 씁니다. 프로젝트마다 13단계의 상태와 개수, 점검 결과, 단계별 설정과 항목, ID마다 앞뒤로 이어진 항목을 보여 주는 추적 화면, 검색이 있습니다. 자료는 페이지 안에 들어 있고, 콘텐츠 보안 정책이 모든 요청을 막으며, 글은 글로만 보여 줍니다. 그래서 디스크에서 바로, 오프라인에서도 열립니다. 언어는 프로필을 따라 한국어나 영어로, 밝은 화면과 어두운 화면은 시스템 설정을 따릅니다. `~/.corthex/projects.json`에서 빠진 프로젝트의 저장된 스냅샷은 디스크에 남지만 페이지에는 넣지 않습니다.
- **기기 밖으로 나가는 것.** 사용자가 허용한 서버·프로젝트의 `hub.py push`만 자료를 보냅니다. 0.2 자료에는 ID·제목·필드·검사·저장소 기준 위치·커밋뿐 아니라 허용한 도메인/SQL/사이트맵 그림 원본과 단계 기록이 포함됩니다. 정제 규칙에 맞는 비밀값·이메일은 가리고 로컬 절대 경로와 그 밖의 파일은 넣지 않습니다. 알려지지 않은 비밀 형식을 완전히 차단한다고 주장하지 않습니다. 첫 실제 보내기는 별도 확인하며 형식과 상한은 [snapshot.md](../plugins/corthex-nexus/skills/corthex-hub/references/snapshot.md)를 따릅니다.
- **보내기.** `hub.py push`는 프로필의 `nexus.push`에 적은 프로젝트의 스냅샷만 `nexus.url`로 보냅니다. HTTPS를 쓰고, Cloudflare Access 서비스 토큰은 환경 변수에서 읽습니다. 리다이렉트를 따라가지 않아서, 토큰이 거절되면 다른 곳으로 보내지 않고 알립니다. 서버가 스냅샷을 거절하면 서버가 밝힌 이유를 보여 줍니다. `hub.py remove`는 서버에서 프로젝트를 지웁니다.
- **서버.** 제품 저장소가 Access·Tunnel 뒤의 Node/SQLite 실행부와 Worker/D1 호환 빌드를 맡습니다. `hub-ref.json`으로 이 허브의 정확한 커밋을 고정하고 실제 연결과 페이지 양식 일치를 검사합니다. 배포·운영: [NEXUS](https://github.com/kodonghui/corthex-nexus/blob/codex/nexus-0.2/nexus/README.ko.md).

지금까지 확인한 것: `tests/test_hub.py`는 단계 스킬의 산출물 틀 그대로 프로젝트를 만들고, 허브가 거기서 읽은 항목, 링크, 점검 결과를 모두 확인합니다. 이어서 원본 형식마다, 진행 기록 파일, 페이지, 로컬 가짜 서버를 상대로 한 보내기를 확인합니다. Linux의 Python 3.8과 3.13에서 통과합니다. 페이지는 Chromium에서 1440과 320픽셀 폭, 밝은 화면과 어두운 화면으로 열어 스크립트 오류, 가로 스크롤, 네트워크 요청이 없는 것을 봤습니다. 저장소 세 곳에 나뉘고 요구사항을 Notion에서 내보낸 실제 프로젝트도 바꾸지 않고 읽었습니다. Windows와 macOS는 아직 돌려 보지 않았습니다.

기존 서버·Worker 검증 이력은 제품 저장소에 보존합니다. 현재 서버·계약·화면 검사는 `kodonghui/corthex-nexus`에서 하고 Linux·Windows·macOS 허브 호환성은 여기에서 검사합니다.



0.2에서는 보내기 자료를 최신으로 가져온 기본 브랜치의 Git 객체에서 만들고, 허용한 도메인·SQL·사이트맵 원본과 부분별 저장소 단계 기록을 포함합니다. 프로젝트 자료를0.1의 항목 목록만이라고 설명하지 않습니다. 원본·항목·검사·1,000,000바이트 상한과 정제 규칙은 허브 형식 문서를 따릅니다. `.corthex/stages/PART.json`과 기기 기록의 우선순위를 지키고, 명시한 컨텍스트·용어·terms:none과 제외 용어를 그림 교차 점검에 씁니다. 실제 사용자 승인 없이 상태를 완료로 바꾸지 않습니다.

핵심0.7 스킬의 선택적 NEXUS 절차는 프로젝트당 세션 한 번의 할 일 읽기, 사용자 요청 우선, 점유와 PR 보류, 의견 결정·제안 반영·단계 기록·철회 확인을 가르칩니다. 스킬만 쓰며 자동 네트워크 훅을 추가하지 않습니다. PR C의 유효한 프로젝트 ask_before가 프로필 목록을 대체하는 규칙을 그대로 적용하고 기존 명시적 승인과 되돌릴 수 없는 작업의 경계를 보존합니다. 부분을 나누거나 저장소를 옮길 때는 각 원본의 확인된 기록만 보존합니다. NEXUS 제품 원본과 기록은 별도 저장소에 두고 MEMORY의 기록을 덮어쓰지 않습니다.

위의 Windows/macOS 미실행 문장은 초기0.1 검증 이력입니다. 2026-11-04 CLI 보완은 PR117의59명명 메서드를 세 OS/Python 양끝6셀에서 확인했고 build3개는 별도 PR118의6메서드×6셀에서 확인했습니다. 실제 사용자·서버·전체 원래 인수 범위는 각 실행 보고서에서 별도로 판정합니다.

## 버전과 릴리스

- 버전은 유의적 버전을 씁니다. 버전은 두 매니페스트와 모든 스킬의 `metadata.version`에 있고, 검사가 셋을 같게 유지합니다.
- 릴리스는 `<플러그인>--v<버전>` 이름의 Git 태그입니다. 예: `corthex--v0.1.0`. `claude plugin tag`가 매니페스트와 마켓플레이스 항목이 맞는지 확인한 뒤 태그를 만듭니다.
- 사용자는 각 도구의 마켓플레이스 명령으로 갱신을 받습니다.

## 검사

| 검사 | 명령 | 범위 |
| --- | --- | --- |
| 저장소 검사 | `python -m unittest discover -s tests -v` | 매니페스트와 마켓플레이스, 스킬 형식, 단계 계약, 기억 훅과 그 스크립트, 허브 스크립트와 페이지와 보내기, `corthex-uxui`의 스크립트(FFmpeg가 있으면 만든 영상으로), `hub.py`, 설명서 링크와 번역 짝, 비밀값과 개인 정보 |
| Claude Code 검증 | `claude plugin validate --strict .` 다음 플러그인마다 `claude plugin validate --strict plugins/<플러그인>` | 마켓플레이스와 플러그인에 대한 Claude Code 자체 스키마 |

CI는 모든 풀 리퀘스트와 `main`에 올라오는 모든 push에서 저장소 검사와 서버 검사를 Linux, Windows, macOS에서, Claude Code 검증과 서버의 Wrangler 빌드를 Linux에서 돌립니다. Linux와 Windows에는 FFmpeg를 설치해 미디어 점검을 만든 영상으로 돌리고, macOS에서는 그 검사를 건너뜁니다. `corthex-memory`나 Windows 훅 검사를 바꾸는 풀 리퀘스트는 Windows에서 Claude Code와 Codex로 기억 훅도 돌립니다. Git Bash가 있을 때, PowerShell 7만 있을 때, Windows PowerShell 5.1만 있을 때를 로컬 가짜 모델 API로 돌립니다.

## 앞으로

0.1.0에는 없고 계획만 있습니다. 둘 다 핵심 플러그인에 넣지 않는 구성 요소가 필요합니다.

- `corthex-memory`의 다음 판: 대화 기록을 모아 프로젝트마다 현재 상태로 정리하고, 필요한 것을 다시 꺼내는 훅. 그 현재 상태도 세션 시작 문맥에 넣습니다. 요구사항: [docs/02-prd/memory.ko.md](02-prd/memory.ko.md). 사용자 흐름: [docs/03-user-flow/memory/](03-user-flow/memory/README.ko.md). 기능 명세: [docs/04-functional-spec/memory.ko.md](04-functional-spec/memory.ko.md). 기억 폴더: [docs/05-erd/memory.ko.md](05-erd/memory.ko.md). 인터페이스: [docs/06-api/memory.ko.md](06-api/memory.ko.md). 작업 분해: [docs/10-wbs/memory.ko.md](10-wbs/memory.ko.md).
- `corthex-nexus`의 다음 판: 요구사항 [docs/02-prd/nexus.ko.md](https://github.com/kodonghui/corthex-nexus/blob/codex/nexus-0.2/docs/02-prd/nexus.ko.md)로 정합니다. NEXUS 서버의 사이트맵·유저 플로우 편집 화면과 같은 자료를 쓰는 MCP 서버는 거기서 후보입니다(결정 D5). 기억을 여러 기기에서 함께 쓰게 되면 서버 저장소를 D1에서 Postgres로 옮길 수 있습니다.

## 근거

2026-10-23에 확인했습니다.

- Claude Code: [Plugin manifest reference](https://code.claude.com/docs/en/plugins/manifest-reference), [Marketplace reference](https://code.claude.com/docs/en/plugins/marketplace-reference), [Plugin dependencies](https://code.claude.com/docs/en/plugins/dependencies), [Publish and distribute a plugin](https://code.claude.com/docs/en/plugins/publish), [Skills](https://code.claude.com/docs/en/skills)
- OpenAI: [Codex plugins](https://developers.openai.com/codex/plugins/build), [Submit your Claude Code plugin to OpenAI](https://developers.openai.com/plugins/guides/submit-claude-plugin), [Build skills](https://learn.chatgpt.com/docs/build-skills)
- Agent Plugins: [Plugin manifest](https://agent-plugins.org/plugin-authors/manifest), [Client extensions](https://agent-plugins.org/plugin-authors/client-extensions), [Compatible clients](https://agent-plugins.org/compatible-clients)
- 훅: [Claude Code hooks reference](https://code.claude.com/docs/en/hooks), [Codex hooks](https://learn.chatgpt.com/docs/hooks), [openai/codex#39895](https://github.com/openai/codex/issues/39895)
- Cloudflare Access: [Authenticate agents](https://developers.cloudflare.com/cloudflare-one/access-controls/authenticate-agents/), [Service tokens](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/)
- Cloudflare Workers와 D1: [Cloudflare Access for Workers](https://developers.cloudflare.com/workers/configuration/cloudflare-access/), [Custom Domains](https://developers.cloudflare.com/workers/configuration/routing/custom-domains/), [Workers limits](https://developers.cloudflare.com/workers/platform/limits/), [D1 limits](https://developers.cloudflare.com/d1/platform/limits/)
- [Agent Skills specification](https://agentskills.io/specification)
