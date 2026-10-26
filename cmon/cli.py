"""命令行入口。"""
from __future__ import annotations

import argparse
import json
import sys

from . import config as config_mod
from .db import Store
from .mock.scenarios import SCENARIOS
from .output import card as card_mod
from .pipeline import Pipeline


def cmd_demo(args: argparse.Namespace) -> int:
    for name, sc in SCENARIOS.items():
        print(f"{name:14s} {sc['hours']:>3d}h  {sc['title']}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    cfg = config_mod.load()
    if args.reset and cfg.db_path.exists():
        Store(cfg.db_path).reset()

    pipe = Pipeline(cfg, args.scenario, offline=args.offline, verbose=not args.quiet)
    try:
        result = pipe.run()
    finally:
        pipe.close()

    if args.json:
        print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    cfg = config_mod.load()
    store = Store(cfg.db_path)
    metrics = store.metrics()
    events = store.recent_events(args.limit)
    date = args.date or "latest"
    path = card_mod.write_daily(cfg.out_dir, date, events, metrics)
    print(f"日报已生成：{path}")
    print(f"快照 {store.snapshot_count()} 条，事件 {store.event_count()} 个")
    for name, value in sorted(metrics.items()):
        print(f"  {name}: {value:g}")
    store.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cmon", description="淘宝商品与竞品监控 Agent")
    sub = p.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="列出可用场景")
    demo.set_defaults(func=cmd_demo)

    run = sub.add_parser("run", help="跑一个场景")
    run.add_argument("--scenario", default="price-drop")
    run.add_argument("--offline", action="store_true", help="不调模型，用本地替身")
    run.add_argument("--quiet", action="store_true")
    run.add_argument("--json", action="store_true", help="结束时打印指标 JSON")
    run.add_argument("--no-reset", dest="reset", action="store_false",
                     help="保留上次的数据，用于跨场景累积")
    run.set_defaults(func=cmd_run, reset=True)

    rep = sub.add_parser("report", help="从库里重新生成日报")
    rep.add_argument("--date", default=None)
    rep.add_argument("--limit", type=int, default=100)
    rep.set_defaults(func=cmd_report)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())