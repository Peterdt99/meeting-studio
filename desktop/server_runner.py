"""Detached desktop backend: closing its app window does not interrupt jobs."""
from pathlib import Path
import os
import sys

APP_DIR = Path(__file__).resolve().parent.parent
os.chdir(APP_DIR)
sys.path.insert(0, str(APP_DIR))
data = APP_DIR / "data"
data.mkdir(exist_ok=True)
sys.stdout = (data / "server-output.log").open("a", encoding="utf-8", buffering=1)
sys.stderr = (data / "server-errors.log").open("a", encoding="utf-8", buffering=1)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8766)
