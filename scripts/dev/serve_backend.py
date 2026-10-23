"""Child entrypoint with bounded local logs; not an alternative application factory."""

import argparse
import json
from pathlib import Path

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fd", type=int)
    parser.add_argument("--check-config", action="store_true")
    arguments = parser.parse_args()
    if arguments.check_config:
        try:
            from core.config import settings

            try:
                configured = bool(settings.llm_profiles)
            except ValueError:
                configured = False
            print(json.dumps({"settings_valid": True, "models_configured": configured}))
        except Exception:
            # Validation exceptions may contain input values; never echo secrets.
            print(json.dumps({"settings_valid": False, "models_configured": False}))
        return
    if arguments.fd is None:
        parser.error("Start through scripts.dev.local_backend run")
    log = Path.cwd() / "logs/backend.log"
    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
        "handlers": {
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": str(log),
                "maxBytes": 5 * 1024 * 1024,
                "backupCount": 2,
                "encoding": "utf-8",
                "formatter": "plain",
            }
        },
        "root": {"level": "INFO", "handlers": ["file"]},
        "loggers": {"uvicorn": {"handlers": ["file"], "level": "INFO", "propagate": False}},
    }
    uvicorn.run("main:app", fd=arguments.fd, access_log=False, log_config=config)


if __name__ == "__main__":
    main()
