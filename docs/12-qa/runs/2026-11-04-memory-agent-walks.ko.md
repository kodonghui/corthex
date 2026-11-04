# C1 실제 모델 걷기 · Windows

2026-11-04 · TASK-057 · 기본 main `70128f321dacaf53002c569023e9e904cb422cb8`. Claude Code 2.1.310·Codex 0.164.0, 한국어·영어. 모든 대화와 프로젝트·저장소는 지어낸 시험 자료입니다.

## 판정 범위

실제 호스트 계정의 모델을 사용했습니다. C1 기억 자체의 정리·임베딩·동기화 API는 실행하지 않았고 실제 사용자 기억은 켜지 않았습니다. 기기 간 인증 파일을 복사하지 않았으며 아래 공유 증거에는 인증 자료가 없습니다.

관찰은 기본 커밋과 작업 중인 스킬 수정본에 걸칩니다. 프로필별 원본45개 해시와 기록된 설치본46개 해시를 증거에 보존합니다. 초기 네 환경은 설치·관찰 증거만 있으며 전체 설치 바이트를 나중에 검증했다고 주장하지 않습니다. 스킬 이외 원본44개는 현재 후보와 같습니다. 동의·제외 안내 수정은 최종 스킬 해시 `4d4332063472d52230a5ce88b3ff5d3bb4d9354e069fc7ec40e6270b4391f2e1`로 새로 설치한 네 환경에서 재시험했습니다. 이 보고는 릴리스 커밋에서의 재걷기나 태그 완료를 뜻하지 않습니다.

[공유 증거](2026-11-04-memory-agent-walks.evidence.json)에는 보낸 질문·실제 답변·원본 훅 입력/출력·원문 변화·보호 파일 해시와 독립 검토를 넣었습니다. 아래 R번호와 프로필/단계 키로 찾습니다. 주소만 시험 경로로 치환하고 지어낸 키 모양을 가렸습니다. 원본 자료 SHA256과 공유 사본을 구분합니다.

통합 기준은 `20f8725e8611946806fdd4685999696b29668331`입니다. 걷기 도중 병합된 core 안내 변경을 포함하지만 MEMORY의 스킬 이외 44개 파일은 그대로입니다. 칸마다 대개 호스트·언어별 한 번의 시나리오를 실행했고, 별도 재시도·수정 전후는 증거에 구분합니다. 통계적인 모델 품질이나 성공률을 추정하지 않습니다.

## 실행 목록

28개 행을 네 환경에서 판정했습니다. works는 적은 경로의 증거만 뜻하며 흐름 전체나 C2 기능의 통과를 뜻하지 않습니다. blocked 사유는 공유 증거에 있습니다. R27은 기록을 켠 채 삭제 확인하는 실패를 유지합니다. 명시적으로 먼저 끈 뒤의 우회 성공으로 덮지 않습니다.

| ID | Flow / path | Codex KO | Claude KO | Codex EN | Claude EN |
| --- | --- | --- | --- | --- | --- |
| R01 | FL-001 · The folder is in a project, and the user consents with both memory keys set | works | works | works | works |
| R02 | FL-001 · The folder is in no project | works | works | works | works |
| R03 | FL-001 · The user does not consent | works | works | works | works |
| R04 | FL-001 · A memory key is missing, or set only under another name | works | works | works | works |
| R05 | FL-001 · A temporary device, set up by a script | blocked | blocked | blocked | blocked |
| R06 | FL-002 · A prompt and its final answer are recorded | works | works | works | works |
| R07 | FL-002 · The folder is in no enabled project | works | works | works | works |
| R08 | FL-002 · The folder, the prompts or the final answers are left out | works | works | works | works |
| R09 | FL-002 · An entry cannot be written | works | works | works | works |
| R10 | FL-002 · The turn ends without a final answer | works | works | works | works |
| R11 | FL-002 · The session is cut off | works | works | works | works |
| R12 | FL-003 · The start summary gets memory's part | works | works | works | works |
| R13 | FL-003 · The folder is in no enabled project | works | works | works | works |
| R14 | FL-003 · Session boundaries are left out | works | works | works | works |
| R15 | FL-003 · The memory store cannot be read, or not in time | blocked | blocked | blocked | blocked |
| R16 | FL-003 · Curation failed, stopped, or waits for consent or a key | blocked | blocked | blocked | blocked |
| R17 | FL-003 · Consolidation is due | blocked | blocked | blocked | blocked |
| R18 | FL-003 · Retention deletes old entries in the background | works | works | works | works |
| R19 | FL-010 · The memory status is shown | works | works | works | works |
| R20 | FL-010 · A step waits for consent or a memory key | blocked | blocked | blocked | blocked |
| R21 | FL-010 · The fault guard stopped a project, and the user resumes it | blocked | blocked | blocked | blocked |
| R22 | FL-010 · The user does not resume, or confirms too late | blocked | blocked | blocked | blocked |
| R23 | FL-011 · Memory is turned off for the project | works | works | works | works |
| R24 | FL-011 · The plugin is removed | works | works | works | works |
| R25 | FL-011 · All memory is deleted after the user's yes | works | works | works | works |
| R26 | FL-011 · The user does not confirm | works | works | works | works |
| R27 | FL-011 · Sync was on | fails | fails | fails | fails |
| R28 | FL-011 · One project's memory is deleted | blocked | blocked | blocked | blocked |

## 보존한 실패와 예외

