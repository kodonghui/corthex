# C1 설치 호스트 QA: 병합된 기준

[English](2026-11-04-memory-hosts.md)

아래 결과는 PR #90의 head `24cc42c5bbb8fe181160528b578ec3d4ebf2e7b8`에서 실제 확인했고 `15ea32cb52510cd2bf684b28ac30202820536d07`로 병합했습니다. MEMORY 제품은 PR #88(`2fc4b871873659249e4c43c8b6139c7f5748e186`)과 바이트가 같습니다. 이 보고서는 완료한 기준 근거이며 이 문서 커밋의 미래 검사를 주장하지 않습니다. 실제 Claude Code 2.1.310·Codex CLI 0.164.0은 임시 홈·기억 저장소·모형 동의·고정된 로컬 모형 서버를 씁니다. 실제 제공자나 사용자 기억 시범 결과가 아닙니다.

## Python 여섯 칸

| OS | Python | Passed / skipped | Seconds | Retention successes / attempts / skips |
| --- | --- | ---: | ---: | --- |
| [Linux](https://github.com/kodonghui/corthex/actions/runs/41680581067/job/126072841711) | 3.8.18 | 840 / 13 | 200.315 | 100 / 100 / 0 |
| [Linux](https://github.com/kodonghui/corthex/actions/runs/41680581067/job/126072842344) | 3.15.1 | 841 / 12 | 195.359 | 100 / 100 / 0 |
| [Windows](https://github.com/kodonghui/corthex/actions/runs/41680581067/job/126072841746) | 3.8.10 | 847 / 6 | 363.693 | 100 / 100 / 0 |
| [Windows](https://github.com/kodonghui/corthex/actions/runs/41680581067/job/126072842293) | 3.15.2 | 848 / 5 | 305.106 | 100 / 100 / 0 |
| [macOS](https://github.com/kodonghui/corthex/actions/runs/41680581067/job/126072842061) | 3.8.18 | 832 / 21 | 368.126 | 100 / 101 / 1 |
| [macOS](https://github.com/kodonghui/corthex/actions/runs/41680581067/job/126072841737) | 3.15.2 | 833 / 20 | 274.846 | 100 / 100 / 0 |

각 칸은 853개 시험을 발견해 실패 없이 마쳤고 Node 15개도 통과했습니다. 마켓플레이스와 플러그인 세 곳의 strict 검증 및 Actions app 15368의 필수 `all-checks`를 포함한 현 head 검사 16개가 성공했습니다. 원래 보관 동시 쓰기 조건은 성공 100회·최대 500시도·120초·쓰기 간격 10ms 그대로입니다. macOS 3.8의 임대 건너뜀 1회도 기록하며 조건 변경이 아닙니다.

TC-104의 정적 목록은 배포 MEMORY Python 파일 35개의 모든 import와 플랫폼별 import를 포함합니다. 내부 패키지는 `memory_lib`이며 외부 최상위 모듈은 모두 표준 라이브러리입니다: `argparse`, `builtins`, `collections`, `contextlib`, `copy`, `ctypes`, `dataclasses`, `datetime`, `fcntl`, `functools`, `hashlib`, `itertools`, `json`, `math`, `msvcrt`, `os`, `pathlib`, `re`, `secrets`, `shutil`, `stat`, `subprocess`, `sys`, `tempfile`, `threading`, `time`, `unicodedata`, `urllib`. 여섯 칸의 실제 실행과 함께 보는 의존성 확인이며 모든 플랫폼별 분기를 각 OS에서 실행했다는 주장은 아닙니다.

## 설치 호스트·작업자 생존·기록 보존

실제 호스트 작업 로그: [Linux](https://github.com/kodonghui/corthex/actions/runs/41680581067/job/126072841698) · [Windows](https://github.com/kodonghui/corthex/actions/runs/41680581067/job/126072841933) · [macOS](https://github.com/kodonghui/corthex/actions/runs/41680581067/job/126072842101).

세 OS의 두 호스트에서 네 훅·한국어 프롬프트/최종 답변·실제 같은 세션과 턴·글 없는 시작/종료 경계·성공 timing·실패 로그 없음을 확인했습니다. Windows는 Git Bash 없이 두 호스트, PowerShell 5.1만 둔 Codex도 통과했습니다. Unix 일반 4행·Windows 일반/대체 5행·제어 계측 6행으로 모두 15개 호스트/환경 행입니다.

제어 계측의 여섯 호스트/OS 조합에서는 원래 worker 진입점과 제품 library 바이트를 보존했습니다. 보관 함수 안의 시험용 대기는 같은 실제 PID/nonce의 진입·호스트와 네 훅 종료·그 뒤 heartbeat·재개·반환·오래된 원문 삭제와 새 원문 보존을 연결합니다. 20초 대기와 6/12초 관찰 한도는 그대로입니다. 이는 명시한 계측으로 TC-103의 생존을 확인하며 계측 없는 성능 결과가 아닙니다.

TC-101은 각 조합에서 실제 플러그인을 제거·재설치했습니다. 제거 전·제거 뒤·설치 뒤의 설정·store header·원문 SHA256 목록이 같습니다. TC-108의 양성 대조를 둔 MEMORY 전용 HTTP(S) 프록시는 여섯 조합 모두 요청 0건입니다. Codex 자체 메타데이터 시도는 별도 프록시에서 차단·기록합니다. 이 범위는 설정한 프록시 관찰이며 OS 전체 패킷 캡처가 아닙니다. 훅별 외부 시간 한 번은 원래 제품 인터프리터 시작을 포함하고 호스트/시험 래퍼 시작을 제외하며 p95가 아닙니다.

## 시스템별 지우기 처리 시간

TC-028은 아래 입력마다 준비 1회를 제외하고 10회 측정했습니다. 모형 시험에서는 환경 지우기 값 수를 0으로 고정했습니다. 호스트 작업 Python은 Linux 3.15.1·Windows 3.12.10·macOS 3.15.2입니다. 이 지우기 처리 시간으로 기록 훅 전체의 100ms 목표를 판정하지 않습니다.

| Input (524,288 bytes each) | Linux median / max ms | Windows median / max ms | macOS median / max ms |
| --- | ---: | ---: | ---: |
| prose | 107.798 / 109.869 | 106.299 / 121.217 | 94.29 / 110.359 |
| password-repeat | 258.983 / 264.686 | 235.861 / 242.07 | 205.431 / 293.068 |
| private-openers | 12.375 / 12.93 | 16.521 / 16.936 | 10.629 / 14.511 |
| pem-header-without-key | 107.929 / 109.771 | 114.043 / 119.79 | 122.308 / 132.471 |
| token-digits | 107.527 / 108.02 | 106.618 / 110.542 | 102.974 / 129.417 |
| url-without-at | 107.668 / 108.414 | 106.773 / 110.937 | 121.295 / 154.195 |
| pem-begin-name-repeat | 103.062 / 103.938 | 102.23 / 105.814 | 101.594 / 117.328 |
| pem-end-name-repeat | 17.869 / 18.507 | 20.323 / 21.13 | 19.764 / 26.074 |
| jwt-no-dots | 100.955 / 102.389 | 98.113 / 103.313 | 110.365 / 168.636 |
| jwt-base64-json | 100.516 / 101.37 | 99.753 / 106.846 | 130.448 / 334.937 |
| token-repeat | 341.247 / 351.433 | 299.144 / 316.23 | 342.163 / 592.402 |
| passwd-repeat | 309.331 / 321.206 | 275.042 / 281.647 | 314.089 / 380.829 |
| secret-repeat | 302.341 / 308.349 | 267.694 / 282.693 | 304.045 / 430.445 |
| apikey-repeat | 310.504 / 317.364 | 274.12 / 289.832 | 297.896 / 312.308 |
| jwt-percent-repeat | 101.791 / 102.366 | 99.015 / 105.491 | 100.943 / 108.969 |

## 범위와 실패 기록

이 근거는 TC-028·TC-101·TC-102·TC-103·TC-104·TC-108의 전체 사례 결과를 뒷받침합니다. Windows에서만 확인한 [실제 도구 턴](2026-11-04-memory-tool-turn.ko.md)·[업데이트 신뢰](2026-11-04-memory-trust-update.ko.md)·[실제 작업 알림](2026-11-04-memory-native-prefix.ko.md)은 각각 따로 적었습니다. 다른 OS·모든 알림 형식·재진입 Stop·모든 세션 시작 종류의 통과로 확대하지 않습니다. TC-105는 미완료입니다. [기존 로컬 재생 기준](https://github.com/kodonghui/corthex/issues/95)은 그대로 둔 100ms p95 목표를 넘었으며 CI의 실제 세션 100회가 아닙니다.

앞선 Windows 실행기 판정·제어 호스트 진단 지연·macOS 3.8 프로세스 간 시계 실패는 PR #90의 수정 근거와 함께 보존합니다. 원인 미확정 local 오류와 무효 준비 시도를 제품 수정으로 바꾸지 않습니다. TASK-028은 진행 중이며 에이전트 걷기·사용자 한 주 시범과 출시 판단·실제 태그·그 뒤 PR C는 별도입니다.

비공개로 보존한 정본 근거: `task028-v7-ci-summary.json`, SHA256 `341086294c2fae55026e6c80c49850414ab6f9b0dda323794122d52fbaab0f68`; `task028-v7-native-ci-summary.json`, SHA256 `0aa7afd6c79338a7a2bed3e667216ce0dc0d221cac1b35fa116cce7bbc98eb8f`; `task028-followup-import-inventory.json`, SHA256 `73645ab30d99d2f538c2805c18b31953b4def29e5ae878a63186a45bcdeb875d`. 위 공개 작업 로그와 실제 호스트 출력·행렬 결과를 연결합니다. 저장소 실제 경로와 임시 대화 원문은 이 공개 보고서에 넣지 않습니다.
