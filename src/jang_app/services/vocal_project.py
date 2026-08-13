from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from jang_app.services.rvc_inference_settings import RvcInferenceSettings


VOCAL_PROJECT_SCHEMA_VERSION = 2
UNASSIGNED_SPEAKER_ID = "speaker-unassigned"
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")


class VocalProjectValidationError(ValueError):
    pass


@dataclass(frozen=True)
class VocalSpeaker:
    speaker_id: str
    name: str
    color: str


@dataclass(frozen=True)
class VocalSegment:
    segment_id: str
    start_ms: int
    end_ms: int
    speaker_id: str
    muted: bool = False


@dataclass(frozen=True)
class VocalTake:
    take_id: str
    label: str
    output_path: Path
    created_at: str
    conversion: VocalConversionSettings | None = None


@dataclass(frozen=True)
class VocalConversionSettings:
    voice_model: str
    index_file: str
    pitch: int
    requested_device: str
    effective_device: str
    f0_method: str
    inference: RvcInferenceSettings = field(default_factory=RvcInferenceSettings)


@dataclass(frozen=True)
class VocalProject:
    schema_version: int
    project_id: str
    created_at: str
    updated_at: str
    duration_ms: int
    vocals_path: Path
    instrumental_path: Path
    speakers: tuple[VocalSpeaker, ...]
    segments: tuple[VocalSegment, ...]
    takes: tuple[VocalTake, ...]
    active_take_id: str = ""


def validate_vocal_project(project: VocalProject) -> None:
    if project.schema_version != VOCAL_PROJECT_SCHEMA_VERSION:
        raise VocalProjectValidationError(
            f"Unsupported vocal project schema: {project.schema_version}"
        )
    _validate_id(project.project_id, "project ID")
    _validate_timestamp(project.created_at, "created timestamp")
    _validate_timestamp(project.updated_at, "updated timestamp")
    if project.duration_ms <= 0:
        raise VocalProjectValidationError("Vocal project duration must be positive")

    speaker_ids: set[str] = set()
    speaker_names: set[str] = set()
    for speaker in project.speakers:
        _validate_id(speaker.speaker_id, "speaker ID")
        name = speaker.name.strip()
        if not name:
            raise VocalProjectValidationError("Speaker name is required")
        if speaker.speaker_id in speaker_ids:
            raise VocalProjectValidationError(f"Duplicate speaker ID: {speaker.speaker_id}")
        if name.casefold() in speaker_names:
            raise VocalProjectValidationError(f"Duplicate speaker name: {name}")
        if not _COLOR_PATTERN.fullmatch(speaker.color):
            raise VocalProjectValidationError(f"Invalid speaker color: {speaker.color}")
        speaker_ids.add(speaker.speaker_id)
        speaker_names.add(name.casefold())
    if not speaker_ids:
        raise VocalProjectValidationError("At least one speaker is required")

    segment_ids: set[str] = set()
    previous_end = 0
    for segment in project.segments:
        _validate_id(segment.segment_id, "segment ID")
        if segment.segment_id in segment_ids:
            raise VocalProjectValidationError(f"Duplicate segment ID: {segment.segment_id}")
        if segment.speaker_id not in speaker_ids:
            raise VocalProjectValidationError(
                f"Unknown speaker for segment {segment.segment_id}: {segment.speaker_id}"
            )
        if segment.start_ms < 0 or segment.end_ms <= segment.start_ms:
            raise VocalProjectValidationError(f"Invalid segment range: {segment.segment_id}")
        if segment.end_ms > project.duration_ms:
            raise VocalProjectValidationError(
                f"Segment exceeds project duration: {segment.segment_id}"
            )
        if segment.start_ms < previous_end:
            raise VocalProjectValidationError(
                f"Segments overlap or are out of order: {segment.segment_id}"
            )
        segment_ids.add(segment.segment_id)
        previous_end = segment.end_ms
    if not segment_ids:
        raise VocalProjectValidationError("At least one vocal segment is required")

    take_ids: set[str] = set()
    take_paths: set[Path] = set()
    for take in project.takes:
        _validate_id(take.take_id, "take ID")
        if take.take_id in take_ids:
            raise VocalProjectValidationError(f"Duplicate take ID: {take.take_id}")
        if not take.label.strip():
            raise VocalProjectValidationError(f"Take label is required: {take.take_id}")
        _validate_timestamp(take.created_at, "take timestamp")
        if take.conversion is not None:
            _validate_conversion(take.take_id, take.conversion)
        resolved_path = take.output_path.expanduser().resolve()
        if resolved_path in take_paths:
            raise VocalProjectValidationError(f"Duplicate take path: {resolved_path}")
        take_ids.add(take.take_id)
        take_paths.add(resolved_path)
    if project.active_take_id and project.active_take_id not in take_ids:
        raise VocalProjectValidationError(f"Active take does not exist: {project.active_take_id}")


def _validate_id(value: str, label: str) -> None:
    if not _ID_PATTERN.fullmatch(value):
        raise VocalProjectValidationError(f"Invalid {label}: {value}")


def _validate_timestamp(value: str, label: str) -> None:
    try:
        datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise VocalProjectValidationError(f"Invalid {label}: {value}") from exc


def _validate_conversion(take_id: str, conversion: VocalConversionSettings) -> None:
    if not conversion.voice_model.strip():
        raise VocalProjectValidationError(f"Conversion model is required: {take_id}")
    if isinstance(conversion.pitch, bool) or not isinstance(conversion.pitch, int):
        raise VocalProjectValidationError(f"Conversion pitch must be an integer: {take_id}")
    for label, value in (
        ("requested device", conversion.requested_device),
        ("effective device", conversion.effective_device),
        ("F0 method", conversion.f0_method),
    ):
        if not value.strip():
            raise VocalProjectValidationError(f"Conversion {label} is required: {take_id}")
