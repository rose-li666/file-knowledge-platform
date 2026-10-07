import json
import os
import threading
import time
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((PROJECT_ROOT / "model-spec.json").read_text(encoding="utf-8"))


class LocalEmbedder:
    """Shared local CPU model, serialized inference; no downloads on load."""
    def __init__(self, model_dir: Path):
        import torch
        from sentence_transformers import SentenceTransformer

        torch.set_num_threads(int(os.environ.get("MODEL_CPU_THREADS", "2")))
        manifest = json.loads((model_dir / "download-manifest.json").read_text("utf-8"))
        if manifest["revision"] != SPEC["revision"] or manifest["id"] != SPEC["id"]:
            raise ValueError("Local model revision differs from model-spec.json")
        started = time.perf_counter()
        self.model = SentenceTransformer(str(model_dir), device="cpu", local_files_only=True)
        self.dimension = self.model.get_sentence_embedding_dimension()
        if self.dimension != SPEC["dimension"]:
            raise ValueError("Unexpected embedding dimension")
        self.load_seconds = time.perf_counter() - started
        self.lock = threading.Lock()

    def encode(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        prepared = [SPEC["query_instruction"] + text for text in texts] if query else texts
        with self.lock:
            result = self.model.encode(
                prepared, normalize_embeddings=True, convert_to_numpy=True,
                batch_size=16, show_progress_bar=False,
            )
        result = np.asarray(result, dtype="<f4")
        if result.shape != (len(texts), SPEC["dimension"]) or not np.isfinite(result).all():
            raise ValueError("Invalid embedding values")
        return result
