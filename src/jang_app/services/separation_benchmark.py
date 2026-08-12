from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping

from jang_app.services.audio_clip import render_audio_clip
from jang_app.services.managed_files import file_sha256, write_json_atomic
from jang_app.services.separation_recipe import separation_recipe
from jang_app.services.settings import RvcSettings


BENCHMARK_DEFINITION_SCHEMA = 1
BENCHMARK_RUN_SCHEMA = 1


class SeparationBenchmarkError(RuntimeError):
    """Raised when a separation benchmark cannot be prepared safely."""


@dataclass(frozen=True)
class BenchmarkSource:
    kind: str
    sha256: str
    song_id: str = ""
    source_key: str = ""


@dataclass(frozen=True)
class BenchmarkClip:
    clip_id: str
    title: str
    role: str
    source: BenchmarkSource
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class BenchmarkRvc:
    model_name: str
    model_sha256: str
    index_name: str
    index_sha256: str
    pitch: int
    f0_method: str
    device: str


@dataclass(frozen=True)
class BenchmarkCandidate:
    candidate_id: str
    label: str
    recipe_id: str


@dataclass(frozen=True)
class SeparationBenchmarkDefinition:
    benchmark_id: str
    title: str
    clips: tuple[BenchmarkClip, ...]
    rvc: BenchmarkRvc
    candidates: tuple[BenchmarkCandidate, ...]
    review_dimensions: tuple[str, ...]


def load_benchmark_definition(path: Path) -> SeparationBenchmarkDefinition:
    source = path.expanduser().resolve()
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SeparationBenchmarkError(f"Could not read benchmark definition: {source}") from exc
    if not isinstance(data, Mapping) or data.get("schema") != BENCHMARK_DEFINITION_SCHEMA:
        raise SeparationBenchmarkError("Unsupported benchmark definition schema.")

    clips_data = _mapping_list(data.get("clips"), "clips")
    candidate_data = _mapping_list(data.get("candidates"), "candidates")
    clips = tuple(_clip_from_data(value) for value in clips_data)
    candidates = tuple(_candidate_from_data(value) for value in candidate_data)
    rvc_data = _mapping(data.get("rvc"), "rvc")
    definition = SeparationBenchmarkDefinition(
        benchmark_id=_required_text(data.get("benchmark_id"), "benchmark_id"),
        title=_required_text(data.get("title"), "title"),
        clips=clips,
        rvc=BenchmarkRvc(
            model_name=_required_text(rvc_data.get("model_name"), "rvc.model_name"),
            model_sha256=_sha256(rvc_data.get("model_sha256"), "rvc.model_sha256"),
            index_name=_required_text(rvc_data.get("index_name"), "rvc.index_name"),
            index_sha256=_sha256(rvc_data.get("index_sha256"), "rvc.index_sha256"),
            pitch=_integer(rvc_data.get("pitch"), "rvc.pitch"),
            f0_method=_required_text(rvc_data.get("f0_method"), "rvc.f0_method"),
            device=_required_text(rvc_data.get("device"), "rvc.device"),
        ),
        candidates=candidates,
        review_dimensions=tuple(
            _required_text(value, "review_dimensions")
            for value in _sequence(data.get("review_dimensions"), "review_dimensions")
        ),
    )
    _validate_definition(definition)
    return definition


