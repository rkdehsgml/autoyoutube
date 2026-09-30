# AutoTube 계획 요약 (2026-09-30)

## 현재 초점
유튜브 쇼츠·인스타 릴스·네이버 클립에 꾸준히 올리는 시스템 + 이를 운영하는 AI 에이전트. 노트북을 켜두지 않고 클라우드에서 상시 동작. 수익화·기간(일정)은 고려하지 않음.

## 클라우드 아키텍처 (확정)
- 연산: GitHub Actions (공개 레포 권장, 표준 러너 무료). 상시 프로세스 없음 → 이벤트 구동.
- 상시 대기: Cloudflare Worker `autotube-gateway` — 텔레그램 웹훅(`POST /telegram`), Cron 4개(생성 08:50 KST, 수집 06:00 KST, 주간 개선 월 09:00 KST, 워치독 6시간), `repository_dispatch` 발신(PAT).
- 상태 DB: Cloudflare D1 (Worker는 바인딩, Actions는 REST `POST /accounts/{id}/d1/database/{db}/query`). 스키마 `worker/migrations/0001_init.sql` 단일 기준 — 테이블: settings, topics, jobs, step_runs, artifacts, evals, decisions, approvals, publications, metrics, config_versions, events.
- 미디어: Cloudflare R2 `autotube-media` (jobs/{job_id}/...), 인스타는 presigned URL. 중간 에셋 14일·final 90일 수명 규칙.
- 워크플로 6개: produce, publish, collect, optimize(PAT로 PR), eval(config·프롬프트 PR 체크), ci.
- 제어 흐름: 결정론적 상태 머신(STEPS 표) + 역할별 Claude Agent SDK `query()` (도구·JSON 스키마·max_turns·max_budget_usd 분리). 편집자는 LLM 없음.
- job 상태 16개: queued → researching → storyboarding → producing_assets → rendering → reviewing → packaging → awaiting_approval → approved → publishing → published → measuring → done / rejected, needs_human, failed. 되돌아가는 전이는 QA redo_from(최대 2회)과 [다시] 버튼뿐.
- 안전장치: 게시 도구는 allowed_tools에서 제외하고 can_use_tool이 D1 approvals 확인, produce엔 게시 시크릿 없음(GitHub Environment `publish`), D1 lease(30분)+조건부 전이, publications PK로 중복 게시 방지, 비용 상한(역할·job·월).
- 코드 구조: agent/(core/ports.py Protocol, models.py Pydantic, orchestrator.py, roles/, tools/, adapters/, media/), worker/(TypeScript), config/, evals/, .github/.

## 구현 순서 (기간 없음, 완료 기준으로 진행)
1 기반(ports·models·SqliteStore·상태 머신, `agent local --mock`) → 2 제작 역할(researcher·writer·producer, 렌더 이전) → 3 품질(critic·eval 세트) → 4 클라우드 이전(D1·R2 어댑터, produce.yml, Worker) → 5 게시(publisher·approval_gate·publish.yml) → 6 피드백(collect·optimize·eval) → 7 생성 에셋(Nano Banana·Veo·비용 훅) → 8 운영 편의(워치독·/status·주간 리포트).

## 후보 선정 요약 (상세는 docs/candidates.md)
- LLM: researcher·critic = Haiku 4.5, writer = Sonnet 5.5, optimize·eval = Sonnet 5.5 배치(또는 Opus 5.5)
- 이미지 Nano Banana 2 Lite, 영상 Veo 3.1 Lite(핵심 장면만), 음성 Gemini 3.8 Flash TTS, 렌더 ffmpeg
- 네이버 클립은 공식 업로드 API 미확인 → 반자동 권장
- 월 비용 추정(하루 1편): Veo 없이 약 $20 / 저가 Veo 구성 약 $56 / 고품질 약 $171

## 참고 영상
- CONNECT AI LAB "양산형 AI 채널은 100% 망합니다" (youtu.be/7tlFMYw3gSw): Google Opal 체인(연구→장면→대본추출→TTS / 이미지 / Veo). 우리 설계는 여기에 스토리보드 JSON, 자동 디버깅 QA, 편집·배포·측정·자기개선을 추가.

## 코드 상태
- v0 `autotube`: `python -m pytest -q` (mock 모드) 통과. 워크플로는 `github-workflows/`에 있음 → `.github/workflows/`로 옮겨야 함.
- D1 스키마 DDL은 SQLite에서 검증됨(lease 조건부 UPDATE 동작 확인).
- 다음 착수: 구현 순서 1단계.
