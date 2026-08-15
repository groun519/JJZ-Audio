from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from jang_app.services.audio_metadata import read_audio_metadata
from jang_app.services.managed_files import write_json_atomic
from jang_app.services.output_catalog import converted_vocal_paths
from jang_app.services.rvc_inference_settings import rvc_inference_settings_from_data
from jang_app.services.vocal_project import (
    UNASSIGNED_SPEAKER_ID,
    VOCAL_PROJECT_SCHEMA_VERSION,
    VocalConversionSettings,
    VocalProject,
    VocalProjectValidationError,
    VocalSegment,
    VocalSpeaker,
    VocalTake,
    validate_vocal_project,
)


VOCAL_PROJECT_MANIFEST = "vocal_project.json"
_VOCALS_FILE = "vocals.wav"
_INSTRUMENTAL_FILE = "no_vocals.wav"


class VocalProjectStore:
    def load(self, job_dir: Path) -> VocalProject | None:
        project, _migrated = self._load(job_dir)
        return project

    def _load(self, job_dir: Path) -> tuple[VocalProject | None, bool]:
        root = job_dir.expanduser().resolve()
        manifest_path = root / VOCAL_PROJECT_MANIFEST
        revision = _manifest_revision(manifest_path)
        if revision is None:
            return None, False
        try:
            data = _read_manifest(manifest_path, revision)
        except (OSError, json.JSONDecodeError) as exc:
            raise VocalProjectValidationError(
                f"Could not read vocal project: {manifest_path}"
            ) from exc
        project_data = _mapping(data, "vocal project")
        source_schema = _integer(project_data.get("schema_version"), "schema version")
        project = _project_from_data(root, project_data)
        self._validate_paths(root, project)
        validate_vocal_project(project)
        return project, source_schema != VOCAL_PROJECT_SCHEMA_VERSION

    def available_takes(self, job_dir: Path) -> tuple[VocalTake, ...]:
        """Return every usable RVC take, including outputs from older app versions."""
        root = job_dir.expanduser().resolve()
        discovered = {
            take.output_path: take
            for take in _imported_takes(root, active_converted_path=None)
        }
        try:
            project = self.load(root)
        except (OSError, VocalProjectValidationError):
            project = None
        if project is not None:
            discovered.update(
                (take.output_path.expanduser().resolve(), take)
                for take in project.takes
                if take.output_path.is_file()
            )
        return tuple(
            sorted(
                discovered.values(),
                key=lambda take: _file_mtime(take.output_path),
                reverse=True,
            )
        )

    def open_or_create(
        self,
        job_dir: Path,
        *,
        active_converted_path: Path | None = None,
    ) -> VocalProject:
        root = job_dir.expanduser().resolve()
        project, migrated = self._load(root)
        if project is None:
            return self.save(root, self._new_project(root, active_converted_path))

        synchronized = self._synchronize_takes(root, project, active_converted_path)
        return self.save(root, synchronized) if migrated or synchronized != project else project

    def save(self, job_dir: Path, project: VocalProject) -> VocalProject:
        root = job_dir.expanduser().resolve()
        project = replace(project, schema_version=VOCAL_PROJECT_SCHEMA_VERSION)
        self._validate_paths(root, project)
        validate_vocal_project(project)
        updated = replace(project, updated_at=_now())
        write_json_atomic(root / VOCAL_PROJECT_MANIFEST, _project_to_data(root, updated))
        return updated

    def register_take(
        self,
        job_dir: Path,
        output_path: Path,
        *,
        conversion: VocalConversionSettings,
        label: str = "",
    ) -> VocalProject:
        root = job_dir.expanduser().resolve()
        output = _require_managed_path(root, output_path, "take output")
        if not output.is_file():
            raise VocalProjectValidationError(f"Missing take output: {output}")
        project = self.open_or_create(root, active_converted_path=output)
        existing = _take_for_path(project.takes, output)
        take = VocalTake(
            take_id=existing.take_id if existing is not None else _take_id(root, output),
            label=label.strip() or _default_take_label(conversion),
            output_path=output,
            created_at=existing.created_at if existing is not None else _file_timestamp(output),
            conversion=conversion,
        )
        takes = (take, *(item for item in project.takes if item.take_id != take.take_id))
        return self.save(root, replace(project, takes=takes, active_take_id=take.take_id))

    def set_active_take(self, job_dir: Path, output_path: Path | None) -> VocalProject:
        root = job_dir.expanduser().resolve()
        project = self.open_or_create(root, active_converted_path=output_path)
        active_take_id = _active_take_id(project.takes, output_path)
        if active_take_id == project.active_take_id:
            return project
        return self.save(root, replace(project, active_take_id=active_take_id))

    def rename_take(self, job_dir: Path, output_path: Path, label: str) -> VocalProject:
        root = job_dir.expanduser().resolve()
        project = self.open_or_create(root, active_converted_path=output_path)
        target = _take_for_path(project.takes, output_path)
        if target is None:
            raise VocalProjectValidationError(f"Unknown vocal take: {output_path}")
        renamed = replace(target, label=label.strip())
        return self.save(
            root,
            replace(
                project,
                takes=tuple(renamed if take.take_id == target.take_id else take for take in project.takes),
            ),
        )

    def remove_take(self, job_dir: Path, output_path: Path) -> VocalProject:
        root = job_dir.expanduser().resolve()
        project = self.open_or_create(root, active_converted_path=output_path)
        target = _take_for_path(project.takes, output_path)
        if target is None:
            raise VocalProjectValidationError(f"Unknown vocal take: {output_path}")
        remaining = tuple(take for take in project.takes if take.take_id != target.take_id)
        active_take_id = remaining[0].take_id if remaining else ""
        updated = self.save(
            root,
            replace(project, takes=remaining, active_take_id=active_take_id),
        )
        try:
            target.output_path.unlink()
        except OSError:
            self.save(root, project)
            raise
        return updated

    def _new_project(
        self,
        root: Path,
        active_converted_path: Path | None,
    ) -> VocalProject:
        vocals_path = root / _VOCALS_FILE
        instrumental_path = root / _INSTRUMENTAL_FILE
        if not vocals_path.is_file() or not instrumental_path.is_file():
            raise VocalProjectValidationError(
                f"Vocal project requires {_VOCALS_FILE} and {_INSTRUMENTAL_FILE}: {root}"
            )
        duration_ms = read_audio_metadata(vocals_path).duration_ms
        if duration_ms <= 0:
            raise VocalProjectValidationError(f"Could not determine vocal duration: {vocals_path}")

        created_at = _now()
        takes = _imported_takes(root, active_converted_path)
        active_take_id = _active_take_id(takes, active_converted_path)
        return VocalProject(
            schema_version=VOCAL_PROJECT_SCHEMA_VERSION,
            project_id=f"vocal-{uuid4().hex[:16]}",
            created_at=created_at,
            updated_at=created_at,
            duration_ms=duration_ms,
            vocals_path=vocals_path,
            instrumental_path=instrumental_path,
            speakers=(VocalSpeaker(UNASSIGNED_SPEAKER_ID, "Unassigned", "#898780"),),
            segments=(VocalSegment("segment-001", 0, duration_ms, UNASSIGNED_SPEAKER_ID),),
            takes=takes,
            active_take_id=active_take_id,
        )

    def _synchronize_takes(
        self,
        root: Path,
        project: VocalProject,
        active_converted_path: Path | None,
    ) -> VocalProject:
        existing_takes = tuple(take for take in project.takes if take.output_path.is_file())
        known_paths = {take.output_path.expanduser().resolve() for take in existing_takes}
        imported = tuple(
            take
            for take in _imported_takes(root, active_converted_path)
            if take.output_path.expanduser().resolve() not in known_paths
        )
        takes = (*imported, *existing_takes)
        active_take_id = (
            _active_take_id(takes, active_converted_path)
            if active_converted_path is not None
            else (
                project.active_take_id
                if any(take.take_id == project.active_take_id for take in takes)
                else (takes[0].take_id if takes else "")
            )
        )
        return replace(project, takes=takes, active_take_id=active_take_id)

    def _validate_paths(self, root: Path, project: VocalProject) -> None:
        for label, path in (
            ("vocals", project.vocals_path),
            ("instrumental", project.instrumental_path),
        ):
            resolved = _require_managed_path(root, path, label)
            if not resolved.is_file():
                raise VocalProjectValidationError(f"Missing {label} asset: {resolved}")
        for take in project.takes:
            _require_managed_path(root, take.output_path, f"take {take.take_id}")


