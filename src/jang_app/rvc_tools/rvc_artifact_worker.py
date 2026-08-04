from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path


FEATURE_WIDTH = 768
RANDOM_SEED = 1234


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    index_parser = subparsers.add_parser("build-index")
    index_parser.add_argument("feature_dir", type=Path)
    index_parser.add_argument("output_dir", type=Path)
    index_parser.add_argument("model_name")
    inspect_parser = subparsers.add_parser("inspect-model")
    inspect_parser.add_argument("model_path", type=Path)
    arguments = parser.parse_args()
    if arguments.command == "build-index":
        report = build_index(arguments.feature_dir, arguments.output_dir, arguments.model_name)
    else:
        report = inspect_model(arguments.model_path)
    print(json.dumps(report, sort_keys=True))
    return 0


def build_index(feature_dir: Path, output_dir: Path, model_name: str) -> dict[str, object]:
    import faiss
    import numpy as np

    paths = tuple(sorted(feature_dir.expanduser().resolve().glob("*.npy"), key=lambda path: path.name.casefold()))
    if not paths:
        raise RuntimeError("No HuBERT feature arrays were found.")
    arrays = []
    for path in paths:
        array = np.load(path, allow_pickle=False)
        if array.ndim != 2 or array.shape[1] != FEATURE_WIDTH or array.size == 0:
            raise RuntimeError(f"Invalid HuBERT feature shape: {path}")
        if not np.isfinite(array).all():
            raise RuntimeError(f"HuBERT features contain non-finite values: {path}")
        arrays.append(np.asarray(array, dtype=np.float32))
    features = np.concatenate(arrays, axis=0)
    source_vector_count = int(features.shape[0])
    permutation = np.random.default_rng(RANDOM_SEED).permutation(features.shape[0])
    features = np.ascontiguousarray(features[permutation], dtype=np.float32)
    print("JJZERO_INDEX_PROGRESS=20", flush=True)

    if features.shape[0] > 200000:
        from sklearn.cluster import MiniBatchKMeans

        features = MiniBatchKMeans(
            n_clusters=10000,
            batch_size=256,
            compute_labels=False,
            init="random",
            n_init=1,
            random_state=RANDOM_SEED,
        ).fit(features).cluster_centers_.astype(np.float32, copy=False)
    output = output_dir.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    total_features = output / "total_fea.npy"
    np.save(total_features, features, allow_pickle=False)
    n_ivf = max(1, min(int(16 * math.sqrt(features.shape[0])), max(1, features.shape[0] // 39)))
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", model_name).strip("._-") or "model"
    trained_name = f"trained_IVF{n_ivf}_Flat_nprobe_1_{safe_name}_v2.index"
    added_name = f"added_IVF{n_ivf}_Flat_nprobe_1_{safe_name}_v2.index"
    index = faiss.index_factory(FEATURE_WIDTH, f"IVF{n_ivf},Flat")
    index_ivf = faiss.extract_index_ivf(index)
    index_ivf.nprobe = 1
    index.train(features)
    faiss.write_index(index, str(output / trained_name))
    print("JJZERO_INDEX_PROGRESS=60", flush=True)
    for start in range(0, features.shape[0], 8192):
        index.add(features[start : start + 8192])
    faiss.write_index(index, str(output / added_name))
    print("JJZERO_INDEX_PROGRESS=100", flush=True)
    return {
        "version": 1,
        "feature_count": len(paths),
        "source_vector_count": source_vector_count,
        "vector_count": int(features.shape[0]),
        "dimension": FEATURE_WIDTH,
        "n_ivf": n_ivf,
        "trained_index": trained_name,
        "added_index": added_name,
        "total_features": total_features.name,
    }


def inspect_model(model_path: Path) -> dict[str, object]:
    import torch

    path = model_path.expanduser().resolve()
    checkpoint = torch.load(path, map_location="cpu")
    if not isinstance(checkpoint, dict):
        raise RuntimeError("RVC inference model is not a mapping.")
    weights = checkpoint.get("weight")
    config = checkpoint.get("config")
    if not isinstance(weights, dict) or not weights:
        raise RuntimeError("RVC inference model has no weights.")
    if not isinstance(config, list) or len(config) < 18 or config[-1] != 40000:
        raise RuntimeError("RVC inference model does not use the 40k profile.")
    if checkpoint.get("version") != "v2" or checkpoint.get("sr") != "40k":
        raise RuntimeError("RVC inference model is not v2/40k.")
    if int(checkpoint.get("f0", 0)) != 1:
        raise RuntimeError("RVC inference model does not contain F0 conditioning.")
    return {
        "version": "v2",
        "sample_rate": 40000,
        "f0": True,
        "epoch_info": str(checkpoint.get("info", "")),
        "weight_count": len(weights),
    }


if __name__ == "__main__":
    raise SystemExit(main())
