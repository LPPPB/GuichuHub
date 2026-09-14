"""Runtime filesystem locations, kept outside the source checkout in production."""

from dataclasses import dataclass
from pathlib import Path


_BACKEND_DIR = Path(__file__).resolve().parent
_DEVELOPMENT_DATA_DIR = _BACKEND_DIR / "data"


@dataclass(frozen=True)
class RuntimePaths:
    business_db: Path
    auth_db: Path
    current_state: Path
    cookie_file: Path
    log_dir: Path
    backup_dir: Path

    @classmethod
    def from_environment(cls, env):
        defaults = {
            "KICHU_DB_PATH": _DEVELOPMENT_DATA_DIR / "kichu_board.db",
            "KICHU_AUTH_DB_PATH": _DEVELOPMENT_DATA_DIR / "auth.db",
            "KICHU_STATE_PATH": _DEVELOPMENT_DATA_DIR / "inspiration_db.json",
            "KICHU_COOKIE_PATH": _DEVELOPMENT_DATA_DIR / "bilibili_cookie.json",
            "KICHU_LOG_DIR": _DEVELOPMENT_DATA_DIR / "logs",
            "KICHU_BACKUP_DIR": _DEVELOPMENT_DATA_DIR / "backups",
        }

        def resolve(name):
            return Path(env.get(name) or defaults[name]).expanduser().resolve()

        return cls(
            business_db=resolve("KICHU_DB_PATH"),
            auth_db=resolve("KICHU_AUTH_DB_PATH"),
            current_state=resolve("KICHU_STATE_PATH"),
            cookie_file=resolve("KICHU_COOKIE_PATH"),
            log_dir=resolve("KICHU_LOG_DIR"),
            backup_dir=resolve("KICHU_BACKUP_DIR"),
        )

    def create_required_directories(self):
        for directory in (
            self.business_db.parent,
            self.auth_db.parent,
            self.current_state.parent,
            self.cookie_file.parent,
            self.log_dir,
            self.backup_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
