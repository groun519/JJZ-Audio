from __future__ import annotations

import json
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from jang_app.services.managed_files import write_json_atomic
from jang_app.services.tool_workspace import new_storage_key
from jang_app.services.vocal_split import (
    VocalReferenceRegion,
    VocalSplitOperation,
    VocalSplitRun,
    VocalSplitStem,
)


VOCAL_SPLIT_FOLDER = "vocal_splits"
VOCAL_SPLIT_MANIFEST = "vocal_split.json"
VOCAL_SPLIT_SCHEMA = 3
_LEGACY_METHOD_ID = "lead-backing-v1"
_LEGACY_DEFAULT_LABELS = {
    "lead",
    "lead vocal",
    "main",
    "main vocal",
    "backing",
    "backing vocal",
}


class VocalSplitStoreError(RuntimeError):
    pass


class VocalSplitStore:
    def create_run_dir(self, parent_job_dir: Path) -> Path:
        root = _split_root(parent_job_dir)
        root.mkdir(parents=True, exist_ok=True)
        run_dir = root / new_storage_key("g")
        while run_dir.exists():
            run_dir = root / new_storage_key("g")
        run_dir.mkdir()
        return run_dir

    def create_group(
        self,
        parent_job_dir: Path,
        input_path: Path,
        *,
        label: str = "Original vocal",
    ) -> VocalSplitRun:
        parent = parent_job_dir.expanduser().resolve()
        source = _require_existing_within(parent, input_path, "vocal group input")
        run_dir = self.create_run_dir(parent)
        root = VocalSplitStem(
            "root",
            "vocal",
            label.strip() or "Original vocal",
            source,
            origin="root",
        )
        group = VocalSplitRun(
            run_id=run_dir.name,
            parent_job_dir=parent,
            input_path=source,
            method_id="vocal-group-v2",
            method_label="Vocal group",
            model="",
            created_at=_now(),
            stems=(root,),
            nodes=(root,),
            operations=(),
        )
        self._save(group)
        return group

    def create_operation_dir(self, group: VocalSplitRun) -> Path:
        group_dir = _require_run_dir(group.parent_job_dir, _run_dir(group))
        root = group_dir / "operations"
        root.mkdir(exist_ok=True)
        operation_dir = root / new_storage_key("o")
        while operation_dir.exists():
            operation_dir = root / new_storage_key("o")
        operation_dir.mkdir()
        return operation_dir

    def complete_split(
        self,
        group: VocalSplitRun,
        input_stem_id: str,
        operation_dir: Path,
        extracted_path: Path,
        remaining_path: Path,
        *,
        reference_regions: Iterable[VocalReferenceRegion],
        model: str,
    ) -> VocalSplitRun:
        selected = group.stem(input_stem_id)
        if selected is None or not selected.active:
            raise VocalSplitStoreError("The selected vocal is no longer active")
        normalized_regions = _normalize_reference_regions(reference_regions)

        managed_operation = _require_operation_dir(group, operation_dir)
        extracted = _require_existing_within(
            managed_operation,
            extracted_path,
            "extracted vocal",
        )
        remaining = _require_existing_within(
            managed_operation,
            remaining_path,
            "remaining vocal",
        )
        operation_id = managed_operation.name
        extracted_id = f"{operation_id}-v"
        remaining_id = f"{operation_id}-r"
        generation = selected.generation + 1
        extracted_node = VocalSplitStem(
            extracted_id,
            "vocal",
            f"Vocal {_next_vocal_number(group)}",
            extracted,
            parent_stem_id=selected.stem_id,
            generation=generation,
            origin="extracted",
        )
        remaining_node = VocalSplitStem(
            remaining_id,
            "vocal",
            "Remaining vocal",
            remaining,
            parent_stem_id=selected.stem_id,
            generation=generation,
            origin="remaining",
        )
        inactive_selected = replace(selected, active=False)
        nodes = tuple(
            inactive_selected if node.stem_id == selected.stem_id else node
            for node in group.all_stems
        ) + (extracted_node, remaining_node)
        active_stems: list[VocalSplitStem] = []
        for stem in group.stems:
            if stem.stem_id == selected.stem_id:
                active_stems.extend((extracted_node, remaining_node))
            else:
                active_stems.append(stem)
        operation = VocalSplitOperation(
            operation_id=operation_id,
            input_stem_id=selected.stem_id,
            output_stem_ids=(extracted_id, remaining_id),
            reference_regions=normalized_regions,
            model=model.strip(),
            created_at=_now(),
        )
        updated = replace(
            group,
            method_id="singer-reference-v1",
            method_label="Reference vocal split",
            model=model.strip(),
            stems=tuple(active_stems),
            nodes=nodes,
            operations=group.operations + (operation,),
        )
        self._save(updated)
        return updated

    def register(
        self,
        parent_job_dir: Path,
        run_dir: Path,
        input_path: Path,
        *,
        method_id: str,
        method_label: str,
        model: str,
        stems: Iterable[VocalSplitStem],
    ) -> VocalSplitRun:
        """Import an old one-shot result as a group without changing its files."""
        parent = parent_job_dir.expanduser().resolve()
        managed_run = _require_run_dir(parent, run_dir)
        source = _require_existing_within(parent, input_path, "vocal split input")
        root = VocalSplitStem(
            "root",
            "vocal",
            "Original vocal",
            source,
            active=False,
            origin="root",
        )
        normalized = tuple(
            VocalSplitStem(
                stem.stem_id.strip(),
                "vocal",
                f"Vocal {index}"
                if method_id == _LEGACY_METHOD_ID
                and stem.label.strip().casefold() in _LEGACY_DEFAULT_LABELS
                else stem.label.strip() or f"Vocal {index}",
                _require_existing_within(managed_run, stem.path, "vocal split stem"),
                parent_stem_id="root",
                generation=1,
                origin="extracted" if index == 1 else "remaining",
            )
            for index, stem in enumerate(stems, start=1)
        )
        if not normalized:
            raise VocalSplitStoreError("A vocal split requires at least one stem")
        if any(not stem.stem_id for stem in normalized):
            raise VocalSplitStoreError("Vocal split stem IDs are required")
        if len({stem.stem_id for stem in normalized}) != len(normalized):
            raise VocalSplitStoreError("Vocal split stem IDs must be unique")
        operations: tuple[VocalSplitOperation, ...] = ()
        if len(normalized) >= 2:
            operations = (
                VocalSplitOperation(
                    "legacy",
                    "root",
                    (normalized[0].stem_id, normalized[1].stem_id),
                    (),
                    model.strip(),
                    _now(),
                ),
            )
        group = VocalSplitRun(
            managed_run.name,
            parent,
            source,
            method_id.strip() or "vocal-split",
            "Two-vocal split"
            if method_id == _LEGACY_METHOD_ID
            else method_label.strip() or "Vocal Split",
            model.strip(),
            _now(),
            normalized,
            (root, *normalized),
            operations,
        )
        self._save(group)
        return group

    def runs(self, parent_job_dir: Path) -> tuple[VocalSplitRun, ...]:
        parent = parent_job_dir.expanduser().resolve()
        root = _split_root(parent)
        if not root.is_dir():
            return ()
        loaded: list[VocalSplitRun] = []
        for manifest in root.glob(f"*/{VOCAL_SPLIT_MANIFEST}"):
            try:
                group = self._load(parent, manifest)
            except (
                KeyError,
                OSError,
                TypeError,
                ValueError,
                VocalSplitStoreError,
                json.JSONDecodeError,
            ):
                continue
            if group.stems:
                loaded.append(group)
        return tuple(sorted(loaded, key=lambda group: group.created_at, reverse=True))

    def rename_stem(
        self,
        group: VocalSplitRun,
        stem_id: str,
        label: str,
    ) -> VocalSplitRun:
        value = label.strip()
        if not value:
            raise VocalSplitStoreError("A vocal stem name is required")
        if group.node(stem_id) is None:
            raise VocalSplitStoreError(f"Unknown vocal stem: {stem_id}")
        nodes = tuple(
            replace(stem, label=value) if stem.stem_id == stem_id else stem
            for stem in group.all_stems
        )
        active_by_id = {stem.stem_id: stem for stem in nodes if stem.active}
        updated = replace(
            group,
            nodes=nodes,
            stems=tuple(active_by_id[stem.stem_id] for stem in group.stems),
        )
        self._save(updated)
        return updated

    def remove_stem(self, group: VocalSplitRun, stem_id: str) -> VocalSplitRun | None:
        target = group.stem(stem_id)
        if target is None:
            raise VocalSplitStoreError(f"Unknown vocal stem: {stem_id}")
        if target.origin == "root":
            raise VocalSplitStoreError("The original vocal cannot be removed from a group")
        target_path = _require_within(_run_dir(group), target.path, "vocal split stem")
        target_path.unlink(missing_ok=True)
        remaining = tuple(stem for stem in group.stems if stem.stem_id != stem_id)
        if not remaining:
            self.remove_run(group)
            return None
        updated = replace(
            group,
            stems=remaining,
            nodes=tuple(node for node in group.all_stems if node.stem_id != stem_id),
        )
        self._save(updated)
        return updated

    def remove_run(self, group: VocalSplitRun) -> None:
        run_dir = _require_run_dir(group.parent_job_dir, _run_dir(group))
        if not (run_dir / VOCAL_SPLIT_MANIFEST).is_file():
            raise VocalSplitStoreError("Vocal group manifest is missing")
        shutil.rmtree(run_dir)

    def _save(self, group: VocalSplitRun) -> None:
        run_dir = _require_run_dir(group.parent_job_dir, _run_dir(group))
        write_json_atomic(
            run_dir / VOCAL_SPLIT_MANIFEST,
            {
                "schema": VOCAL_SPLIT_SCHEMA,
                "group_id": group.run_id,
                "created_at": group.created_at,
                "input": _relative(group.parent_job_dir, group.input_path),
                "method": {
                    "id": group.method_id,
                    "label": group.method_label,
                    "model": group.model,
                },
                "nodes": [
                    {
                        "id": stem.stem_id,
                        "role": stem.role,
                        "label": stem.label,
                        "file": _relative(group.parent_job_dir, stem.path),
                        "parent": stem.parent_stem_id,
                        "generation": stem.generation,
                        "active": stem.active,
                        "origin": stem.origin,
                    }
                    for stem in group.all_stems
                ],
                "operations": [
                    {
                        "id": operation.operation_id,
                        "input": operation.input_stem_id,
                        "outputs": list(operation.output_stem_ids),
                        "reference_regions": [
                            {
                                "id": region.region_id,
                                "start_ms": region.start_ms,
                                "end_ms": region.end_ms,
                            }
                            for region in operation.reference_regions
                        ],
                        "model": operation.model,
                        "created_at": operation.created_at,
                    }
                    for operation in group.operations
                ],
            },
        )

    def _load(self, parent: Path, manifest: Path) -> VocalSplitRun:
        run_dir = _require_run_dir(parent, manifest.parent)
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(data, Mapping):
            raise ValueError("Invalid vocal group manifest")
        schema = int(data.get("schema", 1))
        if schema == 1:
            return _load_v1(parent, run_dir, data)
        if schema not in {2, VOCAL_SPLIT_SCHEMA}:
            raise ValueError("Unsupported vocal group manifest")
        method = _mapping(data.get("method"), "vocal group method")
        nodes = tuple(
            _load_node(parent, item)
            for item in _mapping_items(data.get("nodes"), "vocal group nodes")
        )
        active = tuple(node for node in nodes if node.active and node.path.is_file())
        operations = tuple(
            _load_operation(item)
            for item in _mapping_items(
                data.get("operations", []),
                "vocal split operations",
            )
        )
        return VocalSplitRun(
            run_dir.name,
            parent,
            _require_existing_within(
                parent,
                parent / str(data["input"]),
                "vocal group input",
            ),
            str(method.get("id", "vocal-group-v2")),
            str(method.get("label", "Vocal group")),
            str(method.get("model", "")),
            str(data.get("created_at", "")),
            active,
            nodes,
            operations,
        )


