"""YouTube 업로드용 refresh token 1회 발급 (맥북에서 실행).

1. Google Cloud 콘솔 → YouTube Data API v3 사용 설정
2. OAuth 동의 화면: 외부, 게시 상태를 '프로덕션'으로 (테스트 상태면 토큰이 7일 뒤 만료)
3. OAuth 클라이언트 ID(데스크톱 앱) 생성 → JSON을 client_secret.json 으로 저장
4. python scripts/get_youtube_token.py → 브라우저 로그인(업로드할 채널 계정)
5. 출력된 값 3개를 .env 와 GitHub Secrets에 등록
"""
import json
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
secret = Path(sys.argv[1] if len(sys.argv) > 1 else "client_secret.json")

flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
client = json.loads(secret.read_text())["installed"]

print("\n.env / GitHub Secrets에 등록하세요:")
print(f"YT_CLIENT_ID={client['client_id']}")
print(f"YT_CLIENT_SECRET={client['client_secret']}")
print(f"YT_REFRESH_TOKEN={creds.refresh_token}")
