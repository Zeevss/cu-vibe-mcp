#!/usr/bin/env python3
"""Build a self-contained plugin from an explicit source allowlist."""

import argparse
import hashlib
import json
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def write_zip(path, files):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)


def build(output, repository=None, revision=None):
    from lms_mcp.updates import identity, repository_name

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    repo, current = identity()
    repo = repository_name(repository) if repository else repo
    revision = revision or current
    version = tomllib.loads((ROOT / "packages/runtime/pyproject.toml").read_text())["project"]["version"]
    names = [
        "README.md",
        "docs/chat-clients.md",
        "docs/distribution.md",
        "docs/local-runtime.md",
        "plugin.json",
        "mcp.json",
        ".mcp.json",
        ".codex-plugin/plugin.json",
        ".claude-plugin/plugin.json",
        ".claude-plugin/marketplace.json",
        ".agents/plugins/marketplace.json",
        "install.py",
        "tools/client_config.py",
        "skills/cu-lms/SKILL.md",
        "skills/cu-lms/scripts/bootstrap.py",
        "packages/runtime/README.md",
        "packages/runtime/pyproject.toml",
        "packages/runtime/uv.lock",
    ]
    files = {name: (ROOT / name).read_bytes() for name in names}
    for path in (ROOT / "packages/runtime/src/lms_mcp").glob("*"):
        if path.suffix in (".py", ".json"):
            files[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    files["packages/runtime/src/lms_mcp/repository.json"] = encoded(
        {"repository": repo, "revision": revision}
    )
    for name in ["plugin.json", ".codex-plugin/plugin.json", ".claude-plugin/plugin.json"]:
        if json.loads(files[name])["version"] != version:
            raise ValueError(f"{name}: version differs from runtime")
    archive = output / f"cu-lms-plugin-{version}.zip"
    write_zip(archive, files)
    for name, data in files.items():
        target = output / "plugin" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    result = {
        "version": version,
        "repository": repo,
        "revision": revision,
        "filename": archive.name,
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "size": archive.stat().st_size,
    }
    (output / "release.json").write_bytes(encoded(result))
    (output / "SHA256SUMS").write_text(f"{result['sha256']}  {archive.name}\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/release")
    parser.add_argument("--repository", help="GitHub owner/repo, inferred from origin when available")
    parser.add_argument("--revision")
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.repository, args.revision), indent=2))


if __name__ == "__main__":
    main()