def _load_v1(parent: Path, run_dir: Path, data: Mapping[object, object]) -> VocalSplitRun:
    method = _mapping(data.get("method"), "vocal split method")
    method_id = str(method.get("id", "vocal-split"))
    source = _require_existing_within(
        parent,
        parent / str(data["input"]),
        "vocal split input",
    )
    root = VocalSplitStem(
        "root",
        "vocal",
        "Original vocal",
        source,
        active=False,
        origin="root",
    )
    stems = tuple(
        _load_v1_stem(run_dir, item, index, legacy=method_id == _LEGACY_METHOD_ID)
        for index, item in enumerate(
            _mapping_items(data.get("stems"), "vocal split stems"),
            start=1,
        )
    )
    operations: tuple[VocalSplitOperation, ...] = ()
    if len(stems) >= 2:
        operations = (
            VocalSplitOperation(
                "legacy",
                "root",
                (stems[0].stem_id, stems[1].stem_id),
                (),
                str(method.get("model", "")),
                str(data.get("created_at", "")),
            ),
        )
    return VocalSplitRun(
        run_dir.name,
        parent,
        source,
        method_id,
        "Two-vocal split"
        if method_id == _LEGACY_METHOD_ID
        else str(method.get("label", "Vocal Split")),
        str(method.get("model", "")),
        str(data.get("created_at", "")),
        stems,
        (root, *stems),
        operations,
    )


