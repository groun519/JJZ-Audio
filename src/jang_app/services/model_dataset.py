from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from jang_app.config import MODEL_WORKSPACE_DIR, SUPPORTED_AUDIO_EXTENSIONS
from jang_app.services.audio_clip import render_audio_clip
from jang_app.services.audio_denoise import render_denoised_audio
from jang_app.services.audio_metadata import read_audio_metadata
from jang_app.services.clip_edit_history import (
    ClipEditHistory,
    ClipEditState,
    REVIEW_EDITING,
    REVIEW_READY,
    REVIEW_UNREVIEWED,
    TRAINING_MODE_CLIPS,
    TRAINING_MODE_FULL,
    history_from_data,
    history_to_data,
    state_from_values,
)
from jang_app.services.file_names import safe_filename_stem
from jang_app.services.managed_files import write_json_atomic
from jang_app.services.segment_review import (
    SEGMENT_HELD,
    SEGMENT_PENDING,
    SegmentCandidate,
    build_segment_candidates,
    normalize_segment_status,
    update_candidate_status,
)


DATASET_VERSION = 6
DATASET_DIRECTORY_NAME = "datasets"
DATASET_MANIFEST_NAME = "dataset.json"
_MODEL_ID_PATTERN = re.compile(r"^[a-zA-Z0-9._-]+$")


class ModelDatasetError(RuntimeError):
    """Raised when model training material cannot be stored safely."""


@dataclass(frozen=True)
class ModelDatasetClip:
    clip_id: str
    start_ms: int
    end_ms: int
    path: Path
    created_at: str

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)


@dataclass(frozen=True)
class ModelDatasetItem:
    item_id: str
    source_name: str
    source_path: Path
    original_path: Path
    working_path: Path
    added_at: str
    duration_ms: int = 0
    selected_order: int | None = None
    clips: tuple[ModelDatasetClip, ...] = ()
    training_mode: str = TRAINING_MODE_FULL
    review_state: str = REVIEW_UNREVIEWED
    edit_history: ClipEditHistory = ClipEditHistory()
    segment_candidates: tuple[SegmentCandidate, ...] = ()
    denoised_path: Path | None = None
    denoise_strength: int = 0
    denoise_sample_start_ms: int = 0
    denoise_sample_end_ms: int = 0

    @property
    def is_selected(self) -> bool:
        return self.selected_order is not None

    @property
    def size_bytes(self) -> int:
        try:
            return self.active_audio_path.stat().st_size
        except OSError:
            return 0

    @property
    def has_denoised_audio(self) -> bool:
        return self.denoised_path is not None and self.denoised_path.is_file()

    @property
    def active_audio_path(self) -> Path:
        return self.denoised_path if self.has_denoised_audio else self.working_path

    @property
    def training_paths(self) -> tuple[Path, ...]:
        if self.training_mode == TRAINING_MODE_CLIPS:
            return tuple(clip.path for clip in self.clips)
        return (self.active_audio_path,)

    @property
    def training_duration_ms(self) -> int:
        if self.training_mode == TRAINING_MODE_CLIPS:
            return sum(clip.duration_ms for clip in self.clips)
        return self.duration_ms

    @property
    def can_undo(self) -> bool:
        return self.edit_history.can_undo

    @property
    def can_redo(self) -> bool:
        return self.edit_history.can_redo

    @property
    def pending_segment_count(self) -> int:
        return sum(candidate.status == SEGMENT_PENDING for candidate in self.segment_candidates)

    @property
    def held_segment_count(self) -> int:
        return sum(candidate.status == SEGMENT_HELD for candidate in self.segment_candidates)

    @property
    def open_segment_count(self) -> int:
        return self.pending_segment_count + self.held_segment_count


@dataclass(frozen=True)
class ModelDataset:
    model_id: str
    items: tuple[ModelDatasetItem, ...] = ()

    @property
    def source_items(self) -> tuple[ModelDatasetItem, ...]:
        return tuple(item for item in self.items if not item.is_selected)

    @property
    def training_items(self) -> tuple[ModelDatasetItem, ...]:
        selected = (item for item in self.items if item.is_selected)
        return tuple(sorted(selected, key=lambda item: item.selected_order or 0))