def _project_to_data(root: Path, project: VocalProject) -> dict[str, object]:
    return {
        "schema_version": project.schema_version,
        "project_id": project.project_id,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "duration_ms": project.duration_ms,
        "assets": {
            "vocals": _relative_path(root, project.vocals_path, "vocals"),
            "instrumental": _relative_path(root, project.instrumental_path, "instrumental"),
        },
        "speakers": [
            {
                "speaker_id": speaker.speaker_id,
                "name": speaker.name,
                "color": speaker.color,
            }
            for speaker in project.speakers
        ],
        "segments": [
            {
                "segment_id": segment.segment_id,
                "start_ms": segment.start_ms,
                "end_ms": segment.end_ms,
                "speaker_id": segment.speaker_id,
                "muted": segment.muted,
            }
            for segment in project.segments
        ],
        "takes": [
            {
                "take_id": take.take_id,
                "label": take.label,
                "output": _relative_path(root, take.output_path, f"take {take.take_id}"),
                "created_at": take.created_at,
                **(
                    {"conversion": _conversion_to_data(take.conversion)}
                    if take.conversion is not None
                    else {}
                ),
            }
            for take in project.takes
        ],
        "active_take_id": project.active_take_id,
    }


def _project_from_data(root: Path, data: Mapping[str, object]) -> VocalProject:
    source_schema = _integer(data.get("schema_version"), "schema version")
    if source_schema not in {1, VOCAL_PROJECT_SCHEMA_VERSION}:
        raise VocalProjectValidationError(f"Unsupported vocal project schema: {source_schema}")
    assets = _mapping(data.get("assets"), "assets")
    speakers = tuple(
        VocalSpeaker(
            _text(item.get("speaker_id"), "speaker ID"),
            _text(item.get("name"), "speaker name"),
            _text(item.get("color"), "speaker color"),
        )
        for item in _mapping_list(data.get("speakers"), "speakers")
    )
    segments = tuple(
        VocalSegment(
            _text(item.get("segment_id"), "segment ID"),
            _integer(item.get("start_ms"), "segment start"),
            _integer(item.get("end_ms"), "segment end"),
            _text(item.get("speaker_id"), "segment speaker"),
            _boolean(item.get("muted", False), "segment muted"),
        )
        for item in _mapping_list(data.get("segments"), "segments")
    )
    takes = tuple(
        VocalTake(
            _text(item.get("take_id"), "take ID"),
            _text(item.get("label"), "take label"),
            _managed_path(root, _text(item.get("output"), "take output"), "take output"),
            _text(item.get("created_at"), "take timestamp"),
            _conversion_from_data(item.get("conversion")),
        )
        for item in _mapping_list(data.get("takes"), "takes")
    )
    return VocalProject(
        schema_version=VOCAL_PROJECT_SCHEMA_VERSION,
        project_id=_text(data.get("project_id"), "project ID"),
        created_at=_text(data.get("created_at"), "created timestamp"),
        updated_at=_text(data.get("updated_at"), "updated timestamp"),
        duration_ms=_integer(data.get("duration_ms"), "duration"),
        vocals_path=_managed_path(
            root,
            _text(assets.get("vocals"), "vocals path"),
            "vocals",
        ),
        instrumental_path=_managed_path(
            root,
            _text(assets.get("instrumental"), "instrumental path"),
            "instrumental",
        ),
        speakers=speakers,
        segments=segments,
        takes=takes,
        active_take_id=_optional_text(data.get("active_take_id"), "active take ID"),
    )


