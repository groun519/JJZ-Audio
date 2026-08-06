from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from jang_app.pipeline.rvc_convert import list_voice_models
from jang_app.services.rvc_model_workspace import RvcModelRecord


@dataclass(frozen=True)
class RvcModelChoice:
    choice_id: str
    label: str
    root: Path
    model_path: Path
    model_id: str = ""
    index_path: Path | None = None
    pitch: int = 0
    device: str = "auto"
    source: str = "library"


def collect_rvc_model_choices(
    records: Iterable[RvcModelRecord],
    legacy_root: Path,
    *,
    current_root: Path | None = None,
    current_model: str = "",
) -> tuple[RvcModelChoice, ...]:
    choices: list[RvcModelChoice] = []
    seen_paths: set[str] = set()

    for record in records:
        choice = rvc_model_choice_from_record(record)
        if choice is None:
            continue
        _append_choice(choices, seen_paths, choice)

    resolved_legacy_root = legacy_root.expanduser().resolve()
    for relative_model in list_voice_models(resolved_legacy_root):
        model_path = resolve_rvc_setting_path(resolved_legacy_root, relative_model)
        _append_choice(
            choices,
            seen_paths,
            RvcModelChoice(
                choice_id=f"legacy:{_path_key(model_path)}",
                label=model_path.stem,
                root=resolved_legacy_root,
                model_path=model_path,
                source="legacy",
            ),
        )

    current_path = resolve_optional_rvc_setting_path(
        current_root or resolved_legacy_root,
        current_model,
    )
    if current_path is not None and current_path.is_file():
        _append_choice(
            choices,
            seen_paths,
            RvcModelChoice(
                choice_id=f"current:{_path_key(current_path)}",
                label=current_path.stem,
                root=(current_root or resolved_legacy_root).expanduser().resolve(),
                model_path=current_path,
                source="current",
            ),
        )

    return tuple(choices)


def rvc_model_choice_from_record(
    record: RvcModelRecord,
) -> RvcModelChoice | None:
    if not record.can_convert or record.inference_model is None:
        return None
    return RvcModelChoice(
        choice_id=f"library:{record.model_id}",
        label=record.title,
        root=record.runtime_root.expanduser().resolve(),
        model_path=record.inference_model.expanduser().resolve(),
        model_id=record.model_id,
        index_path=(
            record.index_file.expanduser().resolve()
            if record.index_file is not None and record.index_file.is_file()
            else None
        ),
        pitch=record.default_pitch,
        device=record.default_device,
        source="library",
    )


def resolve_rvc_setting_path(root: Path, value: str) -> Path:
    path = Path(value.strip()).expanduser()
    return (path if path.is_absolute() else root.expanduser() / path).resolve()


def resolve_optional_rvc_setting_path(root: Path, value: str) -> Path | None:
    return resolve_rvc_setting_path(root, value) if value.strip() else None


def _append_choice(
    choices: list[RvcModelChoice],
    seen_paths: set[str],
    choice: RvcModelChoice,
) -> None:
    key = _path_key(choice.model_path)
    if key in seen_paths:
        return
    seen_paths.add(key)
    choices.append(choice)


def _path_key(path: Path) -> str:
    return str(path.expanduser().resolve()).casefold()
