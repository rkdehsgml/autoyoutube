# AutoTube 후보 모델·서비스 리스트 (2026-09-30 조사)

신뢰도: ✅ 공식 문서 확인 / ⚠ 제3자 자료 (구현 전 재확인) / ❓ 확인 못 함. 가격은 USD.

## 1. 추천 조합
| 노드 | 1순위 | 더 좋게 | 더 싸게 |
|---|---|---|---|
| researcher | Claude Haiku 4.5 | Sonnet 5.5 | — |
| writer | Claude Sonnet 5.5 | Opus 5.5 | Haiku 4.5 |
| critic | Claude Haiku 4.5 | 애매하면 Sonnet 5.5로 재판정 | — |
| optimize / eval 판정 | Sonnet 5.5 (배치) | Opus 5.5 | — |
| 이미지 | Nano Banana 2 Lite | Nano Banana 2 | — |
| 영상 클립 | Veo 3.1 Lite | Veo 3.1 Fast | 이미지+모션만 (Veo 생략) |
| 음성(TTS) | Gemini 3.8 Flash TTS | ElevenLabs v3 | Google Cloud Standard |
| 렌더 | ffmpeg | — | — |
| 게시 | YouTube Data API v3 / Instagram Graph API | — | — |
| 네이버 클립 | 수동 업로드 (반자동) | — | — |
| 연산·DB·저장소 | GitHub Actions / D1 / R2 | — | — |

## 2. Claude API ✅ (100만 토큰당 입력 / 출력)
| 모델 | API ID | 입력 | 출력 | 배치(50%) |
|---|---|---|---|---|
| Haiku 4.5 | claude-haiku-4-5 | $1 | $5 | $0.50 / $2.50 |
| Sonnet 5.5 | claude-sonnet-5-5 | $2 | $10 | $1 / $5 |
| Opus 5.5 | claude-opus-5-5 | $4 | $20 | $2 / $10 |
- 캐시 읽기는 기본 입력가의 0.1배 (Opus 5.5는 0.05배). 배치와 캐싱은 함께 쓸 수 있음.
- 모델명은 코드에 박지 말고 config/로 분리한다.
- Gemini 저가 LLM(3.5 Flash-Lite $0.30/$2.50 등)은 후보 메모. Agent SDK는 Claude용이라 별도 어댑터가 필요하므로 지금은 Claude로 시작.

## 3. 에셋 생성
- 이미지 ✅: Nano Banana 2 Lite 장당 $0.0336(1K), Nano Banana 2 $0.045~0.151, Nano Banana Pro 약 $0.134~0.24 ⚠
- 영상 ⚠: Veo 3.1 Lite 초당 약 $0.05, Fast 약 $0.15, Standard 약 $0.40. 4·6·8초, 9:16 지원, 오디오 포함 ✅. 전부 Veo로 만들면 60초에 Lite $3 / Fast $9라서, 기본은 이미지+ffmpeg 모션 + 핵심 장면 2~3개만 Veo.
- TTS: Gemini 3.8 Flash TTS ✅ 입력 $0.50 / 출력 $9.00 (100만 토큰당, 2026년 말까지 프로모션), 100만 자 환산 약 $33 ⚠. ElevenLabs v3 약 $100/100만 자 ⚠. Google Cloud Standard 약 $4/100만 자 ⚠. 한국어 품질은 직접 들어보고 결정.

## 4. 게시
- YouTube Data API v3 ✅: 무료. 기본 `videos.insert` 하루 100회, 호출당 1쿼터. 증설은 Audit and Quota Extension Form. ❓ 미검증 API 프로젝트의 영상이 비공개로 잠기는지는 확인 못 함 → 5단계에서 첫 업로드로 테스트.
- Instagram Graph API ✅: 전문 계정 필요. Reels는 `media_type=REELS` + 공개 접근 가능한 `video_url`(R2 presigned URL). 24시간 이동 창 API 게시 100건.
- 네이버 클립 ❓: 공식 업로드 API 확인 못 함 → 텔레그램으로 파일+캡션 전송 후 수동 업로드(반자동). 브라우저 자동화는 약관·제재 위험으로 기본안에서 제외.

## 5. 인프라 ✅
- GitHub Actions: 공개 레포 표준 러너 무료. 비공개 Free 플랜 월 2,000분, 초과 Linux 2-core 분당 $0.006.
- D1 무료: 읽기 500만 행/일, 쓰기 10만 행/일, 저장 5GB.
- R2 무료: 저장 10GB, Class A 100만·Class B 1,000만 요청/월. 초과 저장 GB-월 $0.015. 이그레스 무료.

## 6. 월 비용 시뮬레이션 (하루 1편, 60초, 30일 / 모두 추정)
가정: researcher 입력 30k·출력 5k, writer 20k·4k, critic 30k·3k 토큰, 장면 이미지 12장, TTS 약 350자.
| 시나리오 | 편당 | 월 |
|---|---|---|
| A. 이미지+모션만 | 약 $0.66 | 약 $20 |
| B. Nano Banana 2 Lite + Veo Lite 24초 | 약 $1.86 | 약 $56 |
| C. NB2 고해상도 + Veo Fast 24초 | 약 $5.70 | 약 $171 |
처음엔 A로 시작, job당 상한 $1.

## 7. 구현 전 검증 목록
1. Veo 3.1 공식 초당 가격 2. 네이버 클립 업로드 방식 3. YouTube 미검증 프로젝트 비공개 잠금 4. 한국어 TTS 직접 청취 비교 5. Gemini 프로모션 종료 후 요금 6. ffmpeg 외 렌더 도구 라이선스 7. 7단계 착수 전 가격 재조사

## 출처
Claude 가격 https://platform.claude.com/docs/en/about-claude/pricing · Gemini API 가격 https://ai.google.dev/gemini-api/docs/pricing · YouTube 쿼터 https://developers.google.com/youtube/v3/determine_quota_cost · Instagram 게시 https://developers.facebook.com/docs/instagram-platform/content-publishing/ · Cloudflare R2 https://developers.cloudflare.com/r2/pricing/ · D1 https://developers.cloudflare.com/d1/platform/pricing/ · GitHub Actions 요금 https://docs.github.com/en/billing/managing-billing-for-your-products/managing-billing-for-github-actions/about-billing-for-github-actions
