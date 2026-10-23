# 구조 설명

[English](architecture.md)

CORTHEX가 어떻게 짜여 있고 왜 그렇게 했는지 설명합니다. 파일 형식은 입구 스킬의 참고 문서에 한 번만 정의되어 있고, 이 문서는 그 내용을 되풀이하지 않고 링크합니다.

상태: 0.1.0. 핵심 플러그인 `corthex`와 `corthex-memory`의 첫 부분인 세션 시작 문맥이 있습니다. `corthex-memory`의 나머지와 `corthex-nexus`는 계획 중입니다([앞으로](#앞으로) 참고).

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
│   └── corthex-memory/                  세션 시작 문맥, 훅이 있음
│       ├── .claude-plugin/plugin.json   Claude Code용 매니페스트
│       ├── .codex-plugin/plugin.json    Codex용 매니페스트, 루트 plugin.json은 없음
│       ├── hooks/hooks.json             세션 시작 훅 하나, 두 도구가 함께 읽음
│       ├── scripts/session_start.py     문맥을 만듦, Python 표준 라이브러리만 씀
│       ├── context/principles.md        일하는 원칙의 짧은 판
│       └── LICENSE, NOTICE
├── tests/                               검사, Python 표준 라이브러리만 씀
└── docs/
```

## 매니페스트 둘, 스킬 한 벌

Claude Code는 플러그인 매니페스트를 `.claude-plugin/plugin.json`에서 읽습니다. Codex와 다른 Agent Plugins 클라이언트는 플러그인 루트의 `plugin.json`을 읽고, Codex는 그 파일의 `extensions.com.openai`에서 자기 설정을 가져갑니다. Agent Plugins 1.0의 호환 클라이언트 목록에 Claude Code가 없어서 두 파일을 함께 둡니다. `skills/` 폴더는 하나를 같이 씁니다.

훅이 든 플러그인은 예외입니다. Codex CLI 0.164.0은 플러그인 루트에 `plugin.json`이 있으면 `.codex-plugin/plugin.json`을 함께 둬도 그 플러그인의 훅을 돌리지 않습니다([openai/codex#39895](https://github.com/openai/codex/issues/39895), 2026-10-23에 재현). 루트 `plugin.json`이 없으면 Codex는 `.codex-plugin/plugin.json`을 읽고 `hooks/hooks.json`을 스스로 찾습니다. 그래서 `corthex-memory`는 `.claude-plugin/plugin.json`과 `.codex-plugin/plugin.json`을 두고 루트 `plugin.json`은 두지 않습니다. 이 때문에 다른 Agent Plugins 클라이언트에는 가지 않고, OpenAI 디렉터리는 원래 훅이 든 플러그인을 받지 않습니다.

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

기억 플러그인도 같은 방식으로 `corthex-memory@corthex`를 설치합니다. 이 플러그인은 `corthex`를 의존 플러그인으로 밝혀 두어 Claude Code는 둘을 함께 설치하고, Codex에서는 둘을 모두 추가합니다.

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

- 계약, 단계 키, 추적 ID 규칙: [stage-contract.md](../plugins/corthex/skills/corthex/references/stage-contract.md)
- 각 단계의 여섯 칸, 진행 순서, 점검, 산출물 틀: 단계 스킬의 `references/<단계>.md`. 예: [02-prd.md](../plugins/corthex/skills/corthex-define/references/02-prd.md)
- `tests/test_stages.py`는 모든 단계가 여섯 칸을 채우는지, 단계 스킬이 자기 단계를 링크하는지, 단계 스킬들이 같은 진행 순서를 쓰는지 검사합니다.

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

`corthex-memory` 0.1.0에는 훅이 하나 있습니다. 세션이 시작될 때, `/clear` 뒤, 문맥 압축 뒤에 `scripts/session_start.py`가 짧은 문맥을 넣습니다. 이어 하는 세션과 갈라 낸 세션은 기록에 이미 들어 있어 건너뜁니다. 문맥에는 이것이 들어갑니다.

- 일하는 원칙의 짧은 판. `tests/test_memory.py`가 입구 스킬의 목록과 같게 유지합니다.
- `~/.corthex/profile.json`의 프로필. 없으면 기본값을 알립니다.
- 프로젝트: 저장소 루트까지 올라가며 찾은 가장 가까운 `.corthex/project.json`, 없으면 `~/.corthex/projects.json`에서 지금 폴더를 경로나 저장소로 가진 프로젝트. 단계마다 사람 화면, 정본, 원본을 알리고, 메모는 160자에서 자릅니다. 이 기기의 다른 프로젝트는 이름만 적습니다.

이 파일들만 읽고, 아무것도 쓰지 않으며, 네트워크에 연결하지 않습니다. 값은 한 줄로 펴고 프로젝트 설정은 자료라고 밝혀서, 메모가 제목이나 지시를 따로 만들 수 없게 합니다. 문맥은 8,000자, 약 2,000토큰 아래로 둡니다. Claude Code는 10,000자, Codex는 약 2,500토큰을 넘는 훅 출력을 파일로 돌리기 때문입니다. 넘치면 메모를 먼저 빼고, 그래도 넘치면 글을 줄입니다. 무엇이든 실패하면 훅은 아무것도 넣지 않고 세션은 평소대로 시작합니다.

- **Codex는 신뢰를 묻습니다.** Codex는 `/hooks`에서 검토하고 신뢰한 플러그인 훅만 돌립니다. 설치한 뒤 한 번, 갱신으로 훅이 바뀌면 다시 신뢰합니다.
- **끄는 법.** 플러그인을 끄거나 지웁니다. Claude Code는 `claude plugin disable corthex-memory@corthex`를 실행합니다. Codex는 `~/.codex/config.toml`의 `[plugins."corthex-memory@corthex"]`에 `enabled = false`를 두거나 `codex plugin remove corthex-memory@corthex`를 실행합니다. 훅이 저장하는 것이 없어서 따로 되돌릴 것은 없습니다.
- **지금까지 확인한 것.** Linux에서 Claude Code 2.1.309와 Codex CLI 0.164.0을 격리된 설정과 로컬 가짜 모델 API로 돌려, 두 도구 모두 첫 모델 요청에 문맥이 실린 것을 봤습니다. Codex는 훅을 신뢰했을 때만 돌렸고, 시험에서는 검토 대신 `--dangerously-bypass-hook-trust`를 썼습니다. Windows와 macOS는 아직 시험하지 않았습니다. 훅을 돌리는 셸의 PATH에 `python3`나 `python`이 있어야 합니다. Windows에서 Claude Code는 훅을 Git Bash로, Git Bash가 없으면 PowerShell로 돌립니다.

## 버전과 릴리스

- 버전은 유의적 버전을 씁니다. 버전은 두 매니페스트와 모든 스킬의 `metadata.version`에 있고, 검사가 셋을 같게 유지합니다.
- 릴리스는 `<플러그인>--v<버전>` 이름의 Git 태그입니다. 예: `corthex--v0.1.0`. `claude plugin tag`가 매니페스트와 마켓플레이스 항목이 맞는지 확인한 뒤 태그를 만듭니다.
- 사용자는 각 도구의 마켓플레이스 명령으로 갱신을 받습니다.

## 검사

| 검사 | 명령 | 범위 |
| --- | --- | --- |
| 저장소 검사 | `python -m unittest discover -s tests -v` | 매니페스트와 마켓플레이스, 스킬 형식, 단계 계약, 기억 훅과 그 스크립트, 설명서 링크와 번역 짝, 비밀값과 개인 정보 |
| Claude Code 검증 | `claude plugin validate --strict .` 다음 플러그인마다 `claude plugin validate --strict plugins/<플러그인>` | 마켓플레이스와 플러그인에 대한 Claude Code 자체 스키마 |

CI는 모든 풀 리퀘스트와 `main`에 올라오는 모든 push에서 저장소 검사를 Linux, Windows, macOS에서, Claude Code 검증을 Linux에서 돌립니다.

## 앞으로

0.1.0에는 없고 계획만 있습니다. 둘 다 핵심 플러그인에 넣지 않는 구성 요소가 필요합니다.

- `corthex-memory`의 다음 판: 대화 기록을 모아 프로젝트마다 현재 상태로 정리하고, 필요한 것을 다시 꺼내는 훅. 그 현재 상태도 세션 시작 문맥에 넣습니다.
- `corthex-nexus`(선택): 모든 프로젝트를 모아 보는 허브와 사이트맵·플로우 편집 화면을 갖춘 MCP 서버. 사용자가 자기 도메인에서 돌립니다.

## 근거

2026-10-23에 확인했습니다.

- Claude Code: [Plugin manifest reference](https://code.claude.com/docs/en/plugins/manifest-reference), [Marketplace reference](https://code.claude.com/docs/en/plugins/marketplace-reference), [Plugin dependencies](https://code.claude.com/docs/en/plugins/dependencies), [Publish and distribute a plugin](https://code.claude.com/docs/en/plugins/publish), [Skills](https://code.claude.com/docs/en/skills)
- OpenAI: [Codex plugins](https://developers.openai.com/codex/plugins/build), [Submit your Claude Code plugin to OpenAI](https://developers.openai.com/plugins/guides/submit-claude-plugin), [Build skills](https://learn.chatgpt.com/docs/build-skills)
- Agent Plugins: [Plugin manifest](https://agent-plugins.org/plugin-authors/manifest), [Client extensions](https://agent-plugins.org/plugin-authors/client-extensions), [Compatible clients](https://agent-plugins.org/compatible-clients)
- 훅: [Claude Code hooks reference](https://code.claude.com/docs/en/hooks), [Codex hooks](https://learn.chatgpt.com/docs/hooks), [openai/codex#39895](https://github.com/openai/codex/issues/39895)
- [Agent Skills specification](https://agentskills.io/specification)
