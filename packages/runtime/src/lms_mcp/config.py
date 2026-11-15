import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_path

PORTAL = "https://my.centraluniversity.ru"
NOTE = "https://note.cu.ru"
ORIGINS = {"lms": PORTAL, "note": NOTE}


@dataclass(frozen=True)
class Config:
    data_dir: Path
    max_download_bytes: int = 50 * 1024 * 1024

    @classmethod
    def from_env(cls):
        root = os.environ.get("LMS_MCP_DATA_DIR")
        return cls(Path(root).expanduser() if root else user_data_path("cu-lms-mcp", appauthor=False))


class LMSError(Exception):
    """A deliberately credential-free message suitable for an MCP response."""


class AuthRequired(LMSError):
    pass
