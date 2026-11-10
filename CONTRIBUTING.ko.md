# 기여 안내

[English](CONTRIBUTING.md)

관리자 한 명과 Claude Code, Codex 등의 AI 에이전트가 PR로 함께 작업합니다. 저장소 규칙의 정본은 [AGENTS.md](AGENTS.md)이며, 설계는 [구조 설명](docs/architecture.ko.md)에 있습니다. 커밋마다 [AGENTS.md의 Checks 절](AGENTS.md#checks)에 있는 명령을 먼저 실행합니다. 검사 명령의 정본은 그 절입니다.

## 브랜치와 이력

GitHub flow를 따릅니다. `main`은 검사를 통과한 상태로 유지하고, 최신 `origin/main`에서 한 목적의 짧은 브랜치를 시작하며, 병합 뒤 작업 브랜치를 지웁니다.

- AI 에이전트는 호스트가 정한 `claude/…` 또는 `codex/…` 이름을 씁니다.
- 사람에게는 `fix/hook-timeout` 같은 `<type>/<summary>` 이름을 권장합니다.
- 브랜치 이름으로 권한을 나누지 않습니다.

`main`과 릴리스 태그는 force push, 삭제, 이력 재작성을 하지 않습니다. 자기 작업 브랜치에만 `--force-with-lease --force-if-includes`를 함께 써서 force push할 수 있습니다. 리뷰 반영은 새 커밋으로 하며, 이미 리뷰에 올린 커밋은 고쳐 쓰지 않습니다.

## 커밋

Conventional Commits 1.0.0의 `type(scope): summary` 형식을 따릅니다. type은 `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`, `chore`, `revert` 중 하나입니다. 선택 사항인 scope에는 해당 플러그인이나 스킬 이름을 씁니다.

- 제목은 영어 명령형으로 72자 이내, 가급적 50자 안으로 씁니다.
- 본문에는 이유를 적습니다. 깨지는 변경은 `!` 또는 `BREAKING CHANGE:` 꼬리말로 표시합니다.
- 한 커밋에는 한 변경을 담고, 커밋마다 검사를 통과합니다.
- 리뷰는 추가 커밋으로 반영하며, 이미 리뷰에 올린 커밋은 다시 쓰지 않습니다.

## PR과 병합

모든 변경은 PR로 합니다. PR 템플릿에 무엇을 왜 바꾸는지, 검사와 결과, 위험과 되돌리는 방법, AI 참여를 적습니다. 해당하면 영향을 받는 단계 ID도 적습니다.

다음을 확인한 뒤 merge commit으로만 병합합니다.

- 검사가 통과하고 head에 `all-checks`가 있어야 합니다. 초안 PR의 CI는 Linux 작업만 돌려 `linux-checks`로 보고하므로, 병합 전에 PR을 리뷰 준비로 바꿔 모든 시스템을 돌립니다. Actions가 실행기를 시작하기 전에 실패하는 장애라면, 정해 둔 대체 검사와 결과를 PR에 기록합니다. OS별 도구 버전, 통과·실패 수, 건너뜀을 포함합니다.
- 자동 코드·보안 리뷰가 최신 head에서 완료되고 남은 지적이 없어야 하며, 리뷰 대화도 해결되어야 합니다.
- `main`이 움직였다면 합친 트리를 필요한 시스템에서 다시 검사하고, 병합 커밋의 트리 ID가 검사한 트리와 같은지 확인합니다.

보호 규칙 우회는 Actions가 실행기 시작 전에 실패하는 장애에만 허용합니다. 먼저 대체 검사 결과와 사유를 PR 댓글에 남깁니다.

병합 제목은 `Merge pull request #N: <PR title>`로 씁니다. 본문에 변경 내용, 리뷰 결과, OS별 검사를 적습니다. 병합 메시지 전체에서, attribution 꼬리말까지 `<`와 `>`를 HTML 문자로 바꾸지 않고 그대로 둡니다.

## 버전과 릴리스

SemVer 2.0.0을 씁니다. 저장소 공개 뒤에도 초기 개발 중에는 `0.x`를 유지하며, 관리자가 안정 판 `1.0.0`을 선언합니다. `0.x` 동안 깨지는 변경과 기능은 MINOR, 수정은 PATCH를 올립니다. 깨지는 변경을 MINOR로 올리는 것은 SemVer의 요구사항이 아닌 이 프로젝트의 관례입니다. 시험판은 `-rc.N`을 붙입니다.

[AGENTS.md](AGENTS.md)에 따라 플러그인의 두 매니페스트와 모든 스킬의 `metadata.version`을 함께 바꿉니다.

릴리스 태그는 `<plugin>--v<version>` 이름의 주석 태그입니다. macOS가 포함된 `check` 워크플로까지 통과한 `main` 커밋에서 `claude plugin tag plugins/<plugin>`로만 만듭니다. 가벼운 릴리스 태그를 만들거나, 올린 태그를 옮기거나 지우지 않습니다.

릴리스 노트에는 사람이 읽는 3–5줄 요약과 자동 생성한 PR 목록을 넣습니다. 당분간 `CHANGELOG.md`는 두지 않습니다.

## CI와 보안

- `pull_request_target`과 `workflow_run` 워크플로에서 PR 코드를 체크아웃하지 않습니다.
- 액션은 전체 커밋 SHA로 고정하고 같은 줄 주석에 판을 적습니다.
- 워크플로 권한은 최소인 `permissions: contents: read`로 둡니다.

보안 취약점은 [비공개 신고 절차](SECURITY.ko.md)로 알립니다. 일반 버그와 기능 제안은 공개 이슈 양식을 이용합니다.

## AI 기여와 개인정보

에이전트가 만든 커밋은 그 에이전트의 co-author 꼬리말을 남깁니다. 호스트가 세션 꼬리말을 주면 그것도 남깁니다. PR의 AI involvement 절에는 에이전트가 맡은 일을 적습니다.

커밋 작성자 메일에 개인 메일을 쓰지 않습니다. GitHub noreply 주소나, 에이전트 호스트가 정한 no-reply 주소를 씁니다. 커밋, 문서, 예시에 개인 이름·메일·홈 경로·개인 작업 공간 링크를 넣지 않습니다. [AGENTS.md](AGENTS.md)와 [tests/test_public_safety.py](tests/test_public_safety.py)의 검사를 따릅니다.
