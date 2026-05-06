import multiprocessing
import os
import sys
import logging
from pathlib import Path
from datetime import datetime

os.environ['QT_LOGGING_RULES'] = '*.debug=false'

open("startup.log", "w").write(f"{datetime.now()}: starting main.py\n")

def find_dotenv():
    # If running as PyInstaller EXE, check executable's directory
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).parent
        env_file = exe_dir / ".env"
        if env_file.exists():
            return env_file

    # Check source directory (when running from source)
    source_dir = Path(__file__).parent
    env_file = source_dir / ".env"
    if env_file.exists():
        return env_file

    # Check current working directory
    env_file = Path.cwd() / ".env"
    if env_file.exists():
        return env_file

    return None

_env_file = find_dotenv()
if _env_file:
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file)
    except ImportError:
        pass

from eternal_quotex_bot.app import main


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
