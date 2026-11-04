# CORTHEX

[English](README.md)

CORTHEX는 한 사람이 AI와 함께 소프트웨어 프로젝트를 단계별로 진행하도록 돕는 Claude Code·Codex용 플러그인입니다. 도메인 탐색과 요구사항부터 화면, 개발, QA, 마지막 발표까지 다룹니다.

따로 돌아가는 서비스를 더하지 않습니다. 설치와 갱신은 각 도구의 플러그인 마켓플레이스를 쓰고, 핵심 플러그인은 스킬만 담습니다. 그 위에 세 가지를 더합니다.

- **AI가 일하는 원칙**: 결과부터 말하기, 사실과 추측 나누기, 되돌릴 수 없는 일은 먼저 묻기, 기록 남기기.
- **13단계 작업 흐름**: 모든 단계가 같은 여섯 칸(입력, 산출물, 사람 화면, 동기화, 사람 확인 지점, 추적 ID)을 채워서, 각 산출물을 앞 단계까지 거슬러 따라갈 수 있습니다.
- **프로필과 프로젝트 등록**: 같은 플러그인을 사람마다, 그리고 여러 프로젝트에 함께 쓸 수 있습니다.

선택해서 더하는 플러그인이 둘 있습니다. `corthex-memory`는 세션마다 처음에 원칙, 프로필, 현재 프로젝트 설정을 넣어 줍니다. `corthex-nexus`는 모든 프로젝트의 단계, 점검, 추적 링크를 한 페이지에 보여 줍니다.

> 상태: 핵심 `corthex`는 0.5.0, `corthex-memory` 0.2.0 C1 패키지는 출시 판단·태그 전의 QA·시범 운영 준비 중이며, `corthex-nexus`는 0.1.0입니다. 단계 스킬은 실제 사용으로 채워 갑니다. 기억의 모델 정리·회상은 C2 작업이고, NEXUS에는 로컬 허브와 직접 배포하는 첫 서버가 있습니다.

설치부터 요구사항 하나를 검토하고 진행 기록을 남기기까지는 [첫 프로젝트](docs/first-project.ko.md)를 따라 해 보세요.

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

`corthex-memory` 0.2.0은 세션 문맥과 로컬 대화 기록을 더합니다. 동의를 확인하고 등록한 프로젝트에서 켜야 기록을 시작합니다. 가리기를 거친 프롬프트·최종 답변·세션 종료 경계를 담으며, 도구 호출·도구 결과·파일은 기록 입력이 아닙니다. C1은 모델이나 네트워크를 호출하지 않습니다. 모델 정리·의미 검색·회상은 C2 작업입니다.

기억 저장소는 `~/.corthex/corthex-memory/`, 또는 `CORTHEX_MEMORY_HOME`에 지정한 절대 경로입니다. 원문은 기본 100일 보관하며 `retention`으로 기간을 바꾸면 이후 세션 시작 작업자가 적용합니다. 저장소가 없으면 `on` 명령이 만들며 훅은 만들지 않습니다. 모델 키가 없어도 C1 기록은 동작합니다. 관리 스킬은 키의 존재 여부만 확인하고 대화에서 키를 묻지 않습니다.

기억 스킬에 기록 켜기·끄기, 상태 보기, 폴더나 글 종류 제외, 보관 기간 변경, 로컬 기억 전체 삭제, 저장소 정보 복구를 요청하세요. C1 명령은 `on`, `off`, `status`, `leave-out`, `retention`, `purge`, `repair`입니다. 확인이 필요한 작업은 제안을 보여 주고 사용자가 좋다고 한 뒤 확인 코드를 적용합니다. 전체 삭제에서 읽을 수 없는 정보는 확인 불가로 표시하고 정확한 폴더를 보여 줍니다. `off`는 기존 기억을 보존하고 보관 처리는 계속하며, 플러그인을 지워도 저장소는 남습니다. 확인한 `purge`는 그 로컬 폴더만 지우며 호스트 대화 기록과 바깥의 사본은 남습니다.

PATH에 Python 3.8 이상이 있어야 합니다(훅은 `python3`, `python`, Windows의 `py` 실행기를 차례로 찾습니다). Windows의 Claude Code에는 Git for Windows나 PowerShell 7도 필요합니다. 훅 진단은 안전한 메타데이터와 오류 코드를 남깁니다. 기록 잠금을 잡으면 훅 기한을 넘더라도 읽기·덧붙이기·표지를 마칠 때까지 유지합니다.

```bash
claude plugin install corthex-memory@corthex   # Claude Code, corthex도 함께 설치
codex plugin add corthex-memory@corthex        # Codex, corthex를 추가한 뒤
```

