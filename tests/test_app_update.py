from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from urllib.request import Request
from unittest.mock import patch

from jang_app.services.app_update import (
    ReleaseArtifact,
    UpdateError,
    create_update_plan,
    download_artifact,
    parse_release_manifest,
    verify_authenticode_signature,
)


class _Response(io.BytesIO):
    def __init__(self, data: bytes, status: int = 200) -> None:
        super().__init__(data)
        self.status = status

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class AppUpdateTests(unittest.TestCase):
    def test_parses_components_and_selects_changed_versions(self) -> None:
        payload = b"installer"
        runtime = b"runtime"
        release = parse_release_manifest(
            {
                "schema_version": 2,
                "product": "JJZero Audio",
                "version": "0.3.0",
                "components": [
                    {
                        "id": "application",
                        "version": "0.3.0",
                        "install_mode": "installer",
                        "artifacts": [_artifact("app.exe", payload)],
                    },
                    {
                        "id": "ai-runtime",
                        "version": "2",
                        "install_mode": "extract",
                        "artifacts": [_artifact("runtime.zip", runtime)],
                    },
                ],
            },
            "https://example.test/releases/latest/download/latest.json",
        )

        plan = create_update_plan(
            release,
            current_version="0.2.0",
            runtime_version="1",
        )

        self.assertTrue(plan.application_required)
        self.assertTrue(plan.runtime_required)
        self.assertEqual([item.name for item in plan.artifacts], ["app.exe", "runtime.zip"])
        self.assertEqual(
            release.application.artifacts[0].url,
            "https://example.test/releases/latest/download/app.exe",
        )

    def test_rejects_unsafe_artifact_names(self) -> None:
        data = {
            "schema_version": 2,
            "product": "JJZero Audio",
            "version": "0.3.0",
            "components": [
                {
                    "id": "application",
                    "version": "0.3.0",
                    "install_mode": "installer",
                    "artifacts": [
                        {
                            **_artifact("app.exe", b"app"),
                            "name": "../app.exe",
                        }
                    ],
                }
            ],
        }

        with self.assertRaises(UpdateError):
            parse_release_manifest(data, "https://example.test/latest.json")

    def test_parses_required_authenticode_publisher(self) -> None:
        application = _artifact("app.exe", b"app")
        application["authenticode"] = {
            "required": True,
            "publisher": "JJZero",
        }
        release = parse_release_manifest(
            {
                "schema_version": 2,
                "product": "JJZero Audio",
                "version": "0.3.0",
                "components": [
                    {
                        "id": "application",
                        "version": "0.3.0",
                        "install_mode": "installer",
                        "artifacts": [application],
                    }
                ],
            },
            "https://example.test/latest.json",
        )

        artifact = release.application.artifacts[0]
        self.assertTrue(artifact.signature_required)
        self.assertEqual(artifact.publisher, "JJZero")

    def test_download_resumes_and_verifies_artifact(self) -> None:
        payload = b"verified update payload"
        artifact = ReleaseArtifact(
            "app.exe",
            len(payload),
            hashlib.sha256(payload).hexdigest(),
            "https://example.test/app.exe",
        )
        requests: list[Request] = []

        def opener(request: Request, timeout: float) -> _Response:
            requests.append(request)
            self.assertGreater(timeout, 0)
            return _Response(payload[8:], status=206)

        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            (destination / "app.exe.part").write_bytes(payload[:8])
            progress: list[int] = []

            result = download_artifact(
                artifact,
                destination,
                progress=progress.append,
                opener=opener,
            )

            self.assertEqual(result.read_bytes(), payload)
            self.assertEqual(requests[0].get_header("Range"), "bytes=8-")
            self.assertEqual(progress[-1], 100)

    def test_download_removes_corrupt_partial(self) -> None:
        artifact = ReleaseArtifact(
            "app.exe",
            4,
            hashlib.sha256(b"good").hexdigest(),
            "https://example.test/app.exe",
        )

        def opener(request: Request, timeout: float) -> _Response:
            return _Response(b"bad!", status=200)

        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            with self.assertRaises(UpdateError):
                download_artifact(artifact, destination, opener=opener)
            self.assertFalse((destination / "app.exe.part").exists())

    def test_authenticode_requires_valid_expected_publisher(self) -> None:
        completed = CompletedProcess(
            [],
            0,
            stdout='{"Status":"Valid","Subject":"CN=JJZero Software"}',
            stderr="",
        )
        with patch("jang_app.services.app_update.subprocess.run", return_value=completed):
            self.assertTrue(
                verify_authenticode_signature(Path("installer.exe"), "JJZero Software")
            )
            self.assertFalse(
                verify_authenticode_signature(Path("installer.exe"), "Different Publisher")
            )


def _artifact(name: str, data: bytes) -> dict[str, object]:
    return {
        "name": name,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


if __name__ == "__main__":
    unittest.main()