class ModelDatasetStore:
    def __init__(self, workspace_root: Path = MODEL_WORKSPACE_DIR) -> None:
        self.root = workspace_root.expanduser().resolve() / DATASET_DIRECTORY_NAME
        self._dataset_cache: dict[
            str,
            tuple[tuple[int, int, int] | None, ModelDataset],
        ] = {}

    def load(self, model_id: str) -> ModelDataset:
        model_dir = self._model_dir(model_id)
        manifest = model_dir / DATASET_MANIFEST_NAME
        revision = self._manifest_revision(manifest)
        cached = self._dataset_cache.get(model_id)
        if cached is not None and cached[0] == revision:
            return cached[1]
        if revision is None:
            return self._cache_dataset(ModelDataset(model_id), revision)
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ModelDatasetError(f"Dataset manifest cannot be read: {manifest}") from exc
        if (
            not isinstance(data, dict)
            or data.get("version") not in {1, 2, 3, 4, 5, DATASET_VERSION}
            or data.get("model_id") != model_id
        ):
            raise ModelDatasetError("Dataset manifest is not compatible with this model.")
        raw_items = data.get("items")
        if not isinstance(raw_items, list):
            raise ModelDatasetError("Dataset manifest has no valid item list.")
        try:
            items = tuple(self._item_from_data(item, model_dir) for item in raw_items if isinstance(item, dict))
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelDatasetError("Dataset manifest contains an invalid item.") from exc
        return self._cache_dataset(
            ModelDataset(model_id, _normalize_selected_order(items)),
            revision,
        )

    def add_sources(
        self,
        model_id: str,
        paths: Iterable[Path],
        progress: Callable[[int], None] | None = None,
    ) -> ModelDataset:
        dataset = self.load(model_id)
        candidates = _validated_audio_paths(paths)
        existing_sources = {_path_key(item.source_path) for item in dataset.items}
        candidates = tuple(path for path in candidates if _path_key(path) not in existing_sources)
        if not candidates:
            if progress is not None:
                progress(100)
            return dataset

        model_dir = self._model_dir(model_id)
        originals_dir = model_dir / "originals"
        working_dir = model_dir / "working"
        total_bytes = sum(path.stat().st_size for path in candidates) * 2
        copied_bytes = 0
        created_paths: list[Path] = []
        added_items: list[ModelDatasetItem] = []

        def report(chunk_size: int) -> None:
            nonlocal copied_bytes
            copied_bytes += chunk_size
            if progress is not None:
                progress(_percentage(copied_bytes, total_bytes))

        try:
            for source in candidates:
                item_id = uuid.uuid4().hex[:16]
                safe_stem = safe_filename_stem(source.stem, "audio", 56)
                file_name = f"{item_id}_{safe_stem}{source.suffix.casefold()}"
                original_path = originals_dir / file_name
                working_path = working_dir / file_name
                _copy_file_atomic(source, original_path, report)
                created_paths.append(original_path)
                _copy_file_atomic(source, working_path, report)
                created_paths.append(working_path)
                added_items.append(
                    ModelDatasetItem(
                        item_id=item_id,
                        source_name=source.name,
                        source_path=source,
                        original_path=original_path,
                        working_path=working_path,
                        added_at=datetime.now(UTC).isoformat(),
                        duration_ms=_safe_duration_ms(source),
                    )
                )
            updated = ModelDataset(model_id, dataset.items + tuple(added_items))
            self._save(updated)
        except Exception:
            for path in created_paths:
                _unlink_quietly(path)
            raise
        if progress is not None:
            progress(100)
        return updated

    def select_items(self, model_id: str, item_ids: Iterable[str]) -> ModelDataset:
        dataset = self.load(model_id)
        ordered_ids = _unique_values(item_ids)
        next_order = len(dataset.training_items)
        items_by_id = {item.item_id: item for item in dataset.items}
        selected_order: dict[str, int] = {}
        for item_id in ordered_ids:
            item = items_by_id.get(item_id)
            if item is not None and not item.is_selected:
                selected_order[item_id] = next_order
                next_order += 1
        if not selected_order:
            return dataset
        updated = ModelDataset(
            model_id,
            tuple(
                replace(item, selected_order=selected_order[item.item_id])
                if item.item_id in selected_order
                else item
                for item in dataset.items
            ),
        )
        self._save(updated)
        return updated

    def deselect_items(self, model_id: str, item_ids: Iterable[str]) -> ModelDataset:
        dataset = self.load(model_id)
        removed_ids = set(item_ids)
        items = tuple(
            replace(item, selected_order=None) if item.item_id in removed_ids else item
            for item in dataset.items
        )
        updated = ModelDataset(model_id, _normalize_selected_order(items))
        self._save(updated)
        return updated

    def move_selected_item(self, model_id: str, item_id: str, offset: int) -> ModelDataset:
        dataset = self.load(model_id)
        selected = list(dataset.training_items)
        current_index = next((index for index, item in enumerate(selected) if item.item_id == item_id), None)
        if current_index is None:
            return dataset
        target_index = max(0, min(len(selected) - 1, current_index + offset))
        if target_index == current_index:
            return dataset
        selected[current_index], selected[target_index] = selected[target_index], selected[current_index]
        order_by_id = {item.item_id: index for index, item in enumerate(selected)}
        updated = ModelDataset(
            model_id,
            tuple(
                replace(item, selected_order=order_by_id[item.item_id]) if item.is_selected else item
                for item in dataset.items
            ),
        )
        self._save(updated)
        return updated

    def add_clip(
        self,
        model_id: str,
        item_id: str,
        start_ms: int,
        end_ms: int,
        progress: Callable[[int], None] | None = None,
    ) -> ModelDataset:
        return self.add_clips(model_id, item_id, ((start_ms, end_ms),), progress)

    def add_clips(
        self,
        model_id: str,
        item_id: str,
        ranges: Iterable[tuple[int, int]],
        progress: Callable[[int], None] | None = None,
    ) -> ModelDataset:
        dataset = self.load(model_id)
        item = _require_item(dataset, item_id)
        duration_ms = item.duration_ms or _safe_duration_ms(item.working_path)
        additions = _normalize_clip_ranges(ranges, duration_ms)
        if not additions:
            if progress is not None:
                progress(100)
            return dataset
        existing_ranges = _clip_ranges(item)
        new_ranges = tuple(clip_range for clip_range in additions if clip_range not in existing_ranges)
        target_ranges = existing_ranges + new_ranges
        return self._commit_user_edit(dataset, item, target_ranges, progress)

    def update_clip(
        self,
        model_id: str,
        item_id: str,
        clip_id: str,
        start_ms: int,
        end_ms: int,
        progress: Callable[[int], None] | None = None,
    ) -> ModelDataset:
        dataset = self.load(model_id)
        item = _require_item(dataset, item_id)
        clip_index = _clip_index(item, clip_id)
        if clip_index is None:
            return dataset
        ranges = list(_clip_ranges(item))
        ranges[clip_index] = (start_ms, end_ms)
        return self._commit_user_edit(dataset, item, tuple(ranges), progress)

    def split_clip(
        self,
        model_id: str,
        item_id: str,
        clip_id: str,
        position_ms: int,
        progress: Callable[[int], None] | None = None,
    ) -> ModelDataset:
        dataset = self.load(model_id)
        item = _require_item(dataset, item_id)
        clip_index = _clip_index(item, clip_id)
        if clip_index is None:
            return dataset
        clip = item.clips[clip_index]
        position = int(position_ms)
        if position - clip.start_ms < 100 or clip.end_ms - position < 100:
            raise ModelDatasetError("Split position must leave at least 100 ms on each side.")
        ranges = list(_clip_ranges(item))
        ranges[clip_index : clip_index + 1] = ((clip.start_ms, position), (position, clip.end_ms))
        return self._commit_user_edit(dataset, item, tuple(ranges), progress)

    def remove_clip(self, model_id: str, item_id: str, clip_id: str) -> ModelDataset:
        dataset = self.load(model_id)
        item = _require_item(dataset, item_id)
        clip_index = _clip_index(item, clip_id)
        if clip_index is None:
            return dataset
        ranges = list(_clip_ranges(item))
        del ranges[clip_index]
        return self._commit_user_edit(dataset, item, tuple(ranges))

    def undo_last_clip(self, model_id: str, item_id: str) -> ModelDataset:
        return self.undo_edit(model_id, item_id)

    def undo_edit(
        self,
        model_id: str,
        item_id: str,
        progress: Callable[[int], None] | None = None,
    ) -> ModelDataset:
        dataset = self.load(model_id)
        item = _require_item(dataset, item_id)
        target, history = item.edit_history.undo(_item_edit_state(item))
        if target is None:
            return dataset
        return self._commit_edit_state(dataset, item, target, history, progress)

    def redo_edit(
        self,
        model_id: str,
        item_id: str,
        progress: Callable[[int], None] | None = None,
    ) -> ModelDataset:
        dataset = self.load(model_id)
        item = _require_item(dataset, item_id)
        target, history = item.edit_history.redo(_item_edit_state(item))
        if target is None:
            return dataset
        return self._commit_edit_state(dataset, item, target, history, progress)

    def mark_item_ready(self, model_id: str, item_id: str) -> ModelDataset:
        dataset = self.load(model_id)
        item = _require_item(dataset, item_id)
        if not item.training_paths:
            raise ModelDatasetError("Add at least one clip before marking this audio ready.")
        if item.pending_segment_count:
            raise ModelDatasetError("Review or exclude every queued segment before marking this audio ready.")
        if item.review_state == REVIEW_READY:
            return dataset
        updated = _replace_dataset_item(dataset, replace(item, review_state=REVIEW_READY))
        self._save(updated)
        return updated

    def replace_segment_candidates(
        self,
        model_id: str,
        item_id: str,
        ranges: Iterable[tuple[int, int]],
    ) -> ModelDataset:
        dataset = self.load(model_id)
        item = _require_item(dataset, item_id)
        duration_ms = item.duration_ms or _safe_duration_ms(item.working_path)
        normalized = _normalize_clip_ranges(ranges, duration_ms)
        uncovered = tuple(
            candidate_range
            for candidate_range in normalized
            if not _range_is_covered(candidate_range, item.clips)
        )
        candidates = build_segment_candidates(uncovered, item.segment_candidates)
        review_state = REVIEW_EDITING if candidates else item.review_state
        updated = _replace_dataset_item(
            dataset,
            replace(
                item,
                duration_ms=duration_ms,
                training_mode=TRAINING_MODE_CLIPS if candidates else item.training_mode,
                segment_candidates=candidates,
                review_state=review_state,
                edit_history=item.edit_history.record(_item_edit_state(item)),
            ),
        )
        self._save(updated)
        return updated

    def set_segment_candidate_status(
        self,
        model_id: str,
        item_id: str,
        candidate_id: str,
        status: str,
    ) -> ModelDataset:
        dataset = self.load(model_id)
        item = _require_item(dataset, item_id)
        if not any(candidate.candidate_id == candidate_id for candidate in item.segment_candidates):
            return dataset
        candidates = update_candidate_status(item.segment_candidates, candidate_id, status)
        updated = _replace_dataset_item(
            dataset,
            replace(
                item,
                segment_candidates=candidates,
                review_state=REVIEW_EDITING,
                edit_history=item.edit_history.record(_item_edit_state(item)),
            ),
        )
        self._save(updated)
        return updated

    def accept_segment_candidate(
        self,
        model_id: str,
        item_id: str,
        candidate_id: str,
        start_ms: int,
        end_ms: int,
        progress: Callable[[int], None] | None = None,
    ) -> ModelDataset:
        dataset = self.load(model_id)
        item = _require_item(dataset, item_id)
        if not any(candidate.candidate_id == candidate_id for candidate in item.segment_candidates):
            return dataset
        duration_ms = item.duration_ms or _safe_duration_ms(item.working_path)
        accepted_range = _normalize_clip_ranges(((start_ms, end_ms),), duration_ms)[0]
        remaining = tuple(
            candidate for candidate in item.segment_candidates if candidate.candidate_id != candidate_id
        )
        current = _item_edit_state(item)
        target = ClipEditState(
            TRAINING_MODE_CLIPS,
            REVIEW_EDITING,
            _clip_ranges(item) + (accepted_range,),
            remaining,
        )
        return self._commit_edit_state(
            dataset,
            item,
            target,
            item.edit_history.record(current),
            progress,
        )

    def move_clip_to_review_status(
        self,
        model_id: str,
        item_id: str,
        clip_id: str,
        status: str,
    ) -> ModelDataset:
        dataset = self.load(model_id)
        item = _require_item(dataset, item_id)
        clip_index = _clip_index(item, clip_id)
        if clip_index is None:
            return dataset
        clip = item.clips[clip_index]
        candidates = tuple(
            candidate
            for candidate in item.segment_candidates
            if candidate.candidate_id != clip.clip_id
        ) + (
            SegmentCandidate(
                candidate_id=clip.clip_id,
                start_ms=clip.start_ms,
                end_ms=clip.end_ms,
                status=normalize_segment_status(status),
            ),
        )
        ranges = tuple(
            (candidate.start_ms, candidate.end_ms)
            for index, candidate in enumerate(item.clips)
            if index != clip_index
        )
        current = _item_edit_state(item)
        target = ClipEditState(
            TRAINING_MODE_CLIPS,
            REVIEW_EDITING,
            ranges,
            candidates,
        )
        return self._commit_edit_state(
            dataset,
            item,
            target,
            item.edit_history.record(current),
        )

    def apply_denoise(
        self,
        model_id: str,
        item_id: str,
        strength: int,
        sample_start_ms: int = 0,
        sample_end_ms: int = 0,
        progress: Callable[[int], None] | None = None,
    ) -> ModelDataset:
        dataset = self.load(model_id)
        item = _require_item(dataset, item_id)
        normalized_strength = max(0, min(100, int(strength)))
        duration_ms = item.duration_ms or _safe_duration_ms(item.working_path)
        sample_start, sample_end = _normalize_optional_range(sample_start_ms, sample_end_ms, duration_ms)
        version_id = uuid.uuid4().hex[:12]
        denoised_path = self._model_dir(model_id) / "processed" / item.item_id / f"denoised_{version_id}.wav"
        try:
            render_denoised_audio(
                item.working_path,
                denoised_path,
                normalized_strength,
                sample_start,
                sample_end,
                _scaled_progress(progress, 0, 70),
            )
            prepared_item = replace(
                item,
                denoised_path=denoised_path,
                denoise_strength=normalized_strength,
                denoise_sample_start_ms=sample_start,
                denoise_sample_end_ms=sample_end,
                review_state=REVIEW_EDITING,
            )
            target = ClipEditState(item.training_mode, REVIEW_EDITING, _clip_ranges(item))
            updated = self._commit_edit_state(
                dataset,
                prepared_item,
                target,
                item.edit_history,
                _scaled_progress(progress, 70, 100),
                force_render=True,
            )
        except Exception:
            _unlink_quietly(denoised_path)
            raise
        self._delete_processed_audio(item.denoised_path, model_id, except_path=denoised_path)
        return updated

    def remove_denoise(
        self,
        model_id: str,
        item_id: str,
        progress: Callable[[int], None] | None = None,
    ) -> ModelDataset:
        dataset = self.load(model_id)
        item = _require_item(dataset, item_id)
        if not item.has_denoised_audio:
            if progress is not None:
                progress(100)
            return dataset
        prepared_item = replace(
            item,
            denoised_path=None,
            review_state=REVIEW_EDITING,
        )
        target = ClipEditState(item.training_mode, REVIEW_EDITING, _clip_ranges(item))
        updated = self._commit_edit_state(
            dataset,
            prepared_item,
            target,
            item.edit_history,
            progress,
            force_render=True,
        )
        self._delete_processed_audio(item.denoised_path, model_id)
        return updated

    def _commit_user_edit(
        self,
        dataset: ModelDataset,
        item: ModelDatasetItem,
        ranges: tuple[tuple[int, int], ...],
        progress: Callable[[int], None] | None = None,
    ) -> ModelDataset:
        duration_ms = item.duration_ms or _safe_duration_ms(item.working_path)
        normalized = _normalize_clip_ranges(ranges, duration_ms)
        current = _item_edit_state(item)
        target = ClipEditState(
            TRAINING_MODE_CLIPS,
            REVIEW_EDITING,
            normalized,
            item.segment_candidates,
        )
        if target == current:
            if progress is not None:
                progress(100)
            return dataset
        return self._commit_edit_state(dataset, item, target, item.edit_history.record(current), progress)

    def _commit_edit_state(
        self,
        dataset: ModelDataset,
        item: ModelDatasetItem,
        target: ClipEditState,
        history: ClipEditHistory,
        progress: Callable[[int], None] | None = None,
        *,
        force_render: bool = False,
    ) -> ModelDataset:
        duration_ms = item.duration_ms or _safe_duration_ms(item.working_path)
        target_ranges = () if target.training_mode == TRAINING_MODE_FULL else target.ranges
        normalized = _normalize_clip_ranges(target_ranges, duration_ms)
        reusable = {} if force_render else {(clip.start_ms, clip.end_ms): clip for clip in item.clips}
        clips: list[ModelDatasetClip | None] = []
        pending: list[tuple[int, tuple[int, int]]] = []
        for index, clip_range in enumerate(normalized):
            clip = reusable.pop(clip_range, None)
            clips.append(clip)
            if clip is None:
                pending.append((index, clip_range))

        created_paths: list[Path] = []
        try:
            for render_index, (clip_index, (start, end)) in enumerate(pending):
                clip_id = uuid.uuid4().hex[:12]
                file_name = f"clip_{clip_index + 1:03d}_{clip_id}.wav"
                clip_path = self._model_dir(dataset.model_id) / "clips" / item.item_id / file_name

                def report(value: int, current_index: int = render_index) -> None:
                    if progress is not None:
                        progress(round((current_index * 100 + value) / len(pending)))

                render_audio_clip(item.active_audio_path, clip_path, start, end, report)
                created_paths.append(clip_path)
                clips[clip_index] = ModelDatasetClip(
                    clip_id=clip_id,
                    start_ms=start,
                    end_ms=end,
                    path=clip_path,
                    created_at=datetime.now(UTC).isoformat(),
                )
            completed_clips = tuple(clip for clip in clips if clip is not None)
            segment_candidates = (
                item.segment_candidates
                if target.segment_candidates is None
                else target.segment_candidates
            )
            updated_item = replace(
                item,
                duration_ms=duration_ms,
                clips=completed_clips,
                training_mode=target.training_mode,
                review_state=target.review_state,
                edit_history=history,
                segment_candidates=segment_candidates,
            )
            updated = _replace_dataset_item(dataset, updated_item)
            self._save(updated)
        except Exception:
            for path in created_paths:
                _unlink_quietly(path)
            raise

        retained_paths = {clip.path for clip in completed_clips}
        for old_clip in item.clips:
            if old_clip.path not in retained_paths and _is_within(old_clip.path, self._model_dir(dataset.model_id)):
                _unlink_quietly(old_clip.path)
        if progress is not None:
            progress(100)
        return updated

    def _delete_processed_audio(
        self,
        path: Path | None,
        model_id: str,
        *,
        except_path: Path | None = None,
    ) -> None:
        if path is None or path == except_path:
            return
        if _is_within(path, self._model_dir(model_id)):
            _unlink_quietly(path)

    def reset_item(
        self,
        model_id: str,
        item_id: str,
        progress: Callable[[int], None] | None = None,
    ) -> ModelDataset:
        dataset = self.load(model_id)
        item = _require_item(dataset, item_id)
        source_size = item.original_path.stat().st_size
        copied_bytes = 0

        def report(chunk_size: int) -> None:
            nonlocal copied_bytes
            copied_bytes += chunk_size
            if progress is not None:
                progress(_percentage(copied_bytes, source_size))

        _copy_file_atomic(item.original_path, item.working_path, report)
        updated_item = replace(
            item,
            duration_ms=_safe_duration_ms(item.original_path),
            clips=(),
            training_mode=TRAINING_MODE_FULL,
            review_state=REVIEW_UNREVIEWED,
            edit_history=ClipEditHistory(),
            segment_candidates=(),
            denoised_path=None,
            denoise_strength=0,
            denoise_sample_start_ms=0,
            denoise_sample_end_ms=0,
        )
        updated = _replace_dataset_item(dataset, updated_item)
        self._save(updated)
        model_dir = self._model_dir(model_id)
        for clip in item.clips:
            if _is_within(clip.path, model_dir):
                _unlink_quietly(clip.path)
        self._delete_processed_audio(item.denoised_path, model_id)
        if progress is not None:
            progress(100)
        return updated

    def remove_items(self, model_id: str, item_ids: Iterable[str]) -> ModelDataset:
        dataset = self.load(model_id)
        removed_ids = set(item_ids)
        removed = tuple(item for item in dataset.items if item.item_id in removed_ids)
        kept = tuple(item for item in dataset.items if item.item_id not in removed_ids)
        updated = ModelDataset(model_id, _normalize_selected_order(kept))
        self._save(updated)
        model_dir = self._model_dir(model_id)
        for item in removed:
            processed_paths = (item.denoised_path,) if item.denoised_path is not None else ()
            for path in (
                item.original_path,
                item.working_path,
                *processed_paths,
                *(clip.path for clip in item.clips),
            ):
                if _is_within(path, model_dir):
                    _unlink_quietly(path)
        return updated

    def _save(self, dataset: ModelDataset) -> None:
        model_dir = self._model_dir(dataset.model_id)
        manifest = model_dir / DATASET_MANIFEST_NAME
        data = {
            "version": DATASET_VERSION,
            "model_id": dataset.model_id,
            "items": [self._item_to_data(item, model_dir) for item in dataset.items],
        }
        write_json_atomic(manifest, data)
        self._cache_dataset(dataset, self._manifest_revision(manifest))

    @staticmethod
    def _manifest_revision(manifest: Path) -> tuple[int, int, int] | None:
        try:
            stat = manifest.stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size

    def _cache_dataset(
        self,
        dataset: ModelDataset,
        revision: tuple[int, int, int] | None,
    ) -> ModelDataset:
        self._dataset_cache[dataset.model_id] = revision, dataset
        return dataset

    def _model_dir(self, model_id: str) -> Path:
        if not _MODEL_ID_PATTERN.fullmatch(model_id):
            raise ModelDatasetError(f"Invalid model id: {model_id}")
        return self.root / model_id

    @staticmethod
    def _item_to_data(item: ModelDatasetItem, model_dir: Path) -> dict[str, object]:
        return {
            "id": item.item_id,
            "source_name": item.source_name,
            "source_path": str(item.source_path),
            "original_path": item.original_path.relative_to(model_dir).as_posix(),
            "working_path": item.working_path.relative_to(model_dir).as_posix(),
            "denoised_path": (
                item.denoised_path.relative_to(model_dir).as_posix() if item.denoised_path is not None else ""
            ),
            "denoise_strength": item.denoise_strength,
            "denoise_sample_start_ms": item.denoise_sample_start_ms,
            "denoise_sample_end_ms": item.denoise_sample_end_ms,
            "added_at": item.added_at,
            "duration_ms": item.duration_ms,
            "selected_order": item.selected_order,
            "training_mode": item.training_mode,
            "review_state": item.review_state,
            "edit_history": history_to_data(item.edit_history),
            "segment_candidates": [
                {
                    "id": candidate.candidate_id,
                    "start_ms": candidate.start_ms,
                    "end_ms": candidate.end_ms,
                    "status": candidate.status,
                }
                for candidate in item.segment_candidates
            ],
            "clips": [
                {
                    "id": clip.clip_id,
                    "start_ms": clip.start_ms,
                    "end_ms": clip.end_ms,
                    "path": clip.path.relative_to(model_dir).as_posix(),
                    "created_at": clip.created_at,
                }
                for clip in item.clips
            ],
        }

    @staticmethod
    def _item_from_data(data: dict[str, object], model_dir: Path) -> ModelDatasetItem:
        selected_order = data.get("selected_order")
        if selected_order is not None:
            selected_order = int(selected_order)
        clips = tuple(
            ModelDatasetClip(
                clip_id=str(clip["id"]),
                start_ms=max(0, int(clip["start_ms"])),
                end_ms=max(0, int(clip["end_ms"])),
                path=_manifest_path(model_dir, str(clip["path"])),
                created_at=str(clip["created_at"]),
            )
            for clip in data.get("clips", [])
            if isinstance(clip, dict)
        )
        fallback_mode = TRAINING_MODE_CLIPS if clips else TRAINING_MODE_FULL
        fallback_review = REVIEW_EDITING if clips else REVIEW_UNREVIEWED
        state = state_from_values(
            data.get("training_mode", fallback_mode),
            data.get("review_state", fallback_review),
            _ranges_from_clips(clips),
        )
        segment_candidates = tuple(
            SegmentCandidate(
                candidate_id=str(candidate["id"]),
                start_ms=max(0, int(candidate["start_ms"])),
                end_ms=max(0, int(candidate["end_ms"])),
                status=normalize_segment_status(candidate.get("status")),
            )
            for candidate in data.get("segment_candidates", [])
            if isinstance(candidate, dict)
        )
        return ModelDatasetItem(
            item_id=str(data["id"]),
            source_name=str(data["source_name"]),
            source_path=Path(str(data["source_path"])).expanduser(),
            original_path=_manifest_path(model_dir, str(data["original_path"])),
            working_path=_manifest_path(model_dir, str(data["working_path"])),
            added_at=str(data["added_at"]),
            duration_ms=max(0, int(data.get("duration_ms", 0))),
            selected_order=selected_order,
            clips=clips,
            training_mode=TRAINING_MODE_CLIPS if segment_candidates else state.training_mode,
            review_state=state.review_state,
            edit_history=history_from_data(data.get("edit_history")),
            segment_candidates=segment_candidates,
            denoised_path=_optional_manifest_path(model_dir, data.get("denoised_path")),
            denoise_strength=max(0, min(100, int(data.get("denoise_strength", 0)))),
            denoise_sample_start_ms=max(0, int(data.get("denoise_sample_start_ms", 0))),
            denoise_sample_end_ms=max(0, int(data.get("denoise_sample_end_ms", 0))),
        )