def _load_v1_stem(
    run_dir: Path,
    item: Mapping[object, object],
    index: int,
    *,
    legacy: bool,
) -> VocalSplitStem:
    label = str(item.get("label", "")).strip()
    if not label or (legacy and label.casefold() in _LEGACY_DEFAULT_LABELS):
        label = f"Vocal {index}"
    return VocalSplitStem(
        str(item["id"]),
        "vocal",
        label,
        _require_existing_within(
            run_dir,
            run_dir / str(item["file"]),
            "vocal split stem",
        ),
        parent_stem_id="root",
        generation=1,
        origin="extracted" if index == 1 else "remaining",
    )


def _load_node(parent: Path, item: Mapping[object, object]) -> VocalSplitStem:
    path = _require_within(parent, parent / str(item["file"]), "vocal group node")
    active = bool(item.get("active", True)) and path.is_file()
    return VocalSplitStem(
        str(item["id"]),
        str(item.get("role", "vocal")),
        str(item.get("label", "Vocal")),
        path,
        str(item.get("parent", "")),
        int(item.get("generation", 0)),
        active,
        str(item.get("origin", "vocal")),
    )


def _load_operation(item: Mapping[object, object]) -> VocalSplitOperation:
    outputs = item.get("outputs")
    if not isinstance(outputs, list) or len(outputs) != 2:
        raise TypeError("A vocal split operation requires two outputs")
    raw_regions = item.get("reference_regions")
    if isinstance(raw_regions, list):
        reference_regions = (
            _normalize_reference_regions(
                VocalReferenceRegion(
                    str(region.get("id", "")),
                    int(region.get("start_ms", 0)),
                    int(region.get("end_ms", 0)),
                )
                for region in raw_regions
                if isinstance(region, Mapping)
            )
            if raw_regions
            else ()
        )
    else:
        start_ms = int(item.get("reference_start_ms", 0))
        end_ms = int(item.get("reference_end_ms", 0))
        reference_regions = (
            (VocalReferenceRegion("reference-1", start_ms, end_ms),)
            if start_ms >= 0 and end_ms > start_ms
            else ()
        )
    return VocalSplitOperation(
        str(item["id"]),
        str(item["input"]),
        (str(outputs[0]), str(outputs[1])),
        reference_regions,
        str(item.get("model", "")),
        str(item.get("created_at", "")),
    )