- #110: 처음 동의 안내의 조작·프로젝트 삭제 항목과 키 설정 위치 누락. 수정 후 네 환경 독립 검토 통과.
- #111: 둘 다 제외할 때 정리할 내용이 없다는 경고 누락, 끄면 기록을 재개한다는 잘못된 안내. 수정 후 네 환경 독립 검토 통과.
- #112: 기록 중 삭제 제안의 23건이 확인 때 27건으로 바뀌어 confirm-stale. 네 환경에서 미삭제·재질문을 확인했습니다. 먼저 끄도록 명시한 뒤 새 제안/동의는 삭제를 마쳤고 설치 훅 네 개가 저장소를 만들지 않았습니다. 형식이 잘못된 sync:true 시험은 별도 설정 실수이며 sync-on 통과 근거가 아닙니다.
- #113: Codex 영어의 켜진 터미널 세션에서 정상 /quit·종료0 뒤 End 관찰/원문이 없습니다. 이후 전체 관찰과 복사본에도 없으며 원인은 미확정입니다. 질문·최종 답변 세 쌍과 시작 요약은 모두 있습니다. 깨끗한 중단 두 건도 start/prompt만 있어 End를 주장하지 않습니다. 별도 조용한 새 세션의 후속 성공은 이전 실패를 해결한 증거가 아닙니다.
- 후속 삭제 대화의 질문 두 건은 lock-busy로 빠졌습니다: codex-en-keys-present/sync-purge-yes(476ms), claude-en-keys-present/purge-off-preview(543ms). 명시적인 진단과 원문을 보존하며 임대 소유자·유지보수 원인은 확인하지 않았습니다. #101의 알려진 lock-busy 현상과 함께 추적하고 #98의 원인으로 단정하지 않습니다.
- 한 활성화 답변의 닫히지 않은 private 표시는 명세대로 그 뒤 텍스트를 가렸습니다. 이는 설명되지 않은 정상 답변 유실로 세지 않습니다. 파일 공유 차단·max-turns·강제 세션 중단은 의도한 제어이며 정상 쓰기 실패와 구분합니다.

## 시작 요약과 종료 범위

시작·재개·clear·compact × 켜짐·동의 없음·읽기 불가 × 두 호스트·두 언어의 48칸을 확인했습니다. 같은 프로필의 기본 부분이 같고 전체 UTF8은 켜짐2110–2119, 동의 없음2241–2250, 읽기 불가2022–2031바이트로 모두8000미만입니다. 최초 on-yes는 활성화 전 재개이므로 켜진 재개 근거는 이후 sync-purge-preview를 씁니다. 업데이트 안내 창에서 멈춘 Codex KO 첫 시도(종료1·훅0)는 보존하고 retry만 판정합니다. 시작 요약 통과와 #113의 종료 경계 공백을 구분합니다.

## CI 재생과 제한

새 walk_replay.py는 설치한 두 호스트·두 언어 설정에서 각각9턴(합계36턴)을 로컬 고정 응답 모델로 재생합니다. 동의 보류·프로젝트 밖·키 존재·비공개·폴더/종류/경계 제외·상태·끄기·동의 후 삭제·설치 상태의 저장소 없음 보호를 검사합니다. Windows와 Linux의 네 환경이 각각 통과했습니다. 실제 모델의 번역·동의 의미 판정은 이 재생이 인증하지 않습니다. 도구 제외와 수명주기는 기존 실제 호스트 검사가 맡고, 실패·보관·불완전 턴·중단·지우기 처리와 판정 보호는 같은 훅 작업에서 실제 하위 프로세스 API 회귀 검사로 잇습니다.
재생은 원래 제품 자식을 바꾸지 않고 lifecycle_prompt.py의 시작 완료·조용한 임대 간격을 명시적으로 씁니다. 시간 측정이나 경합 수정의 근거가 아닙니다. 첫 재생 두 시도는 끈 뒤 전체 파일이 같다고 잘못 요구해 실패했으며 보존했습니다. 실제 SessionStart 유지보수는 curation.json을 갱신할 수 있습니다. 최종 검사는 현재 헤더·설정·원문·기억 층을 보존하고 보조 변화를 따로 적습니다. 100회 측정·50ms 기다림·보관 스트레스 조건은 바꾸지 않았습니다.

## 느낀 점과 출시 상태

긴 동의 설명은 요구한 항목을 유지하기 위한 것이며 간결함 평가는 판정과 별개입니다. Windows의 python3 실행기 대체 시도는 호스트의 hook_response에 잡음을 남겼습니다. 원본 자식의 stderr0과 전체 실행기 무소음을 혼동하지 않습니다. 제거 뒤 로컬 패키지를 다시 쓰는 권한은 후속 질문에서 따로 명시했습니다.
태그는 아직 없습니다. TASK-029·TC-114는 2026-11-04 결정으로 제거 이력을 남기고, TASK-030이 go/no를 맡습니다. 새 기록/종료 공백에 대한 한 번의 태그 전 확인과 최종 검사·리뷰가 필요합니다. 기다리는 동안 PR C 다음 C2 명세를 진행하도록 승인돼 있습니다. C2 분할 때 TASK-047·048의 자료와 TASK-050·055의 시험 방식을 한 번 묻습니다.

공유 증거 SHA256: `61e69c82e014da5fa56da4764b3cd9baf408141c83ab67ae18934a98b49c781d`.
