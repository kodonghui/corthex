# NEXUS 스냅샷 CI

커밋이 default branch에 반영되면 `NEXUS push`는 호환되는 고정 허브의 `push --job --json`을 실행합니다. default branch push에서만 실행하며 애플리케이션을 배포하지 않습니다.

세션 환경 변수에 다음 값을 설정한 뒤 설치된 허브의 `hub.py setup-ci PROJECT`를 사용합니다.

- `CORTHEX_NEXUS_URL`: 기존 NEXUS의 비루프백 HTTPS origin입니다.
- `CORTHEX_NEXUS_CLIENT_ID`: Cloudflare Access 서비스 클라이언트 ID입니다.
- `CORTHEX_NEXUS_CLIENT_SECRET`: 대응하는 서비스 시크릿입니다.

명시적인 명령은 `gh secret set`의 표준 입력으로 암호화된 레포 Actions 시크릿을 설정합니다. 값은 출력하거나 인수에 넣거나 로컬에 저장하지 않습니다. 프로젝트의 GitHub 원격 주소로 레포를 확인하므로 프로젝트 ID `marong`을 레포 `marong2`에 연결할 수 있습니다. `gh`가 없거나 로그인하지 않았으면 한 줄로 알리고 건너뜁니다. GitHub 권한·전송 실패는 원본 CLI 출력을 노출하지 않고 보고합니다.

기존 default branch 워크플로는 유지합니다. 워크플로가 없으면 액션·허브 고정 커밋, 읽기 권한, 전체 프로젝트 이력, 순차 실행을 사용하는 재사용 가능한 PR 하나를 엽니다. 명령이 PR을 병합하거나 로컬 작업 디렉터리를 변경하지 않습니다. `setup-ci PROJECT --dry-run`은 시크릿 설정·PR 생성 없이 미리 확인합니다. 성공한 `push PROJECT --first`는 업로드 뒤 이 설정을 자동 실행하지만 최초 업로드 동의는 여전히 필요하며, 설정 실패가 업로드를 반복하거나 취소하지 않습니다. 실제 업로드 주소가 환경 변수의 `CORTHEX_NEXUS_URL`과 다르면 시크릿을 쓰기 전에 자동 설정을 건너뛰고 두 주소를 출력하지 않는 한 줄 안내를 남깁니다. 일반 push·dry-run·CI 작업은 시크릿을 설정하지 않습니다.

워크플로가 BUG-006의 헤더 선택 기능이 있는 허브를 사용하고 서버가 Cloudflare Access 뒤의 v2라면, 레포 워크플로의 **Push the snapshot** 단계 환경에 `CORTHEX_NEXUS_AUTH_HEADERS: cf-access`를 추가합니다. 새 CI 실행기에는 로컬 서버 기록이 없습니다. 이 설정은 시크릿이 아니며 `setup-ci`가 설정하거나 기존 워크플로를 변경하지 않습니다. NEXUS v3의 기본값은 `nexus-agent`입니다. 인증이 거부되면 토큰과 Access 설정뿐 아니라 선택된 헤더 쌍도 확인합니다.

## CI의 새 스냅샷 전송 확인

1. 인증된 `GET /api/snapshots/{project}/held`로 현재 `default_commit`과 `revision`을 확인합니다.
2. 다음 PR을 병합하고 새 커밋은 먼저 `NEXUS push` 작업으로 전송합니다. **Push the snapshot** 단계에서 `answer.sent: true`가 나오고 `answer.pushed.default_commit`이 실행 커밋과 일치하는지 확인합니다.
3. NEXUS의 보유 스냅샷을 다시 조회합니다. 커밋과 버전이 CI 응답과 일치하고 버전이 증가했는지 확인합니다.

CI가 성공하고 `why: already-held`가 나오면 보유 스냅샷에 접근해 중복 전송을 건너뛴 것입니다. 실제 전송은 다음 새 커밋으로 검증합니다. `not-set`은 빠진 CI 설정을 알려 주고 `first-push-waits`는 승인된 최초 업로드가 필요하다는 뜻입니다.

CI가 분기 이력을 교체하거나 체크포인트를 통과시키거나 프로젝트 데이터를 삭제하지 않습니다. 고정된 작업 허브는 제품의 `hub-ref.json`과 호환되는 버전이며, 변경할 때는 호환성 검사가 필요합니다.

자동화를 중단하려면 Actions에서 `NEXUS push`를 비활성화하거나 워크플로 PR을 revert합니다. 기존 서버 데이터는 보존합니다. 시크릿 교체·삭제는 별도의 명시적 작업이며 설정 명령이 토큰을 요청하거나 생성하지 않습니다.
