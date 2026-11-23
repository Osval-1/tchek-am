import os
from pathlib import Path

import environ

# Must run before importing base, which reads os.environ at import time.
environ.Env.read_env(Path(__file__).resolve().parents[3] / ".env")
os.environ.setdefault("DEBUG", "True")

from .base import *  # noqa: E402,F403
