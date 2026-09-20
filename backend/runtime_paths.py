"""Runtime filesystem locations, kept outside the source checkout in production."""

from dataclasses import dataclass
from pathlib import Path


_BACKEND_DIR = Path(__file__).resolve().parent
_DEVELOPMENT_DATA_DIR = _BACKEND_DIR / "data"


@dataclass(frozen=True)
class RuntimePaths:
    cookie_file: Path
    log_dir: Path

    @classmethod
    def from_environment(cls, env):
        defaults = {
            "KICHU_COOKIE_PATH": _DEVELOPMENT_DATA_DIR / "bilibili_cookie.json",
            "KICHU_LOG_DIR": _DEVELOPMENT_DATA_DIR / "logs",
        }

        def resolve(name):
            return Path(env.get(name) or defaults[name]).expanduser().resolve()

        return cls(
            cookie_file=resolve("KICHU_COOKIE_PATH"),
            log_dir=resolve("KICHU_LOG_DIR"),
        )

    def create_required_directories(self):
        for directory in (
            self.cookie_file.parent,
            self.log_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
