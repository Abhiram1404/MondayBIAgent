"""
Central logging configuration. Writes all logger output to logs/app.log.
Import this module early (e.g. at app startup) so that logging from other modules goes to the log file.
"""
import logging
import sys
from pathlib import Path

# Log file path: project_root/logs/app.log
LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_FILE = LOG_DIR / "app.log"

_configured = False


def setup_logging(
    level: int = logging.INFO,
    log_file: Path | str | None = None,
    also_console: bool = False,
) -> None:
    """Configure the root logger to write to a file (and optionally the console)."""
    global _configured
    if _configured:
        return

    log_path = Path(log_file) if log_file else LOG_FILE
    log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)

    # File handler: all logs go here
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if also_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

    _configured = True


# Run setup on import so that "import logger" is enough to enable file logging
setup_logging()
