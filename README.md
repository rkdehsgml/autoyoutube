# AutoTube — 한국어 쇼츠 자동 생성·배포 파이프라인

주제 하나 → 대본(LLM) → 음성(TTS) → 스톡 영상 → 자막 → 1080×1920 MP4 → 폰으로 미리보기 → 1탭 승인 → 업로드.

```
주제 큐/텔레그램 /new ─▶ [GitHub Actions: generate] ─▶ 텔레그램 미리보기 ─▶ [승인]
                                                                       │
                     Cloudflare Worker ◀── 버튼 콜백 ◀─────────────────┘
                            │ repository_dispatch
                            ▼
                  [GitHub Actions: publish] ─▶ YouTube / Instagram
```

> **복무 중 운영 원칙**: `publish.youtube_privacy: private`, `disclosure.enable_affiliate: false` 를 전역 전까지 유지.
> 수익화(YPP 신청·쿠팡 파트너스)는 전역 후에 켠다.

## 1. 맥북에서 바로 돌려보기 (API 키 없이)

```bash
brew install ffmpeg
cd autoyoutube
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m pytest -q                                   # 전체 파이프라인 모의 실행
python -m autotube generate --topic "장마철 원룸 곰팡이 냄새" --mock
open outputs/*/final.mp4
```

`--mock` 은 가짜 대본 + 무음 + 단색 배경입니다. 다음 순서로 하나씩 실제 공급자로 바꿉니다.

| 단계 | 설정 (`config/channel.yaml`) | 필요한 키 (`.env`) |
| --- | --- | --- |
| 음성 | `providers.tts: edge` (무료, 기본값) | 없음 |
| 스톡 영상 | `providers.visuals: pexels` | `PEXELS_API_KEY` |
| 대본 | `providers.llm: anthropic` + `llm_model` | `ANTHROPIC_API_KEY` (또는 GEMINI/OPENAI) |
| 음성(고품질) | `providers.tts: google` | `GOOGLE_TTS_API_KEY` |

```bash
cp .env.example .env    # 키 입력
python -m autotube generate --topic "자취방 겨울 외풍 막는 준비물"
python -m autotube queue add "가성비 무선청소기 고르는 기준" --format price_tier_top3
python -m autotube generate --from-queue
python -m autotube publish --job outputs/<job_id>      # YouTube 업로드(비공개)
```

## 2. 클라우드 + 폰 세팅 (1회)

1. 워크플로 파일 옮기기 (보안상 원격으로 `.github/`에 쓸 수 없어 `github-workflows/`에 두었습니다):
   ```bash
   mkdir -p .github/workflows && mv github-workflows/*.yml .github/workflows/ && rmdir github-workflows
   ```
   그다음 **GitHub 비공개 레포**로 푸시.
2. 레포 Settings → Secrets and variables → Actions
   - Secrets: `.env.example` 의 키들 (`PEXELS_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `YT_*` …)
   - Variables: `LLM_PROVIDER`, `LLM_MODEL`
3. **텔레그램 봇**: BotFather → `/newbot` → 토큰. 봇에게 아무 메시지 보낸 뒤
   `https://api.telegram.org/bot<TOKEN>/getUpdates` 에서 `chat.id` 확인.
4. **YouTube 토큰**: `python scripts/get_youtube_token.py` (파일 안 설명 참고).
5. **승인 Worker** (Cloudflare 무료 계정):
   ```bash
   cd workers/telegram-approval
   # wrangler.toml 의 GH_REPO 수정 후
   npx wrangler deploy
   npx wrangler secret put TG_BOT_TOKEN        # 나머지 3개도 동일 (wrangler.toml 주석 참고)
   curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=<워커 URL>&secret_token=<TG_WEBHOOK_SECRET>"
   ```
6. 폰에 설치: 텔레그램, GitHub, YouTube Studio, 네이버 클립 크리에이터 앱.

## 3. 매일 쓰는 법 (폰)

| 하고 싶은 것 | 방법 |
| --- | --- |
| 새 영상 주문 | 텔레그램에서 `/new 주제` |
| 자동 생성 | 매일 09:00 KST, `data/topics.csv` 큐에서 1편 |
| 승인·업로드 | 미리보기의 **[승인 · 업로드]** |
| 네이버 클립 | 같이 온 "[네이버 클립용 문구]" 복사 → 클립 앱에 영상+문구 업로드 |
| 실패 확인·재실행 | GitHub 앱 → Actions |

## 4. 구조

```
autotube/
  cli.py            generate / notify / publish / queue
  pipeline.py       단계 오케스트레이션
  stages/           topics · script · tts · visuals · subtitles · render · metadata
  publish/          youtube(videos.insert) · instagram(Reels) · storage(R2 공개 URL)
  notify/telegram.py 미리보기 + 승인 버튼
config/channel.yaml 니치·포맷·톤·공급자·배포 설정
config/prompts/     대본 프롬프트
data/               topics.csv(주제 큐) · coupang_links.csv(키워드→파트너스 링크)
workers/            텔레그램 → GitHub 중계 Worker
.github/workflows/  generate.yml · publish.yml
```

## 5. 정책 체크 (코드에 반영됨)

- **비진정성 콘텐츠**: 포맷 4종 로테이션, 대본마다 `insight`(채널 고유 판단 기준) 필수, 최근 제목 중복 방지.
- **AI 표기**: AI 영상 클립을 쓴 편만 `containsSyntheticMedia=true`.
- **대가성 문구**: `enable_affiliate: true` 일 때 설명 첫 줄·인스타 캡션에 자동 삽입(+ `#광고 #제휴링크`).
- **API 제약**: 감사 전 YouTube API 업로드는 비공개 고정 → 공개 운영 2~3개월 전에 감사 신청.

## 6. 다음에 붙일 것 (TODO)

- [ ] `visuals.generate_ai_clip` — Veo / Kling / Hailuo 중 하나 연결
- [ ] 주간 성과 리포트: YouTube Analytics API → 상위 주제를 큐에 자동 추가
- [ ] 쿠팡 파트너스 API(최종승인 후) 로 `coupang_links.csv` 자동 채우기
- [ ] BGM 폴더 로테이션