def _imported_takes(root: Path, active_converted_path: Path | None) -> tuple[VocalTake, ...]:
    paths = set(converted_vocal_paths(root))
    if active_converted_path is not None:
        active = active_converted_path.expanduser().resolve()
        if active.is_file() and active.parent == root:
            paths.add(active)
    ordered = sorted(paths, key=_file_mtime, reverse=True)
    return tuple(_imported_take(root, path) for path in ordered)


def _imported_take(root: Path, path: Path) -> VocalTake:
    return VocalTake(_take_id(root, path), path.stem, path, _file_timestamp(path))


def _active_take_id(takes: tuple[VocalTake, ...], path: Path | None) -> str:
    if path is None:
        return ""
    resolved = path.expanduser().resolve()
    return next(
        (take.take_id for take in takes if take.output_path.expanduser().resolve() == resolved),
        "",
    )


def _take_for_path(takes: tuple[VocalTake, ...], path: Path) -> VocalTake | None:
    resolved = path.expanduser().resolve()
    return next(
        (take for take in takes if take.output_path.expanduser().resolve() == resolved),
        None,
    )


def _take_id(root: Path, path: Path) -> str:
    relative = path.expanduser().resolve().relative_to(root).as_posix()
    digest = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:12]
    return f"take-{digest}"


