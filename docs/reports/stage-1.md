# 1단계(기반) 보고서 — 2026-10-01

1. 한 일: `worker/migrations/0001_init.sql`(설계 문서 DDL, 12 테이블) · `agent/core`(16상태 전이표, 테이블 1:1 Pydantic 모델, Store·BlobStore·Clock·Notifier 등 Protocol) · `SqliteStore`(같은 DDL) · `LocalBlobStore`(R2 키 구조).
2. 한 일: `agent/orchestrator.py` STEPS 표 — lease 30분(단계마다 연장·종료 시 반납, 조건부 전이), 재시도 3회, QA redo_from 최대 2회(3번째 → needs_human), 비용 상한(역할·job $1·월), 승인·거절·[다시](`apply_decision`).
3. 한 일: `python -m agent local --mock`(또는 `pip install -e .` 후 `agent local --mock`) → queued → awaiting_approval. `status`·`decide` 명령, `config/roles.yaml`(게시 도구는 allowed 금지).
4. 테스트: `python -m pytest -q` → 76 passed (agent 74 + v0 2). 스키마↔모델 컬럼 일치, 잘못된 전이 거부, lease 16스레드 동시 획득(1개만 성공), lease 상실 시 전이 안 함, 재시도·QA 루프·비용 상한, CLI 종단.
5. 남은 결정(TODO(decision)): [다시] 되돌아갈 단계(storyboarding 가정)·최대 횟수(3 가정)·[다시] 후 qa_rounds 초기화 여부.
6. 남은 결정: 월 상한 기본값($30 가정), producer 모델(Haiku 가정), producer 역할 예산 $1.50 > job 상한 $1 (job 상한이 먼저 걸림).
7. 남은 결정: QA 불합격인데 redo_from 이 없으면 바로 needs_human (현재 구현), 비용 상한 초과는 failed (needs_human 아님).
8. 참고: 클라우드 세션은 레포 쓰기 권한이 없어 push는 맥에서. 워크플로 파일은 아직 `github-workflows/`.
9. 다음(2단계): researcher·writer·producer 실제 핸들러(Agent SDK `query()` + JSON 스키마 검증 + max_turns·budget), 렌더·자막을 `agent/media`로 이전.
10. 다음(2단계): 역할 프롬프트 `agent/prompts/<role>.md`, 실제 호출은 `--live` 일 때만, mock 테스트 유지.