Codex에서는 `/hooks`에서 플러그인의 훅을 검토하고 신뢰해 주세요. 기록은 [기억 스킬](plugins/corthex-memory/skills/corthex-memory/SKILL.md)로 관리합니다. 패키지의 실제 호스트 C1 QA·관리자 시범 운영·출시 판단을 마친 뒤 릴리스 태그를 정합니다. 자세한 내용은 [세션 시작 문맥](docs/architecture.ko.md#세션-시작-문맥)에 있습니다.

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
| `corthex-discover` | 01 | Miro 같은 보드에서 이벤트 스토밍을 단계별로 함께 하고, 컨텍스트·컨텍스트 지도·용어집을 담은 도메인 설계서로 정리할 때 |
| `corthex-define` | 02–04 | 요구사항, 유저 플로우, 기능 명세를 쓸 때 |
| `corthex-contract` | 05–06 | DB 스키마와 API 계약을 명세에 맞출 때 |
| `corthex-screen` | 07–09 | 사이트맵, 화면 상태, 목업과 디자인 토큰 |
| `corthex-build` | 10–12 | 작업 분해, 개발, QA |
| `corthex-present` | 13 | 발표 대본, 장면표, 슬라이드 |
| `corthex-record` | 상시 | 회의록, 결정 로그, 진행 기록, 회고 |
| `corthex-uxui` | 08·09·13 또는 단독 | 화면·모션·영상의 막연한 디자인 표현을 부품 이름과 숫자로 바꾸고, 결과를 보이기 전에 줄바꿈·대비·터치 크기·번쩍임·음량을 잴 때 |
| `corthex-hub` | 전체, `corthex-nexus`에 있음 | 모든 프로젝트의 단계, 점검, 추적 링크를 한 페이지로 보고, 단계마다 진행 상태를 기록할 때 |

## 프로필과 프로젝트

- `~/.corthex/profile.json`: 호칭, 언어, 기록 위치, 먼저 물어볼 일. `corthex` 스킬이 만들기를 제안합니다. 비밀값은 넣지 않습니다.
- 제품 저장소의 `.corthex/project.json`: 단계마다 사람이 보는 곳(`human`), 텍스트 원본의 위치(`source`), 둘이 다를 때 어느 쪽을 따를지(`truth`).
- `~/.corthex/projects.json`: 한 기기에 있는 프로젝트 목록.
- `~/.corthex/hub/`: `corthex-nexus`를 설치했을 때 허브의 스냅샷, 기록한 진행 상태, 페이지.

Notion에 기록할 때는 프로젝트의 `records.location`이나 프로필의 `records.hub`가 기록 데이터베이스를 가리킵니다. 기록은 그 행으로 쓰고, 기록 안의 표는 인라인 데이터베이스로 둡니다. [기록 스킬](plugins/corthex/skills/corthex-record/SKILL.md)을 따릅니다.

설계와 각 형식의 위치는 [구조 설명](docs/architecture.ko.md)에 있습니다.

## 호환

- Claude Code는 `.claude-plugin/marketplace.json`과 각 플러그인의 `.claude-plugin/plugin.json`을 읽습니다.
- Codex와 다른 [Agent Plugins](https://agent-plugins.org) 클라이언트는 `.agents/plugins/marketplace.json`과 핵심 플러그인 루트의 `plugin.json`을 읽습니다. `corthex-memory`는 훅이 있어 그 대신 `.codex-plugin/plugin.json`을 두고, Claude Code와 Codex에서만 씁니다. `corthex-nexus`는 훅이 없어 루트 `plugin.json`을 둡니다.
- 스킬은 [Agent Skills](https://agentskills.io) 형식이라 두 도구가 함께 쓰고, 스킬 하나만 따로 쓸 수도 있습니다.
- `corthex-uxui`에는 필요할 때 쓰는 점검 스크립트 둘이 있고, 둘 다 읽기만 합니다. `page-check.js`는 점검할 페이지 안에서 돌며, 브라우저 콘솔에 붙여 넣거나 Playwright 같은 브라우저 자동화 도구에 넘겨 씁니다. `media-check.py`는 Python 3.8 이상과 FFmpeg가 필요합니다.

## 개발

브랜치, 커밋, PR, 릴리스 규칙은 [기여 안내](CONTRIBUTING.ko.md)에 있습니다.

```bash
python -m unittest discover -s tests -v
claude plugin validate --strict .
claude plugin validate --strict plugins/corthex
claude plugin validate --strict plugins/corthex-memory
claude plugin validate --strict plugins/corthex-nexus
node --test nexus/test/*.test.js     # Node 22.13 이상
```

## 라이선스

[Apache-2.0](LICENSE). [NOTICE](NOTICE)도 함께 보세요.
