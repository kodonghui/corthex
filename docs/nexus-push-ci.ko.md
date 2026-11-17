# NEXUS 스냅샷 CI

`NEXUS push` 워크플로는 push가 `main`에 반영되면 고정 커밋 `c6095b40c71bc74d207b13b5b08aeeb078c7d0c5`의 `hub.py push --job --json`으로 프로젝트 스냅샷을 전송합니다. PR에서는 실행하지 않으며 애플리케이션을 배포하지 않습니다.

레포 소유자가 Settings → Secrets and variables → Actions에서 다음 시크릿을 설정해야 합니다.

- `CORTHEX_NEXUS_URL`: 기존 NEXUS 서버 주소입니다.
- `CORTHEX_NEXUS_CLIENT_ID`: Cloudflare Access 서비스 클라이언트 ID입니다.
- `CORTHEX_NEXUS_CLIENT_SECRET`: 대응하는 서비스 시크릿입니다.

비밀값은 PR·로그·파일에 넣지 않습니다. 이 변경에서는 시크릿을 설정하지 않습니다. 누락되면 작업은 `not-set`을 보고하고 전송하지 않습니다. 프로젝트 이름은 `.corthex/project.json`에서 읽습니다. marong2 레포의 프로젝트 이름은 `marong`입니다. 최초 업로드는 소유자의 확인과 수동 `--first` push가 필요하며, CI는 `first-push-waits`를 보고합니다. 서버가 보유한 default branch 커밋의 후속 커밋만 전송하며, 분기된 이력을 교체하거나 체크포인트를 통과시키거나 프로젝트를 삭제하지 않습니다.

작업은 레포 읽기 권한, 프로젝트 전체 Git 이력, 고정된 checkout 액션과 허브 커밋, Git 인증정보 비저장, 취소하지 않는 순차 실행을 사용합니다. 마지막 허브 실행 단계에만 시크릿을 전달합니다.

자동화를 중단하려면 Actions에서 `NEXUS push`를 비활성화합니다. 롤백하려면 `.github/workflows/corthex-nexus-push.yml`을 추가한 PR을 revert합니다. 기존 서버 데이터는 보존됩니다. 허브 커밋을 변경할 때는 운영 서버 및 제품 레포의 `hub-ref.json`과 호환성을 확인해야 합니다.

검증: 워크플로는 NEXUS 서버 가이드에서 이미 테스트하는 push 작업 예시와 동일합니다. 실제 전송은 소유자의 시크릿 설정과 default branch push 뒤에 확인할 수 있습니다.
