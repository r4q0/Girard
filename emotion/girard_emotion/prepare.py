"""Download the mood models if they are missing. Run: python -m girard_emotion.prepare"""
from __future__ import annotations

import shutil
import sys
import urllib.request

from .readers import MODELS

FILES = {
    "yunet.onnx": "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "hsemotion.onnx": "https://github.com/HSE-asavchenko/face-emotion-recognition/raw/main/models/affectnet_emotions/onnx/enet_b0_8_va_mtl.onnx",
    "goemotions/model.onnx": "https://huggingface.co/SamLowe/roberta-base-go_emotions-onnx/resolve/main/onnx/model_quantized.onnx",
    "goemotions/tokenizer.json": "https://huggingface.co/SamLowe/roberta-base-go_emotions-onnx/resolve/main/tokenizer.json",
    "goemotions/config.json": "https://huggingface.co/SamLowe/roberta-base-go_emotions-onnx/resolve/main/config.json",
}


def main() -> None:
    for rel, url in FILES.items():
        dest = MODELS / rel
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {rel} ...", flush=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f)
        tmp.replace(dest)
    print("Mood models ready.")


if __name__ == "__main__":
    sys.exit(main())
