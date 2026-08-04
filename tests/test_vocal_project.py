from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from jang_app.services.vocal_project import (
    UNASSIGNED_SPEAKER_ID,
    VOCAL_PROJECT_SCHEMA_VERSION,
    VocalProject,
    VocalProjectValidationError,
    VocalSegment,
    VocalSpeaker,
    VocalTake,
    validate_vocal_project,
)


class VocalProjectTests(unittest.TestCase):
    def test_valid_project_accepts_gaps_and_muted_segments(self) -> None:
        project = _project(
            segments=(
                VocalSegment("segment-001", 0, 400, UNASSIGNED_SPEAKER_ID),
                VocalSegment("segment-002", 500, 900, UNASSIGNED_SPEAKER_ID, muted=True),
            )
        )

        validate_vocal_project(project)

    def test_overlapping_segments_are_rejected(self) -> None:
        project = _project(
            segments=(
                VocalSegment("segment-001", 0, 600, UNASSIGNED_SPEAKER_ID),
                VocalSegment("segment-002", 500, 900, UNASSIGNED_SPEAKER_ID),
            )
        )

        with self.assertRaisesRegex(VocalProjectValidationError, "overlap"):
            validate_vocal_project(project)

    def test_unknown_speaker_and_missing_active_take_are_rejected(self) -> None:
        unknown_speaker = replace(
            _project(),
            segments=(VocalSegment("segment-001", 0, 1000, "speaker-missing"),),
        )
        missing_take = replace(_project(), active_take_id="take-missing")

        with self.assertRaisesRegex(VocalProjectValidationError, "Unknown speaker"):
            validate_vocal_project(unknown_speaker)
        with self.assertRaisesRegex(VocalProjectValidationError, "Active take"):
            validate_vocal_project(missing_take)


def _project(*, segments: tuple[VocalSegment, ...] | None = None) -> VocalProject:
    timestamp = "2026-08-04T12:00:00+00:00"
    return VocalProject(
        schema_version=VOCAL_PROJECT_SCHEMA_VERSION,
        project_id="vocal-test",
        created_at=timestamp,
        updated_at=timestamp,
        duration_ms=1000,
        vocals_path=Path("vocals.wav"),
        instrumental_path=Path("no_vocals.wav"),
        speakers=(VocalSpeaker(UNASSIGNED_SPEAKER_ID, "Unassigned", "#898780"),),
        segments=segments
        if segments is not None
        else (VocalSegment("segment-001", 0, 1000, UNASSIGNED_SPEAKER_ID),),
        takes=(
            VocalTake(
                "take-existing",
                "Existing",
                Path("vocals_rvc_existing.wav"),
                timestamp,
            ),
        ),
    )


if __name__ == "__main__":
    unittest.main()
