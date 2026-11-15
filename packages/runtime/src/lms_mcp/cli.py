import argparse
import asyncio
import getpass
import json
import os
import sys
from pathlib import Path

from .auth import AuthManager
from .browser import detect_browsers
from .client import LMSClient
from .config import Config, LMSError
from .session import SessionStore, parse_cookies


def output(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


async def run_command(args, config):
    store = SessionStore(config.data_dir)
    auth = AuthManager(store)
    if args.command == "login":
        await auth.begin(args.browser, args.timeout)
        previous = None
        try:
            while auth.busy():
                status = auth.status()["login"]
                if status["state"] != previous:
                    print(status["message"], file=sys.stderr)
                    previous = status["state"]
                await asyncio.sleep(0.5)
            result = auth.status()
            output(result)
            return 0 if result["login"]["state"] == "authenticated" else 1
        finally:
            await auth.close()
    if args.command == "import-cookie":
        if args.file:
            path = Path(args.file).expanduser()
            if path.stat().st_size > 1024 * 1024:
                raise LMSError("Cookie-файл превышает 1 МиБ")
            text = path.read_text()
        elif args.stdin:
            text = sys.stdin.read(1024 * 1024 + 1)
            if len(text) > 1024 * 1024:
                raise LMSError("Ввод превышает 1 МиБ")
        else:
            text = getpass.getpass("Cookie (ввод скрыт): ")
        output(await auth.import_cookies(parse_cookies(text, args.service), args.service))
    elif args.command == "status":
        result = auth.status()
        if args.validate:
            profile = await LMSClient(store).get("/api/micro-lms/students/me")
            if not isinstance(profile, dict) or "lateDaysBalance" not in profile:
                raise LMSError("Неожиданная схема профиля LMS")
            result["validated"] = True
        output(result)
    elif args.command == "logout":
        store.clear(args.service)
        output({"forgotten": True, "service": args.service})
    return 0


def main():
    parser = argparse.ArgumentParser(description="Local Central University LMS MCP (stdio)")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="Run local MCP over stdin/stdout (default)")
    serve.add_argument("--compact", action="store_true", help="Small tool set for chat clients")
    updates = sub.add_parser(
        "updates", help="Check GitHub release and repository revision; never installs code"
    )
    updates.add_argument("--repository")
    updates.add_argument("--force", action="store_true")
    sub.add_parser("browsers", help="List installed browsers")
    run = sub.add_parser("run", help="Execute one method or a batch locally from JSON")
    sources = run.add_mutually_exclusive_group(required=True)
    sources.add_argument("--stdin", action="store_true")
    sources.add_argument("--file")
    methods = sub.add_parser("methods", help="Print local method schemas")
    methods.add_argument("--name", action="append")
    login = sub.add_parser("login", help="Open browser and capture the session after manual sign-in")
    login.add_argument("--browser", default="auto")
    login.add_argument("--timeout", type=int, default=300)
    cookie = sub.add_parser("import-cookie", help="Import Cookie header, cookie JSON or Netscape file")
    source = cookie.add_mutually_exclusive_group()
    source.add_argument("--file")
    source.add_argument("--stdin", action="store_true")
    cookie.add_argument("--service", choices=["lms", "note"], default="lms")
    status = sub.add_parser("status")
    status.add_argument("--validate", action="store_true")
    logout = sub.add_parser("logout", help="Forget local session; does not log out on the portal")
    logout.add_argument("--service", choices=["lms", "note"], default="lms")
    sub.add_parser("config", help="Print a local stdio mcpServers configuration")
    args = parser.parse_args()
    config = Config.from_env()
    os.environ.setdefault("SE_CACHE_PATH", str(config.data_dir / "selenium"))
    try:
        from .updates import check_updates, notify_update

        if args.command == "updates":
            output(asyncio.run(check_updates(config, force=args.force, repository=args.repository)))
            return 0
        if args.command in (None, "serve", "run"):
            asyncio.run(notify_update(config))
        if args.command in (None, "serve"):
            from .server import create_server

            create_server(config, compact=getattr(args, "compact", False)).run(transport="stdio")
            return 0
        if args.command == "browsers":
            output({"browsers": [b.as_dict() for b in detect_browsers()]})
            return 0
        if args.command == "config":
            output(
                {
                    "mcpServers": {
                        "cu-lms": {
                            "command": sys.executable,
                            "args": ["-m", "lms_mcp", "serve"],
                            "env": {"LMS_MCP_DATA_DIR": str(config.data_dir)},
                        }
                    }
                }
            )
            return 0
        if args.command in ("run", "methods"):
            from .runner import LocalRunner

            runner = LocalRunner(config)
            if args.command == "methods":
                result = asyncio.run(runner.methods())
                if args.name:
                    if any(name not in result for name in args.name):
                        raise LMSError("Неизвестное имя метода")
                    result = {name: result[name] for name in args.name}
                output(result)
                return 0
            if args.file:
                path = Path(args.file).expanduser()
                if path.stat().st_size > 2 * 1024 * 1024:
                    raise LMSError("Запрос превышает 2 МиБ")
                text = path.read_text()
            else:
                text = sys.stdin.read(2 * 1024 * 1024 + 1)
                if len(text) > 2 * 1024 * 1024:
                    raise LMSError("Запрос превышает 2 МиБ")
            try:
                request = json.loads(text)
            except ValueError:
                raise LMSError("Некорректный JSON запроса") from None
            result = asyncio.run(runner.run(request))
            output(result)
            return 0 if result["ok"] else 1
        return asyncio.run(run_command(args, config))
    except LMSError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Операция отменена", file=sys.stderr)
        return 130
    except OSError:
        print(
            "Не удалось прочитать/записать локальный файл. Проверьте путь и права доступа.", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
