# CORTHEX

[English](README.md)

CORTHEX는 한 사람이 AI와 함께 소프트웨어 프로젝트를 단계별로 진행하도록 돕는 Claude Code·Codex용 플러그인입니다. 도메인 탐색과 요구사항부터 화면, 개발, QA, 마지막 발표까지 다룹니다.

따로 돌아가는 서비스를 더하지 않습니다. 설치와 갱신은 각 도구의 플러그인 마켓플레이스를 쓰고, 핵심 플러그인은 스킬만 담습니다. 그 위에 세 가지를 더합니다.

- **AI가 일하는 원칙**: 결과부터 말하기, 사실과 추측 나누기, 되돌릴 수 없는 일은 먼저 묻기, 기록 남기기.
- **13단계 작업 흐름**: 모든 단계가 같은 여섯 칸(입력, 산출물, 사람 화면, 동기화, 사람 확인 지점, 추적 ID)을 채워서, 각 산출물을 앞 단계까지 거슬러 따라갈 수 있습니다.
- **프로필과 프로젝트 등록**: 같은 플러그인을 사람마다, 그리고 여러 프로젝트에 함께 쓸 수 있습니다.

선택해서 더하는 플러그인이 둘 있습니다. `corthex-memory`는 세션마다 처음에 원칙, 프로필, 현재 프로젝트 설정을 넣어 줍니다. `corthex-nexus`는 모든 프로젝트의 단계, 점검, 추적 링크를 한 페이지에 보여 줍니다.

> 상태: 0.1.0, 초기 골격입니다. 단계 스킬은 실제로 쓰면서 채워 갈 뼈대입니다. `corthex-memory`는 아직 세션 시작 문맥만 넣고, `corthex-nexus`에는 로컬 허브 페이지와 직접 배포하는 첫 NEXUS 서버가 있습니다.

## 설치

### Claude Code

```bash
claude plugin marketplace add kodonghui/corthex
claude plugin install corthex@corthex
```

설치한 뒤 세션에서 하려는 일을 말하거나 `/corthex:corthex`를 실행하세요.

### Codex

```bash
codex plugin marketplace add kodonghui/corthex
codex plugin add corthex@corthex
```

### 선택: 세션 시작 문맥

`corthex-memory`는 세션이 시작될 때 일하는 원칙, 프로필, 현재 프로젝트 설정을 넣습니다. 로컬 파일만 읽고 네트워크에 연결하지 않습니다. PATH에 Python 3(`python3`나 `python`)이 있어야 하고, Windows의 Claude Code에서는 Git for Windows나 PowerShell 7도 있어야 합니다.

```bash
claude plugin install corthex-memory@corthex   # Claude Code, corthex도 함께 설치
codex plugin add corthex-memory@corthex        # Codex, corthex를 추가한 뒤
```