def _validated_audio_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    resolved: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        candidate = path.expanduser().resolve()
        if not candidate.is_file() or candidate.suffix.casefold() not in SUPPORTED_AUDIO_EXTENSIONS:
            raise ModelDatasetError(f"Unsupported audio file: {candidate}")
        key = _path_key(candidate)
        if key not in seen:
            seen.add(key)
            resolved.append(candidate)
    return tuple(resolved)


def _copy_file_atomic(source: Path, target: Path, report: Callable[[int], None]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f"{target.suffix}.copying")
    try:
        with source.open("rb") as source_file, temporary.open("wb") as target_file:
            while chunk := source_file.read(1024 * 1024):
                target_file.write(chunk)
                report(len(chunk))
        os.replace(temporary, target)
        shutil.copystat(source, target)
    finally:
        _unlink_quietly(temporary)


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        # A waveform preview may briefly retain a Windows file handle.
        pass


def _manifest_path(model_dir: Path, value: str) -> Path:
    path = (model_dir / Path(value)).resolve()
    if not _is_within(path, model_dir):
        raise ValueError("Dataset path leaves the model workspace")
    return path


def _optional_manifest_path(model_dir: Path, value: object) -> Path | None:
    return _manifest_path(model_dir, value) if isinstance(value, str) and value else None


