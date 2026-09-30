"""명령줄 진입점.

  python -m autotube generate --topic "장마철 곰팡이" [--format problem_solution] [--mock]
  python -m autotube generate --from-queue --notify
  python -m autotube notify  --job outputs/<job_id>
  python -m autotube publish --job outputs/<job_id> [--platforms youtube,instagram] [--notify]
  python -m autotube queue add "주제" [--format myth_fact]
  python -m autotube queue list
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from autotube import pipeline
from autotube.config import load_config
from autotube.models import Job
from autotube.notify import telegram
from autotube.stages import topics
from autotube.utils import log, setup_logging


def _mock(cfg) -> None:
    cfg.set_path("providers.llm", "mock")
    cfg.set_path("providers.tts", "mock")
    cfg.set_path("providers.visuals", "placeholder")


def cmd_generate(args, cfg) -> None:
    if args.mock:
        _mock(cfg)
    job = pipeline.generate(cfg, topic=args.topic, format_id=args.format, from_queue=args.from_queue)
    print(f"완성: {job.video_path}")
    if args.notify:
        telegram.send_preview(job)


def cmd_notify(args, cfg) -> None:
    telegram.send_preview(Job.load(Path(args.job)))


def cmd_publish(args, cfg) -> None:
    platforms = args.platforms.split(",") if args.platforms else cfg.get_path("publish.platforms", ["youtube"])
    try:
        results = pipeline.publish(cfg, Path(args.job), platforms)
    except Exception as e:
        if args.notify:
            telegram.send_text(f"업로드 실패 ({Path(args.job).name}): {e}")
        raise
    msg = "\n".join(f"{k}: {v}" for k, v in results.items()) or "업로드 대상 없음"
    print(msg)
    if args.notify:
        telegram.send_text(f"업로드 완료 ({Path(args.job).name})\n{msg}\n\n네이버 클립·쇼핑 태그는 폰에서 마무리하세요.")


def cmd_queue(args, cfg) -> None:
    if args.action == "add":
        topics.add(args.topic, args.format or "")
        print(f"추가: {args.topic}")
    else:
        for row in topics._read(topics.QUEUE_PATH):
            print(f"[{row['status']}] {row['topic']} ({row['format'] or '자동'})")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="autotube", description="쇼츠 자동 생성·배포")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="영상 1편 생성")
    g.add_argument("--topic")
    g.add_argument("--format", help="channel.yaml의 formats.id")
    g.add_argument("--from-queue", action="store_true", help="data/topics.csv에서 다음 주제")
    g.add_argument("--mock", action="store_true", help="API 키 없이 가짜 대본·무음·단색 배경으로 테스트")
    g.add_argument("--notify", action="store_true", help="텔레그램 미리보기 전송")
    g.set_defaults(func=cmd_generate)

    n = sub.add_parser("notify", help="완성된 job 미리보기를 텔레그램으로 전송")
    n.add_argument("--job", required=True)
    n.set_defaults(func=cmd_notify)

    u = sub.add_parser("publish", help="승인된 job 업로드")
    u.add_argument("--job", required=True, help="outputs/<job_id>")
    u.add_argument("--platforms", help="youtube,instagram (기본: channel.yaml)")
    u.add_argument("--notify", action="store_true")
    u.set_defaults(func=cmd_publish)

    q = sub.add_parser("queue", help="주제 큐 관리")
    q.add_argument("action", choices=["add", "list"])
    q.add_argument("topic", nargs="?")
    q.add_argument("--format")
    q.set_defaults(func=cmd_queue)

    args = p.parse_args(argv)
    setup_logging(args.verbose)
    cfg = load_config()
    try:
        args.func(args, cfg)
    except Exception as e:
        log.error("%s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
