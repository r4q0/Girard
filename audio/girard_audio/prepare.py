"""Download the speech models if they are missing. Run: python -m girard_audio.prepare"""
from __future__ import annotations

import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from .stt import MODELS, PARAKEET

RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"
PARAKEET_TAR = "sherpa-onnx-nemo-parakeet-unified-en-0.6b-int8-non-streaming"


def fetch(url: str, dest: Path) -> None:
    print(f"Downloading {url.rsplit('/', 1)[-1]} ...", flush=True)
    with urllib.request.urlopen(url) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def main() -> None:
    MODELS.mkdir(parents=True, exist_ok=True)
    vad = MODELS / "silero_vad.onnx"
    if not vad.exists():
        fetch(f"{RELEASES}/silero_vad.onnx", vad)
    if not (PARAKEET / "encoder.int8.onnx").exists():
        with tempfile.TemporaryDirectory() as tmp:
            tar = Path(tmp) / "model.tar.bz2"
            fetch(f"{RELEASES}/{PARAKEET_TAR}.tar.bz2", tar)
            print("Unpacking ...", flush=True)
            with tarfile.open(tar) as t:
                t.extractall(tmp, filter="data")
            shutil.move(str(Path(tmp) / PARAKEET_TAR), PARAKEET)
    print("Speech models ready.")


if __name__ == "__main__":
    sys.exit(main())