def _normalize_reference_regions(
    regions: Iterable[VocalReferenceRegion],
) -> tuple[VocalReferenceRegion, ...]:
    normalized: list[VocalReferenceRegion] = []
    seen_ids: set[str] = set()
    for index, region in enumerate(regions, start=1):
        start_ms = int(region.start_ms)
        end_ms = int(region.end_ms)
        if start_ms < 0 or end_ms <= start_ms:
            raise VocalSplitStoreError("A valid solo reference range is required")
        region_id = region.region_id.strip() or f"reference-{index}"
        if region_id in seen_ids:
            raise VocalSplitStoreError("Solo reference range IDs must be unique")
        seen_ids.add(region_id)
        normalized.append(VocalReferenceRegion(region_id, start_ms, end_ms))
    if not normalized:
        raise VocalSplitStoreError("At least one solo reference range is required")
    normalized.sort(key=lambda region: (region.start_ms, region.end_ms, region.region_id))
    return tuple(normalized)


def _mapping(value: object, label: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"Invalid {label}")
    return value


def _mapping_items(value: object, label: str) -> tuple[Mapping[object, object], ...]:
    if not isinstance(value, list):
        raise TypeError(f"Invalid {label}")
    return tuple(item for item in value if isinstance(item, Mapping))


def _next_vocal_number(group: VocalSplitRun) -> int:
    return 1 + sum(1 for stem in group.all_stems if stem.origin == "extracted")


def _split_root(parent_job_dir: Path) -> Path:
    return parent_job_dir.expanduser().resolve() / VOCAL_SPLIT_FOLDER


def _run_dir(group: VocalSplitRun) -> Path:
    return group.parent_job_dir / VOCAL_SPLIT_FOLDER / group.run_id


def _require_run_dir(parent_job_dir: Path, run_dir: Path) -> Path:
    parent = parent_job_dir.expanduser().resolve()
    candidate = run_dir.expanduser().resolve()
    if candidate.parent != _split_root(parent) or candidate.name in {"", ".", ".."}:
        raise VocalSplitStoreError("Vocal group is outside the managed result folder")
    return candidate


def _require_operation_dir(group: VocalSplitRun, operation_dir: Path) -> Path:
    group_dir = _require_run_dir(group.parent_job_dir, _run_dir(group))
    candidate = operation_dir.expanduser().resolve()
    if candidate.parent != group_dir / "operations" or candidate.name in {"", ".", ".."}:
        raise VocalSplitStoreError("Vocal split operation is outside its group")
    return candidate


def _require_existing_within(root: Path, path: Path, label: str) -> Path:
    resolved = _require_within(root, path, label)
    if not resolved.is_file():
        raise VocalSplitStoreError(f"{label} does not exist")
    return resolved


def _require_within(root: Path, path: Path, label: str) -> Path:
    resolved_root = root.expanduser().resolve()
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise VocalSplitStoreError(f"{label} is outside its managed folder") from exc
    return resolved


def _relative(parent: Path, path: Path) -> str:
    return str(path.expanduser().resolve().relative_to(parent.expanduser().resolve()))


def _now() -> str:
    return datetime.now(UTC).isoformat()
