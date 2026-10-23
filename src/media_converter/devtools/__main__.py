import argparse
import json
from pathlib import Path

from media_converter.common.errors import AppError
from media_converter.config import AppPaths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="视频转换器开发工具（仅显示已实现命令）")
    commands = parser.add_subparsers(dest="command", required=True)
    agent = commands.add_parser("bench-agent", help="真人验收后显式启用的真实在线验收")
    agent.add_argument("--sessions", type=int, default=5)
    agent.add_argument("--turns-per-session", type=int, default=3)
    agent.add_argument("--live-api", action="store_true")
    agent.add_argument("--data-dir", default="data")
    agent.add_argument("--output", type=Path, required=True)
    video = commands.add_parser("bench-video", help="52 视频真实桌面压力与本地 AI 并行")
    video.add_argument("--profile", choices=["agreed", "long-1080p"], default="agreed")
    video.add_argument("--root", "--fixture-root", type=Path, required=True)
    video.add_argument("--data-dir", default="data")
    video.add_argument("--with-agent-local", action="store_true")
    video.add_argument("--output", type=Path, required=True)
    load = commands.add_parser("bench-mcp", help="真实本地 MCP 3×100 混合负载")
    load.add_argument("--profile", choices=["mixed", "real-local", "faults"], default="real-local")
    load.add_argument("--rounds", type=int, default=3)
    load.add_argument("--concurrent", "--client-concurrency", type=int, default=100)
    load.add_argument("--requests", type=int, choices=[100], default=100)
    load.add_argument("--faults", action="store_true")
    load.add_argument("--data-dir", default="data")
    load.add_argument("--output", required=True, type=Path)
    evaluate = commands.add_parser("eval-rag", help="固定评估集真实检索消融；不伪造人工确认")
    evaluate.add_argument("--dataset", type=Path, required=True)
    evaluate.add_argument("--data-dir", default="data")
    evaluate.add_argument("--output", type=Path, required=True)
    build = commands.add_parser("build-windows", help="构建本地验收候选包")
    build.add_argument("--components", choices=["core", "tools", "all"], default="all")
    build.add_argument("--data-dir", default="data")
    build.add_argument("--output", type=Path, default=Path("dist"))
    smoke = commands.add_parser("smoke-package", help="新目录和隔离 PATH 的真实包测试")
    smoke.add_argument("--package", required=True, type=Path)
    smoke.add_argument("--without-dev-path", action="store_true")
    smoke.add_argument("--output", required=True, type=Path)
    doctor = commands.add_parser("doctor", help="检查实际本地工具链，不调用在线模型")
    doctor.add_argument("--require", choices=["core", "all-local"], default="all-local")
    doctor.add_argument("--data-dir", default="data")
    doctor.add_argument("--output", type=Path)
    prepare = commands.add_parser("prepare", help="检查、复用或准备经过校验的本地组件")
    prepare.add_argument("--components", choices=["core", "ai"], required=True)
    prepare.add_argument("--mode", choices=["reuse", "private"], default="reuse")
    prepare.add_argument("--environment-root", type=Path, default=Path("environment"))
    prepare.add_argument("--data-dir", help="本地运行数据目录")
    prepare.add_argument("--output", type=Path)
    prepare.add_argument("--ffmpeg", help="显式 FFmpeg 路径")
    prepare.add_argument("--ffprobe", help="显式 ffprobe 路径")
    fixtures = commands.add_parser("fixtures", help="生成自有小型媒体与文档素材")
    fixtures.add_argument("--profile", choices=["smoke", "pressure"], required=True)
    fixtures.add_argument("--root", type=Path, required=True)
    fixtures.add_argument("--data-dir", help="本地运行数据目录")
    for name, help_text in (
        ("configure-ai", "复用已有本地 AI 环境，不下载"),
        ("knowledge-build", "构建并切换内置知识索引"),
        ("init-agent-db", "初始化隔离项目 MySQL 库"),
        ("sync-mysql", "补同步本地 outbox"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--data-dir", default="data")
        command.add_argument("--output", type=Path)
        if name == "configure-ai":
            command.add_argument("--environment-root", type=Path, default=Path("environment"))
        if name in {"knowledge-build", "init-agent-db"}:
            command.add_argument("--root", type=Path, default=Path("knowledge"))
        if name == "init-agent-db":
            command.add_argument(
                "--stdin-credentials", action="store_true", help="仅从 stdin 读取初始化凭据"
            )
    args = parser.parse_args(argv)

    from media_converter.media.toolchain import inspect_toolchain

    try:
        if args.command == "bench-agent":
            import asyncio

            from media_converter.devtools.bench_agent import benchmark

            result = asyncio.run(
                benchmark(
                    args.data_dir,
                    args.output,
                    live_api=args.live_api,
                    sessions=args.sessions,
                    turns_per_session=args.turns_per_session,
                )
            )
            print(
                json.dumps({"status": result["status"], "online_called": result["online_called"]})
            )
            return 0 if result.get("automatic_passed") else 2
        if args.command == "bench-video":
            from media_converter.devtools.bench_mcp import write_report
            from media_converter.devtools.bench_video import benchmark
            from media_converter.devtools.resources import ResourceMonitor

            with ResourceMonitor() as monitor:
                result = benchmark(args.root, args.data_dir, args.output)
            result["resources"] = monitor.report()
            write_report(args.output, result)
            print(json.dumps({"ok": result["ok"], "seconds": result.get("seconds")}))
            return 0 if result["ok"] else 2
        if args.command == "bench-mcp":
            import asyncio

            from media_converter.devtools.bench_mcp import benchmark, write_report
            from media_converter.devtools.resources import ResourceMonitor

            with ResourceMonitor() as monitor:
                result = asyncio.run(
                    benchmark(
                        args.data_dir,
                        args.output,
                        rounds=args.rounds,
                        concurrent=args.concurrent,
                        with_faults=args.faults or args.profile == "faults",
                    )
                )
            result["resources"] = monitor.report()
            write_report(args.output, result)
            print(json.dumps({"ok": result["ok"], "rounds": len(result["rounds"])}))
            return 0 if result["ok"] else 2
        if args.command == "eval-rag":
            import asyncio

            from media_converter.devtools.eval_rag import evaluate

            result = asyncio.run(evaluate(args.dataset, args.data_dir, args.output))
            print(json.dumps({k: v for k, v in result.items() if k != "cases"}))
            return 0 if result["automatic_gate_passed"] else 2
        if args.command == "build-windows":
            from media_converter.devtools.build_windows import build

            print(json.dumps(build(args.output, args.data_dir, args.components)))
            return 0
        if args.command == "smoke-package":
            from media_converter.devtools.smoke_package import smoke

            result = smoke(args.package, args.output, args.without_dev_path)
            return 0 if result["ok"] else 2
        if args.command == "doctor":
            import asyncio

            from media_converter.services.health import HealthService

            result = asyncio.run(HealthService(args.data_dir).inspect(require=args.require))
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result["ok"] else 2
        if args.command in {"configure-ai", "knowledge-build", "init-agent-db", "sync-mysql"}:
            from media_converter.devtools.agent_setup import run_command

            print(json.dumps(run_command(args), ensure_ascii=False))
            return 0
        if args.command == "fixtures":
            if args.profile == "pressure":
                from media_converter.devtools.pressure_fixtures import generate

                value = generate(args.root, AppPaths.from_argument(args.data_dir).data_dir)
                print(json.dumps({"ok": True, "profile": "pressure", "files": len(value["files"])}))
                return 0
            from media_converter.devtools.fixtures import generate_smoke_fixtures

            manifest = generate_smoke_fixtures(args.root, AppPaths.from_argument(args.data_dir))
            print(
                json.dumps(
                    {
                        "ok": True,
                        "profile": "smoke",
                        "file_count": len(manifest["files"]),
                        "manifest": str(args.root.resolve() / "manifest.json"),
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        if args.command == "prepare" and not (args.ffmpeg or args.ffprobe):
            import asyncio

            from media_converter.services.preparer import SetupService

            async def prepare_components():
                from PySide6.QtCore import QLockFile

                service = SetupService(
                    AppPaths.from_argument(args.data_dir).data_dir,
                    environment_root=args.environment_root,
                )
                lease = QLockFile(str(service.root / "application.lock"))
                if not lease.tryLock(0):
                    from media_converter.common.errors import ErrorCode

                    raise AppError(ErrorCode.INVALID_STATE)
                try:
                    value = await service.prepare(mode=args.mode, components=args.components)
                    if (service.root / "private-components.json").exists():
                        value["private_services_stopped_after_check"] = True
                    return value
                finally:
                    try:
                        await service.close()
                    finally:
                        lease.unlock()

            result = asyncio.run(prepare_components())
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result["ok"] else 2
        snapshot = inspect_toolchain(
            AppPaths.from_argument(args.data_dir),
            ffmpeg=Path(args.ffmpeg) if args.ffmpeg else None,
            ffprobe=Path(args.ffprobe) if args.ffprobe else None,
        )
        print(
            json.dumps(
                {
                    "ok": snapshot.ready,
                    "ffmpeg_version": snapshot.ffmpeg_version,
                    "ffprobe_version": snapshot.ffprobe_version,
                    "missing_encoders": snapshot.missing_encoders,
                    "missing_muxers": snapshot.missing_muxers,
                },
                ensure_ascii=False,
            )
        )
        return 0 if snapshot.ready else 2
    except AppError as error:
        result = {"ok": False, "error_code": error.info.code, "message": error.info.message}
        if args.command != "build-windows" and getattr(args, "output", None):
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
        print(
            json.dumps(
                result,
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