def prepare_benchmark(
    definition_path: Path,
    workspace_root: Path,
    output_root: Path,
    rvc_settings: RvcSettings,
    *,
    source_overrides: Mapping[str, Path] | None = None,
) -> Path:
    definition_file = definition_path.expanduser().resolve()
    definition = load_benchmark_definition(definition_file)
    workspace = workspace_root.expanduser().resolve()
    root = output_root.expanduser().resolve() / definition.benchmark_id
    clip_root = root / "clips"
    overrides = {
        key: value.expanduser().resolve()
        for key, value in (source_overrides or {}).items()
    }

    prepared_clips: list[dict[str, object]] = []
    for clip in definition.clips:
        source = _resolve_source(clip.source, workspace, overrides)
        _require_hash(source, clip.source.sha256, f"source for {clip.clip_id}")
        output = clip_root / f"{clip.clip_id}.wav"
        render_audio_clip(source, output, clip.start_ms, clip.end_ms)
        prepared_clips.append(
            {
                "clip_id": clip.clip_id,
                "title": clip.title,
                "role": clip.role,
                "source_path": str(source),
                "source_sha256": clip.source.sha256,
                "start_ms": clip.start_ms,
                "end_ms": clip.end_ms,
                "path": str(output.resolve()),
                "sha256": file_sha256(output),
                "size": output.stat().st_size,
            }
        )

    resolved_rvc = _resolve_rvc(definition.rvc, rvc_settings)
    manifest = root / "benchmark.json"
    write_json_atomic(
        manifest,
        {
            "schema": BENCHMARK_RUN_SCHEMA,
            "benchmark_id": definition.benchmark_id,
            "title": definition.title,
            "prepared_at": datetime.now(UTC).isoformat(),
            "definition_path": str(definition_file),
            "definition_sha256": file_sha256(definition_file),
            "root": str(root),
            "clips": prepared_clips,
            "rvc": resolved_rvc,
            "candidates": [asdict(candidate) for candidate in definition.candidates],
            "review_dimensions": list(definition.review_dimensions),
        },
    )
    return manifest


def _clip_from_data(data: Mapping[str, object]) -> BenchmarkClip:
    source_data = _mapping(data.get("source"), "clip.source")
    source = BenchmarkSource(
        kind=_required_text(source_data.get("kind"), "clip.source.kind"),
        sha256=_sha256(source_data.get("sha256"), "clip.source.sha256"),
        song_id=_optional_text(source_data.get("song_id")),
        source_key=_optional_text(source_data.get("source_key")),
    )
    return BenchmarkClip(
        clip_id=_required_text(data.get("clip_id"), "clip.clip_id"),
        title=_required_text(data.get("title"), "clip.title"),
        role=_required_text(data.get("role"), "clip.role"),
        source=source,
        start_ms=_integer(data.get("start_ms"), "clip.start_ms"),
        end_ms=_integer(data.get("end_ms"), "clip.end_ms"),
    )


def _candidate_from_data(data: Mapping[str, object]) -> BenchmarkCandidate:
    return BenchmarkCandidate(
        candidate_id=_required_text(data.get("candidate_id"), "candidate.candidate_id"),
        label=_required_text(data.get("label"), "candidate.label"),
        recipe_id=_required_text(data.get("recipe_id"), "candidate.recipe_id"),
    )


def _validate_definition(definition: SeparationBenchmarkDefinition) -> None:
    if not definition.clips:
        raise SeparationBenchmarkError("Benchmark requires at least one clip.")
    if not definition.candidates:
        raise SeparationBenchmarkError("Benchmark requires at least one candidate.")
    _require_unique((clip.clip_id for clip in definition.clips), "clip IDs")
    _require_unique((candidate.candidate_id for candidate in definition.candidates), "candidate IDs")
    for clip in definition.clips:
        if clip.start_ms < 0 or clip.end_ms <= clip.start_ms:
            raise SeparationBenchmarkError(f"Invalid range for clip {clip.clip_id}.")
        if clip.source.kind == "library" and not clip.source.song_id:
            raise SeparationBenchmarkError(f"Library clip {clip.clip_id} requires song_id.")
        if clip.source.kind == "override" and not clip.source.source_key:
            raise SeparationBenchmarkError(f"Override clip {clip.clip_id} requires source_key.")
        if clip.source.kind not in {"library", "override"}:
            raise SeparationBenchmarkError(
                f"Unsupported source kind for {clip.clip_id}: {clip.source.kind}"
            )
    for candidate in definition.candidates:
        recipe = separation_recipe(candidate.recipe_id)
        if recipe.recipe_id != candidate.recipe_id:
            raise SeparationBenchmarkError(
                f"Unknown separation recipe for {candidate.candidate_id}: {candidate.recipe_id}"
            )


