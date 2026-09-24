"""The two local readers: the largest face on screen, and the words the prospect says."""
from __future__ import annotations

import json
import os
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

MODELS = Path(os.environ.get("GIRARD_EMOTION_MODELS", Path(__file__).resolve().parents[1] / "models"))
FACE_CLASSES = ["anger", "contempt", "disgust", "fear", "happiness", "neutral", "sadness", "surprise"]
DETECT_WIDTH = 960   # faces are found on a downscaled screen (still finds 60 px faces); the crop is full resolution
MIN_FACE_PX = 40     # smaller faces are too blurry to read


def _session(path: Path) -> ort.InferenceSession:
    # One thread each: this engine must never compete with speech-to-text for the CPU.
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 1
    opts.inter_op_num_threads = 1
    return ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max())
    return e / e.sum()


class FaceReader:
    """YuNet finds faces; HSEmotion (enet_b0_8_va_mtl) reads the largest one."""

    MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

    def __init__(self):
        self.detector = cv2.FaceDetectorYN.create(str(MODELS / "yunet.onnx"), "", (320, 320), 0.7, 0.3, 50)
        self.emotions = _session(MODELS / "hsemotion.onnx")

    def read(self, bgra: np.ndarray) -> dict | None:
        """Returns {probs: {class: p}, valence, arousal, size} for the largest face, or None."""
        h, w = bgra.shape[:2]
        scale = min(1.0, DETECT_WIDTH / w)
        small = cv2.resize(bgra, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else bgra
        small = cv2.cvtColor(small, cv2.COLOR_BGRA2BGR)
        self.detector.setInputSize((small.shape[1], small.shape[0]))
        _, faces = self.detector.detect(small)
        if faces is None or not len(faces):
            return None
        x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])[:4] / scale
        if min(fw, fh) < MIN_FACE_PX:
            return None
        m = 0.1  # a little margin, like the training crops
        x0, y0 = int(max(0, x - m * fw)), int(max(0, y - m * fh))
        x1, y1 = int(min(w, x + fw * (1 + m))), int(min(h, y + fh * (1 + m)))
        face = cv2.cvtColor(bgra[y0:y1, x0:x1], cv2.COLOR_BGRA2RGB)
        face = cv2.resize(face, (224, 224)).astype(np.float32) / 255.0
        face = ((face - self.MEAN) / self.STD).transpose(2, 0, 1)[None]
        out = self.emotions.run(None, {"input": face})[0][0]
        probs = _softmax(out[:8])
        return {
            "probs": dict(zip(FACE_CLASSES, probs.tolist())),
            "valence": float(np.clip(out[8], -1, 1)),
            "arousal": float(np.clip(out[9], -1, 1)),
            "size": int(min(fw, fh)),
        }


class TextReader:
    """RoBERTa trained on GoEmotions (28 labels, int8 ONNX)."""

    def __init__(self):
        d = MODELS / "goemotions"
        self.tokenizer = Tokenizer.from_file(str(d / "tokenizer.json"))
        self.tokenizer.enable_truncation(128)
        self.labels = list(json.loads((d / "config.json").read_text(encoding="utf-8"))["id2label"].values())
        self.session = _session(d / "model.onnx")

    def read(self, text: str) -> dict[str, float]:
        enc = self.tokenizer.encode(text)
        ids = np.array([enc.ids], dtype=np.int64)
        mask = np.array([enc.attention_mask], dtype=np.int64)
        logits = self.session.run(None, {"input_ids": ids, "attention_mask": mask})[0][0]
        probs = 1 / (1 + np.exp(-logits))  # multi-label: each emotion scored on its own
        return dict(zip(self.labels, probs.tolist()))
