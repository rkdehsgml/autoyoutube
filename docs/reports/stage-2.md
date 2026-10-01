# 2단계(제작 역할) 보고서 — 2026-10-01

1. 한 일: `agent/core/role_runner.py` — Agent SDK `query()` 실행기. 도구는 roles.yaml 교집합만 노출(`tools`·`allowed_tools`·MCP `autotube`), `permission_mode=dontAsk`·`setting_sources=[]`, 게시 도구 노출 불가. `structured_output` 을 Pydantic 으로 재검증하고 실패하면 같은 세션 resume 으로 1회 수정. 예산 초과→BudgetExceeded, 턴 초과·실행 오류→재시도, 실패해도 쓴 비용 기록.
2. 한 일: researcher(topic_bank+WebSearch, 요청 주제 유지, 포맷 검증·로테이션) · writer(스토리보드, 아직 못 만드는 비주얼은 stock 으로) · producer(LLM+도구, 끝에 reconcile 로 실제 산출물 기준 매니페스트 재작성·누락 음성 합성·못 찾은 비주얼은 단색 배경) + 프롬프트 3개.
3. 한 일: 도구 `topic_bank`·`tts_synthesize`(텍스트는 스토리보드에서만)·`stock_search`·`check_asset` — job 하나에 묶이고 멱등. 어댑터 edge·google·mock TTS, Pexels·placeholder. v0 렌더·자막을 `agent/media` 로 이전(editor, LLM 없음) + 썸네일, packaging 은 코드(v0 metadata 이전).
4. 실행: 기본 `agent local` = 외부 호출 없이 진짜 1080×1920 mp4, `--live` = 실제 API(ANTHROPIC_API_KEY 필수), `--fake-media` = 테스트용. 테스트 `python -m pytest -q` → 120 passed (agent 118 + v0 2), 네트워크 없음.
5. 미검증: 실제 API 실행(`--live`)은 클라우드 세션에서 돌리지 않음 → 완료 기준(실제 API로 1편)은 맥에서 확인 필요.
6. 남은 결정(TODO(decision)): live 의 critic 임시 통과(3단계 전), Google TTS 단가($30/100만 자 가정), 스톡 최소 세로 해상도 1280px.
7. 남은 결정: Storyboard 에 description·products(선택) 추가함, 비용 상한 초과는 failed, [다시]·월 상한 기본값은 1단계 그대로.
8. 참고: 이 세션도 레포 쓰기 권한이 없어 push 는 번들로 전달. 워크플로 파일은 아직 `github-workflows/`.
9. 다음(3단계): critic(Gemini 영상 심사 + 규칙 검사: 자막·오디오 레벨·OCR), `qa_redirect` 실사용, 일부러 망친 영상 5편 eval 세트, `agent eval`.
10. 다음(3단계): QA 지적 사항을 writer·producer 입력으로 넘기는 경로 확장, rubric(`config/rubric.yaml`) 버전 관리.