def _resolve_source(
    source: BenchmarkSource,
    workspace_root: Path,
    overrides: Mapping[str, Path],
) -> Path:
    if source.kind == "override":
        path = overrides.get(source.source_key)
        if path is None:
            raise SeparationBenchmarkError(
                f"Missing source override: {source.source_key}"
            )
        if not path.is_file():
            raise SeparationBenchmarkError(f"Source override does not exist: {path}")
        return path

    songs_root = workspace_root / "library" / "songs"
    for manifest in songs_root.glob("*/song.json"):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, Mapping) or data.get("id") != source.song_id:
            continue
        if data.get("removed") is True:
            raise SeparationBenchmarkError(f"Benchmark song is removed: {source.song_id}")
        source_data = data.get("source")
        if not isinstance(source_data, Mapping):
            break
        audio = source_data.get("audio")
        if isinstance(audio, str) and audio.strip():
            path = manifest.parent / audio
            if path.is_file():
                return path.resolve()
        break
    raise SeparationBenchmarkError(f"Could not resolve library song: {source.song_id}")


def _resolve_rvc(definition: BenchmarkRvc, settings: RvcSettings) -> dict[str, object]:
    root = settings.root.expanduser().resolve()
    model = _rvc_path(root, settings.voice_model)
    index = _rvc_path(root, settings.index_file)
    if model.name != definition.model_name or index.name != definition.index_name:
        raise SeparationBenchmarkError(
            "Active RVC assets do not match the benchmark definition."
        )
    if settings.pitch != definition.pitch:
        raise SeparationBenchmarkError(
            f"Active RVC pitch is {settings.pitch}; benchmark requires {definition.pitch}."
        )
    if settings.f0_method.casefold() != definition.f0_method.casefold():
        raise SeparationBenchmarkError(
            f"Active F0 method is {settings.f0_method}; benchmark requires {definition.f0_method}."
        )
    _require_hash(model, definition.model_sha256, "RVC model")
    _require_hash(index, definition.index_sha256, "RVC index")
    return {
        "root": str(root),
        "voice_model": str(model),
        "voice_model_sha256": definition.model_sha256,
        "index_file": str(index),
        "index_sha256": definition.index_sha256,
        "pitch": definition.pitch,
        "f0_method": definition.f0_method,
        "device": definition.device,
    }


def _rvc_path(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    resolved = path if path.is_absolute() else root / path
    resolved = resolved.resolve()
    if not resolved.is_file():
        raise SeparationBenchmarkError(f"RVC asset does not exist: {resolved}")
    return resolved


def _require_hash(path: Path, expected: str, label: str) -> None:
    actual = file_sha256(path)
    if actual.casefold() != expected.casefold():
        raise SeparationBenchmarkError(
            f"SHA-256 mismatch for {label}: expected {expected}, got {actual}"
        )


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SeparationBenchmarkError(f"Benchmark {label} must be an object.")
    return value


def _mapping_list(value: object, label: str) -> tuple[Mapping[str, object], ...]:
    return tuple(_mapping(item, label) for item in _sequence(value, label))


def _sequence(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, list):
        raise SeparationBenchmarkError(f"Benchmark {label} must be a list.")
    return tuple(value)


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SeparationBenchmarkError(f"Benchmark {label} is required.")
    return value.strip()


def _optional_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise SeparationBenchmarkError(f"Benchmark {label} must be an integer.")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise SeparationBenchmarkError(f"Benchmark {label} must be an integer.") from exc


def _sha256(value: object, label: str) -> str:
    text = _required_text(value, label).casefold()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise SeparationBenchmarkError(f"Benchmark {label} must be a SHA-256 value.")
    return text


def _require_unique(values: object, label: str) -> None:
    resolved = tuple(values)  # type: ignore[arg-type]
    if len(set(resolved)) != len(resolved):
        raise SeparationBenchmarkError(f"Benchmark {label} must be unique.")
