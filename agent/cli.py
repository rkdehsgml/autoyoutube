"""agent CLI.

  python -m agent local --topic "장마철 원룸 곰팡이"          # mock: 외부 호출 없이 진짜 mp4 까지
  python -m agent local --live --topic "장마철 원룸 곰팡이"   # 실제 API (Agent SDK·TTS·Pexels)
  python -m agent local --job-id <ID>                        # 기존 job 이어서 진행
  python -m agent status [--job-id <ID>]
  python -m agent decide <ID> approve|reject|redo [--reason ...]

기본 실행은 항상 mock 이다. 실제 외부 API 호출은 --live 를 줄 때만.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from agent.adapters.blob_local import LocalBlobStore
from agent.adapters.notify_memory import MemoryNotifier
from agent.adapters.store_sqlite import SqliteStore
from agent.core.channel import load_dotenv
from agent.media.ffmpeg import require_ffmpeg
from agent.orchestrator import Orchestrator, apply_decision
from agent.roles.mock import MockRoles
from agent.roles.registry import build_handlers, deps_for

ROOT = Path(__file__).resolve().parent.parent
LOCAL_DIR = ROOT / "outputs" / "local"
DECISIONS = {"approve": "approved", "reject": "rejected", "redo": "redo"}


def _stores(args) -> tuple[SqliteStore, LocalBlobStore]:
    env = os.environ.get("AUTOTUBE_ENV", "local")
    if env != "local":
        raise SystemExit(f"AUTOTUBE_ENV={env} 는 아직 지원하지 않습니다 (D1·R2 어댑터는 4단계).")
    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)
    return SqliteStore(db), LocalBlobStore(args.media)


AUTH_ENV = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")


def _mode(args) -> str:
    if args.live:
        return "live"
    return "fast" if args.fake_media else "mock"


def cmd_local(args) -> int:
    mode = _mode(args)
    if mode == "live":
        load_dotenv(Path(args.env_file))
        if not any(os.getenv(k) for k in AUTH_ENV):
            print("--live 는 ANTHROPIC_API_KEY 가 필요합니다 (.env 또는 환경변수).", file=sys.stderr)
            return 2
    if mode != "fast":
        try:
            require_ffmpeg()
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            return 2
    store, blobs = _stores(args)
    notifier = MemoryNotifier(echo=not args.quiet)
    warn = (lambda m: None) if args.quiet else (lambda m: print(f"[경고] {m}", file=sys.stderr))
    mock = MockRoles(qa_failures=args.qa_fail, redo_from=args.redo_from)
    try:
        deps = None if mode == "fast" else deps_for(mode, warn=warn)
    except RuntimeError as e:  # 공급자 키 누락 등
        print(str(e), file=sys.stderr)
        return 2
    orch = Orchestrator(store, blobs, build_handlers(mode, deps, mock), notifier=notifier)
    if args.job_id:
        job = store.get_job(args.job_id)
    else:
        job = store.create_job("manual", requested_topic=args.topic, format_id=args.format)
    owner = f"local-{os.getpid()}"
    job = asyncio.run(orch.advance(job.id, owner))
    arts = store.artifacts(job.id)
    finals = [a for a in arts if a.kind == "final"]
    print(f"job {job.id}: {job.state}  (비용 ${job.cost_usd:.3f}, QA 재작업 {job.qa_rounds}회, 산출물 {len(arts)}개)")
    if job.error:
        print(f"  오류: {job.error}")
    if finals:
        print(f"  final: {blobs.local_path(finals[0].r2_key)}")
    if job.state == "awaiting_approval":
        print(f"  다음: python -m agent decide {job.id} approve|reject|redo")
    return 0 if job.state in ("awaiting_approval", "needs_human") else 1


def cmd_status(args) -> int:
    store, _ = _stores(args)
    if args.job_id:
        job = store.get_job(args.job_id)
        print(f"{job.id}  {job.state}  ${job.cost_usd:.3f}  topic={job.requested_topic or job.topic_id}")
        for r in store.step_runs(job.id):
            print(f"  {r.id:>3} {r.step:<17} {r.role or '-':<10} {r.status:<7} ${r.cost_usd or 0:.3f} {r.error or ''}")
        return 0
    jobs = store.list_jobs(limit=args.limit)
    if not jobs:
        print("job 없음")
    for j in jobs:
        print(f"{j.id}  {j.state:<17} ${j.cost_usd:.3f}  {j.created_at}  {j.requested_topic or ''}")
    return 0


def cmd_decide(args) -> int:
    store, _ = _stores(args)
    try:
        job = apply_decision(store, args.job_id, DECISIONS[args.decision], args.reason)
    except (ValueError, KeyError) as e:
        print(f"적용 실패: {e}", file=sys.stderr)
        return 1
    print(f"job {job.id}: {job.state}")
    if job.state == "storyboarding":
        print(f"  다음: python -m agent local --job-id {job.id}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agent", description="AutoTube 에이전트")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default=str(LOCAL_DIR / "agent.db"), help="SQLite 경로 (D1 대신)")
    common.add_argument("--media", default=str(LOCAL_DIR / "media"), help="미디어 폴더 (R2 대신)")
    sub = p.add_subparsers(dest="cmd", required=True)

    lp = sub.add_parser("local", parents=[common], help="로컬에서 job 하나를 awaiting_approval 까지 진행")
    mode = lp.add_mutually_exclusive_group()
    mode.add_argument("--mock", action="store_true", default=True,
                      help="가짜 역할 + 무음 음성 + 단색 배경으로 진짜 mp4 (기본, 외부 호출 없음)")
    mode.add_argument("--live", action="store_true", help="실제 API 호출 (Agent SDK·TTS·Pexels)")
    mode.add_argument("--fake-media", action="store_true", help="렌더 없이 자리표시 바이트만 (테스트용, 가장 빠름)")
    lp.add_argument("--env-file", default=str(ROOT / ".env"), help="--live 에서 읽을 .env 경로")
    lp.add_argument("--topic", default=None, help="요청 주제 (/new 와 같음)")
    lp.add_argument("--format", default=None, help="포맷 id (config/channel.yaml)")
    lp.add_argument("--job-id", default=None, help="기존 job 이어서 진행")
    lp.add_argument("--qa-fail", type=int, default=0, help="mock critic 이 처음 N번 불합격")
    lp.add_argument("--redo-from", default="producing_assets",
                    choices=["storyboarding", "producing_assets", "rendering"])
    lp.add_argument("--quiet", action="store_true")
    lp.set_defaults(func=cmd_local)

    sp = sub.add_parser("status", parents=[common], help="job 목록·상세")
    sp.add_argument("--job-id", default=None)
    sp.add_argument("--limit", type=int, default=20)
    sp.set_defaults(func=cmd_status)

    dp = sub.add_parser("decide", parents=[common], help="승인·거절·[다시] (로컬에서 Worker 대신)")
    dp.add_argument("job_id")
    dp.add_argument("decision", choices=list(DECISIONS))
    dp.add_argument("--reason", default=None)
    dp.set_defaults(func=cmd_decide)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
