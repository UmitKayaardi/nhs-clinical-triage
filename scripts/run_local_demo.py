"""
Runs the full app (FastAPI :8000 + Gradio :7860) on a COPY of the committed
database, so local demos and screenshots never modify triage_data.db.

  python scripts/run_local_demo.py            # fresh copy each start
  python scripts/run_local_demo.py --keep     # reuse the existing copy (keeps demo sessions)
"""

import argparse
import os
import runpy
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--keep", action="store_true", help="reuse .local/demo.db if it exists")
    p.add_argument("--port", type=int, default=7860)
    args = p.parse_args()
    local = ROOT / ".local"
    local.mkdir(exist_ok=True)
    demo_db = local / "demo.db"
    if not (args.keep and demo_db.exists()):
        shutil.copy2(ROOT / "triage_data.db", demo_db)
    os.environ["DATABASE_URL"] = f"sqlite:///{demo_db.as_posix()}"
    os.environ.setdefault("TWILIO_TEST_MODE", "true")
    os.environ["GRADIO_SERVER_PORT"] = str(args.port)
    os.environ.setdefault("AUDIO_TEMP_DIR", str(local / "audio"))
    ffmpeg_dir = local / "bin"
    if (ffmpeg_dir / "ffmpeg.exe").exists() or (ffmpeg_dir / "ffmpeg").exists():
        os.environ["PATH"] = str(ffmpeg_dir) + os.pathsep + os.environ.get("PATH", "")
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    sys.argv = ["app.py"]
    runpy.run_path(str(ROOT / "app.py"), run_name="__main__")


if __name__ == "__main__":
    main()
