import importlib.util
import json
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load("tools/build_release.py", "builder")
bootstrap = load("skills/cu-lms/scripts/bootstrap.py", "bootstrap")
clients = load("tools/client_config.py", "clients")


def test_reproducible_bundle_includes_runtime_and_no_secrets(tmp_path):
    one = builder.build(tmp_path / "a", "example/repo", "a" * 40)
    two = builder.build(tmp_path / "b", "example/repo", "a" * 40)
    assert one == two
    with zipfile.ZipFile(tmp_path / "a" / one["filename"]) as archive:
        names = archive.namelist()
        assert "packages/runtime/src/lms_mcp/cli.py" in names
        assert "packages/runtime/uv.lock" in names
        assert not any(
            ".venv" in name or name.endswith("session.json") or name.startswith("services/") for name in names
        )
        metadata = json.loads(archive.read("packages/runtime/src/lms_mcp/repository.json"))
        assert metadata == {"repository": "example/repo", "revision": "a" * 40}
        for path in ["mcp.json", ".mcp.json"]:
            entry = json.loads(archive.read(path))["mcpServers"]["cu-lms"]
            assert entry["command"] == "uv"
            assert entry["args"][-2:] == ["serve", "--compact"]
            assert "url" not in entry


def test_launcher_uses_bundled_frozen_runtime(tmp_path):
    with patch.object(bootstrap.shutil, "which", return_value="/bin/uv"):
        argv = bootstrap.command(["run", "--stdin"], ROOT)
    assert argv == [
        "/bin/uv",
        "run",
        "--directory",
        str(ROOT / "packages/runtime"),
        "--frozen",
        "--no-dev",
        "cu-lms-mcp",
        "run",
        "--stdin",
    ]


def test_chat_client_config_uses_absolute_command():
    with patch.object(clients.shutil, "which", return_value="/bin/uv"):
        argv = clients.launch_command(ROOT)
    assert Path(argv[0]).is_absolute()
    assert argv[-2:] == ["serve", "--compact"]
