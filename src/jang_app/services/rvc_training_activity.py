from __future__ import annotations

import re

from jang_app.services.i18n import tr


_F0_PROGRESS = re.compile(
    r"f0ing,\s*now-(?P<current>\d+),\s*all-(?P<total>\d+)",
    re.IGNORECASE,
)
_FEATURE_PROGRESS = re.compile(
    r"now-(?P<total>\d+),\s*all-(?P<current>\d+),",
    re.IGNORECASE,
)
_FEATURE_TOTAL = re.compile(r"all-feature-(?P<total>\d+)", re.IGNORECASE)
_CHECKPOINT_SAVE = re.compile(
    r"saving ckpt\s+.+_e(?P<epoch>\d+)_s(?P<step>\d+)",
    re.IGNORECASE,
)
_INDEX_PROGRESS = re.compile(r"JJZERO_INDEX_PROGRESS=(?P<progress>\d+)")
_TRAINING_START = re.compile(
    r"JJZERO_TRAINING_START\s+current=(?P<current>\d+)\s+target=(?P<target>\d+)",
    re.IGNORECASE,
)
_TRAINING_STEP = re.compile(
    r"Train\s+Epoch:\s*(?P<epoch>\d+)\s*\[\s*(?P<progress>\d+(?:\.\d+)?)%\s*\]",
    re.IGNORECASE,
)


def describe_rvc_training_activity(line: str) -> str | None:
    """Convert noisy RVC process output into a short user-facing activity update."""

    text = str(line).strip()
    if not text:
        return None

    match = _TRAINING_START.search(text)
    if match is not None:
        next_epoch = min(int(match.group("target")), int(match.group("current")) + 1)
        return tr(
            "Preparing epoch {epoch} / {target}; the first epoch can take longer",
            epoch=next_epoch,
            target=int(match.group("target")),
        )

    match = _TRAINING_STEP.search(text)
    if match is not None:
        return tr(
            "Training epoch {epoch}; current epoch {progress}%",
            epoch=int(match.group("epoch")),
            progress=round(float(match.group("progress"))),
        )

    match = _F0_PROGRESS.search(text)
    if match is not None:
        current = min(int(match.group("total")), int(match.group("current")) + 1)
        return tr(
            "Analyzing pitch {current} / {total}",
            current=current,
            total=int(match.group("total")),
        )

    match = _FEATURE_PROGRESS.search(text)
    if match is not None:
        current = min(int(match.group("total")), int(match.group("current")) + 1)
        return tr(
            "Analyzing voice features {current} / {total}",
            current=current,
            total=int(match.group("total")),
        )

    match = _FEATURE_TOTAL.search(text)
    if match is not None:
        return tr(
            "Preparing voice feature analysis for {total} clips",
            total=int(match.group("total")),
        )

    match = _CHECKPOINT_SAVE.search(text)
    if match is not None:
        return tr(
            "Saving the epoch {epoch} checkpoint",
            epoch=int(match.group("epoch")),
        )

    match = _INDEX_PROGRESS.search(text)
    if match is not None:
        return tr(
            "Building the retrieval index {progress}%",
            progress=max(0, min(100, int(match.group("progress")))),
        )

    lowered = text.casefold()
    if "jjzero_single_device_training" in lowered:
        return tr("Initializing single-GPU training")
    if "jjzero_training_data_loader_start" in lowered:
        return tr("Loading the first training batch")
    if "jjzero_training_first_batch_ready" in lowered:
        return tr("First training batch loaded; starting model optimization")
    if text.endswith("->Suc."):
        return tr("Preparing audio segments")
    if "loading rmvpe model" in lowered:
        return tr("Loading the pitch analysis model")
    if "all-feature-done" in lowered:
        return tr("Voice feature analysis completed")
    if "gpu extraction left incomplete" in lowered:
        return tr("Recovering missing feature files on CPU")
    if "training is done" in lowered:
        return tr("Model optimization completed")
    return None


def training_stage_detail(stage: str) -> str:
    return tr(
        {
            "Preparing Training": "Checking training materials and runtime",
            "Preparing Audio": "Splitting and normalizing the selected audio",
            "Extracting Features": "Analyzing pitch and voice characteristics",
            "Building File List": "Building the training file list",
            "Preparing Spectrograms": "Preparing reusable audio calculations",
            "Training Model": "Optimizing the voice model epoch by epoch",
            "Building Index": "Building the voice retrieval index",
            "Registering Model": "Registering the completed model in the library",
            "Stopping Training": "Stopping safely after the current operation",
        }.get(stage, "Running the current training step")
    )
