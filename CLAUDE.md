# AutoTube — 에이전트 개발 지침 (CLAUDE.md)

## 목표
유튜브 쇼츠·인스타 릴스·네이버 클립에 영상을 꾸준히 올리는 시스템과, 이를 운영하는 AI 에이전트를 만든다.
노트북 없이 클라우드에서 상시 동작해야 한다. 수익화와 일정은 고려하지 않는다.

## 먼저 읽을 것 (코드 작성 전)
1. docs/plan.md — 확정 아키텍처와 구현 순서
2. docs/candidates.md — 노드별 모델·서비스 후보와 비용 가정
3. 기존 v0 코드(`autotube/`)와 README.md, tests/

## 확정된 결정 (바꾸지 말 것)
- 연산: GitHub Actions, 이벤트 구동. 상시 프로세스 없음.
- 상시 대기: Cloudflare Worker `autotube-gateway` (TypeScript). 텔레그램 웹훅 POST /telegram, Cron 4개(생성 08:50 KST, 수집 06:00, 주간 개선 월 09:00, 워치독 6시간), repository_dispatch 발신.
- 상태 DB: Cloudflare D1, 스키마 기준은 worker/migrations/0001_init.sql 하나. 미디어는 R2 (jobs/{job_id}/...).
- 제어: 결정론적 상태 머신(STEPS 표) + 역할별 Claude Agent SDK query(). 역할마다 도구·JSON 스키마·max_turns·max_budget_usd 분리. editor는 LLM 없이 코드로만.
- job 상태 16개: queued → researching → storyboarding → producing_assets → rendering → reviewing → packaging → awaiting_approval → approved → publishing → published → measuring → done / rejected, needs_human, failed.
- 되돌아가는 전이는 QA redo_from(최대 2회)과 [다시] 버튼뿐.
- 새 코드 구조: agent/(core/ports.py Protocol, models.py Pydantic, orchestrator.py, roles/, tools/, adapters/, media/), worker/, config/, evals/, .github/.
- 기존 v0 패키지 `autotube/`는 새 구조로 옮기는 단계 전까지 삭제하지 않는다. v0 테스트(`python -m pytest -q`)는 계속 통과해야 한다.

## 안전 규칙 (절대 어기지 말 것)
- 게시 도구는 allowed_tools에서 제외하고, can_use_tool이 D1 approvals를 확인해야만 통과.
- produce 워크플로에는 게시 시크릿을 두지 않는다 (GitHub Environment `publish`에만).
- D1 lease(30분) + 조건부 전이로 동시 실행 방지, publications PK로 중복 게시 방지.
- 비용 상한(역할·job·월)을 코드로 강제. 기본은 job당 $1.
- API 키·토큰은 코드나 로그에 넣지 않는다. 환경변수와 .env.example만 쓴다.
- 기본 실행은 항상 mock. 실제 외부 API 호출은 명시적 플래그가 있을 때만.

## 작업 방식
- 대화형 세션: 큰 작업은 코드 전에 짧은 계획(파일 목록, 인터페이스, 테스트 목록)을 먼저 제시하고 승인받는다.
- 무인 실행(예약 작업): 질문하지 말고 추천안으로 진행한다. 문서에 없는 결정은 코드에 `TODO(decision):`으로 표시하고 보고서에 모은다.
- 테스트 먼저: 기능마다 pytest를 작성하고 `python -m pytest -q`가 통과해야 완료.
- 작은 단위로 커밋. 메시지는 "무엇을/왜". main에는 직접 커밋하지 않고 작업 브랜치(`stage-N`)를 쓴다.
- 각 단계가 끝나면 (1) 한 일 (2) 테스트 결과 (3) 남은 결정 사항 (4) 다음 단계 제안을 10줄 이내로 보고한다.

## 구현 순서
1 기반(ports·models·SqliteStore·상태 머신, `agent local --mock`) → 2 제작 역할(researcher·writer·producer) → 3 품질(critic·eval 세트) → 4 클라우드 이전(D1·R2 어댑터, produce.yml, Worker) → 5 게시(publisher·approval_gate·publish.yml) → 6 피드백(collect·optimize·eval) → 7 생성 에셋(Nano Banana·Veo·비용 훅) → 8 운영 편의(워치독·/status·주간 리포트)