Codex에서는 `/hooks`를 한 번 열어 이 플러그인의 훅을 신뢰해 주세요. 신뢰하기 전에는 Codex가 플러그인 훅을 돌리지 않습니다. 끄려면 플러그인을 끄거나 지웁니다. 자세한 내용은 [세션 시작 문맥](docs/architecture.ko.md#세션-시작-문맥)에 있습니다.

### 선택: 프로젝트 허브

`corthex-nexus`는 등록한 모든 프로젝트의 단계별 원본을 읽어 페이지 하나, `~/.corthex/hub/index.html`을 만듭니다. 프로젝트마다 13단계, 추적 ID 점검 결과, 항목 사이의 링크가 보입니다. 단계마다 기록해 둔 진행 상태, 예를 들어 마지막 확인 지점도 함께 보입니다. 페이지는 오프라인에서도 열리고 네트워크에서 아무것도 불러오지 않습니다.

```bash
claude plugin install corthex-nexus@corthex   # Claude Code, corthex도 함께 설치
codex plugin add corthex-nexus@corthex        # Codex, corthex를 추가한 뒤
```

설치한 뒤 허브를 보여 달라고 하거나 `/corthex-nexus:corthex-hub`를 실행하세요. Python 3.8 이상이 필요합니다. 내 도메인의 NEXUS 서버로 프로젝트 스냅샷을 보낼 수도 있지만, 목록에 적어 둔 프로젝트만 보냅니다. 서버는 Cloudflare Access 뒤에서 도는 Cloudflare Worker로, 내 Cloudflare 계정에 직접 배포합니다: [nexus/](nexus/README.ko.md). 자세한 내용은 [프로젝트 허브](docs/architecture.ko.md#프로젝트-허브)에 있습니다.

## 스킬

| 스킬 | 단계 | 쓰는 때 |
| --- | --- | --- |
| `corthex` | 입구 | 프로필 설정, 프로젝트 등록, 지금 어느 단계이고 다음은 무엇인지 볼 때 |
| `corthex-discover` | 01 | 도메인 워크숍 결과를 바운디드 컨텍스트와 용어집으로 정리할 때 |
| `corthex-define` | 02–04 | 요구사항, 유저 플로우, 기능 명세를 쓸 때 |
| `corthex-contract` | 05–06 | DB 스키마와 API 계약을 명세에 맞출 때 |
| `corthex-screen` | 07–09 | 사이트맵, 화면 상태, 목업과 디자인 토큰 |
| `corthex-build` | 10–12 | 작업 분해, 개발, QA |
| `corthex-present` | 13 | 발표 대본, 장면표, 슬라이드 |
| `corthex-record` | 상시 | 회의록, 결정 로그, 진행 기록 |
| `corthex-hub` | 전체, `corthex-nexus`에 있음 | 모든 프로젝트의 단계, 점검, 추적 링크를 한 페이지로 보고, 단계마다 진행 상태를 기록할 때 |

## 프로필과 프로젝트

- `~/.corthex/profile.json`: 호칭, 언어, 기록 위치, 먼저 물어볼 일. `corthex` 스킬이 만들기를 제안합니다. 비밀값은 넣지 않습니다.
- 제품 저장소의 `.corthex/project.json`: 단계마다 사람이 보는 곳(`human`), 텍스트 원본의 위치(`source`), 둘이 다를 때 어느 쪽을 따를지(`truth`).
- `~/.corthex/projects.json`: 한 기기에 있는 프로젝트 목록.
- `~/.corthex/hub/`: `corthex-nexus`를 설치했을 때 허브의 스냅샷, 기록한 진행 상태, 페이지.

설계와 각 형식의 위치는 [구조 설명](docs/architecture.ko.md)에 있습니다.

## 호환

- Claude Code는 `.claude-plugin/marketplace.json`과 각 플러그인의 `.claude-plugin/plugin.json`을 읽습니다.
- Codex와 다른 [Agent Plugins](https://agent-plugins.org) 클라이언트는 `.agents/plugins/marketplace.json`과 핵심 플러그인 루트의 `plugin.json`을 읽습니다. `corthex-memory`는 훅이 있어 그 대신 `.codex-plugin/plugin.json`을 두고, Claude Code와 Codex에서만 씁니다. `corthex-nexus`는 훅이 없어 루트 `plugin.json`을 둡니다.
- 스킬은 [Agent Skills](https://agentskills.io) 형식이라 두 도구가 함께 쓰고, 스킬 하나만 따로 쓸 수도 있습니다.

## 개발

```bash
python -m unittest discover -s tests -v
claude plugin validate --strict .
claude plugin validate --strict plugins/corthex
claude plugin validate --strict plugins/corthex-memory
claude plugin validate --strict plugins/corthex-nexus
node --test nexus/test/*.test.js     # Node 22.5 이상
```

## 라이선스

[Apache-2.0](LICENSE). [NOTICE](NOTICE)도 함께 보세요.