def _file_timestamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()


def _file_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _manifest_revision(path: Path) -> tuple[int, int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size


@lru_cache(maxsize=128)
def _read_manifest(
    path: Path,
    _revision: tuple[int, int, int],
) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _default_take_label(conversion: VocalConversionSettings) -> str:
    model = Path(conversion.voice_model).stem or "RVC"
    return f"{model} / Pitch {conversion.pitch:+d}"


def _conversion_to_data(conversion: VocalConversionSettings) -> dict[str, object]:
    return {
        "voice_model": conversion.voice_model,
        "index_file": conversion.index_file,
        "pitch": conversion.pitch,
        "requested_device": conversion.requested_device,
        "effective_device": conversion.effective_device,
        "f0_method": conversion.f0_method,
        "inference": {
            "index_rate": conversion.inference.index_rate,
            "filter_radius": conversion.inference.filter_radius,
            "rms_mix_rate": conversion.inference.rms_mix_rate,
            "protect": conversion.inference.protect,
        },
    }


def _conversion_from_data(value: object) -> VocalConversionSettings | None:
    if value is None:
        return None
    data = _mapping(value, "take conversion")
    return VocalConversionSettings(
        voice_model=_text(data.get("voice_model"), "conversion model"),
        index_file=_optional_text(data.get("index_file"), "conversion index"),
        pitch=_integer(data.get("pitch"), "conversion pitch"),
        requested_device=_text(data.get("requested_device"), "conversion requested device"),
        effective_device=_text(data.get("effective_device"), "conversion effective device"),
        f0_method=_text(data.get("f0_method"), "conversion F0 method"),
        inference=rvc_inference_settings_from_data(data.get("inference")),
    )


def _relative_path(root: Path, path: Path, label: str) -> str:
    return _require_managed_path(root, path, label).relative_to(root).as_posix()


def _managed_path(root: Path, value: str, label: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        raise VocalProjectValidationError(f"{label} must use a project-relative path")
    return _require_managed_path(root, root / candidate, label)


def _require_managed_path(root: Path, path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_relative_to(root):
        raise VocalProjectValidationError(f"{label} escapes the vocal project folder: {resolved}")
    return resolved


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise VocalProjectValidationError(f"{label} must be an object")
    return value


def _mapping_list(value: object, label: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list):
        raise VocalProjectValidationError(f"{label} must be a list")
    return tuple(_mapping(item, label) for item in value)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VocalProjectValidationError(f"{label} must be a non-empty string")
    return value.strip()


def _optional_text(value: object, label: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise VocalProjectValidationError(f"{label} must be a string")
    return value.strip()


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise VocalProjectValidationError(f"{label} must be an integer")
    return value


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise VocalProjectValidationError(f"{label} must be a boolean")
    return value


def _now() -> str:
    return datetime.now(UTC).isoformat()