def _normalize_selected_order(items: tuple[ModelDatasetItem, ...]) -> tuple[ModelDatasetItem, ...]:
    selected = sorted((item for item in items if item.is_selected), key=lambda item: item.selected_order or 0)
    order_by_id = {item.item_id: index for index, item in enumerate(selected)}
    return tuple(
        replace(item, selected_order=order_by_id[item.item_id]) if item.is_selected else item
        for item in items
    )


def _require_item(dataset: ModelDataset, item_id: str) -> ModelDatasetItem:
    item = next((candidate for candidate in dataset.items if candidate.item_id == item_id), None)
    if item is None:
        raise ModelDatasetError(f"Dataset item is not registered: {item_id}")
    return item


def _replace_dataset_item(dataset: ModelDataset, updated_item: ModelDatasetItem) -> ModelDataset:
    return ModelDataset(
        dataset.model_id,
        tuple(updated_item if item.item_id == updated_item.item_id else item for item in dataset.items),
    )


def _unique_values(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _clip_ranges(item: ModelDatasetItem) -> tuple[tuple[int, int], ...]:
    return _ranges_from_clips(item.clips)


def _ranges_from_clips(clips: tuple[ModelDatasetClip, ...]) -> tuple[tuple[int, int], ...]:
    return tuple((clip.start_ms, clip.end_ms) for clip in clips)


def _clip_index(item: ModelDatasetItem, clip_id: str) -> int | None:
    return next((index for index, clip in enumerate(item.clips) if clip.clip_id == clip_id), None)


def _range_is_covered(candidate_range: tuple[int, int], clips: tuple[ModelDatasetClip, ...]) -> bool:
    start_ms, end_ms = candidate_range
    duration_ms = end_ms - start_ms
    if duration_ms <= 0:
        return True
    for clip in clips:
        overlap = max(0, min(end_ms, clip.end_ms) - max(start_ms, clip.start_ms))
        if overlap / duration_ms >= 0.8:
            return True
    return False


def _item_edit_state(item: ModelDatasetItem) -> ClipEditState:
    return ClipEditState(
        item.training_mode,
        item.review_state,
        _clip_ranges(item),
        item.segment_candidates,
    )


def _normalize_clip_ranges(ranges: Iterable[tuple[int, int]], duration_ms: int) -> tuple[tuple[int, int], ...]:
    normalized: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for start_ms, end_ms in ranges:
        start = max(0, min(int(start_ms), duration_ms))
        end = max(0, min(int(end_ms), duration_ms))
        if end - start < 100:
            raise ModelDatasetError("Select at least 100 ms of audio.")
        clip_range = (start, end)
        if clip_range not in seen:
            normalized.append(clip_range)
            seen.add(clip_range)
    return tuple(normalized)


def _normalize_optional_range(start_ms: int, end_ms: int, duration_ms: int) -> tuple[int, int]:
    start = max(0, min(int(start_ms), duration_ms))
    end = max(start, min(int(end_ms), duration_ms))
    return (start, end) if end - start >= 100 else (0, 0)


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path.expanduser().resolve()))


def _is_within(path: Path, directory: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(directory.expanduser().resolve())
        return True
    except ValueError:
        return False


def _percentage(current: int, total: int) -> int:
    if total <= 0:
        return 100
    return max(0, min(100, round(current * 100 / total)))


def _scaled_progress(
    progress: Callable[[int], None] | None,
    start: int,
    end: int,
) -> Callable[[int], None] | None:
    if progress is None:
        return None
    span = max(0, end - start)
    return lambda value: progress(start + round(max(0, min(100, value)) * span / 100))


def _safe_duration_ms(path: Path) -> int:
    try:
        return max(0, read_audio_metadata(path).duration_ms)
    except Exception:
        return 0
