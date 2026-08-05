from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from urllib.request import Request
from unittest.mock import patch

from jang_app.services.app_update import (
    ReleaseArtifact,
    ReleaseComponent,
    ReleaseManifest,
    UpdateError,
    create_update_plan,
    download_artifact,
    fetch_release_manifest_if_changed,
    parse_release_manifest,
    verify_authenticode_signature,
)


class _Response(io.BytesIO):
    def __init__(
        self,
        data: bytes,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(data)
        self.status = status
        self.headers = headers or {}

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

    def test_selects_blackwell_runtime_profile_component(self) -> None:
        release = parse_release_manifest(
            {
                "schema_version": 2,
                "product": "JJZero Audio",
                "version": "0.2.2",
                "components": [
                    {
                        "id": "application",
                        "version": "0.2.2",
                        "install_mode": "installer",
                        "artifacts": [_artifact("app.exe", b"app")],
                    },
                    {
                        "id": "rvc-runtime-cu128",
                        "version": "1",
                        "install_mode": "extract",
                        "artifacts": [_artifact("rvc-cu128.zip", b"runtime")],
                    },
                ],
            },
            "https://example.test/latest.json",
        )

        plan = create_update_plan(
            release,
            current_version="0.2.2",
            desired_rvc_profile="cu128",
            installed_rvc_profile="cu118",
        )

        self.assertFalse(plan.application_required)
        self.assertTrue(plan.rvc_profile_required)
        self.assertEqual([item.name for item in plan.artifacts], ["rvc-cu128.zip"])

    def test_reinstalls_base_runtime_when_gpu_changes_back_to_cu118(self) -> None:
        release = parse_release_manifest(
            {
                "schema_version": 2,
                "product": "JJZero Audio",
                "version": "0.2.2",
                "components": [
                    {
                        "id": "application",
                        "version": "0.2.2",
                        "install_mode": "installer",
                        "artifacts": [_artifact("app.exe", b"app")],
                    },
                    {
                        "id": "ai-runtime",
                        "version": "1",
                        "install_mode": "extract",
                        "artifacts": [_artifact("runtime.zip", b"runtime")],
                    },
                ],
            },
            "https://example.test/latest.json",
        )

        plan = create_update_plan(
            release,
            current_version="0.2.2",
            runtime_version="1",
            desired_rvc_profile="cu118",
            installed_rvc_profile="cu128",
        )

        self.assertTrue(plan.runtime_required)
        self.assertFalse(plan.rvc_profile_required)

    def test_selects_directml_profile_for_an_existing_amd_install(self) -> None:
        release = parse_release_manifest(
            {
                "schema_version": 2,
                "product": "JJZero Audio",
                "version": "0.2.2",
                "components": [
                    {
                        "id": "application",
                        "version": "0.2.2",
                        "install_mode": "installer",
                        "artifacts": [_artifact("app.exe", b"app")],
                    },
                    {
                        "id": "rvc-runtime-directml",
                        "version": "1",
                        "install_mode": "extract",
                        "artifacts": [_artifact("rvc-directml.zip", b"runtime")],
                    },
                ],
            },
            "https://example.test/latest.json",
        )

        plan = create_update_plan(
            release,
            current_version="0.2.2",
            desired_rvc_profile="directml",
            installed_rvc_profile="cu118",
        )

        self.assertTrue(plan.rvc_profile_required)
        self.assertEqual(plan.rvc_profile, "directml")

    def test_reinstalls_base_runtime_when_accelerator_is_removed(self) -> None:
        release = parse_release_manifest(
            {
                "schema_version": 2,
                "product": "JJZero Audio",
                "version": "0.2.2",
                "components": [
                    {
                        "id": "application",
                        "version": "0.2.2",
                        "install_mode": "installer",
                        "artifacts": [_artifact("app.exe", b"app")],
                    },
                    {
                        "id": "ai-runtime",
                        "version": "1",
                        "install_mode": "extract",
                        "artifacts": [_artifact("runtime.zip", b"runtime")],
                    },
                ],
            },
            "https://example.test/latest.json",
        )

        plan = create_update_plan(
            release,
            current_version="0.2.2",
            runtime_version="1",
            desired_rvc_profile="cpu",
            installed_rvc_profile="directml",
        )

        self.assertTrue(plan.runtime_required)

    def test_supported_amd_downloads_rocm_and_directml_fallback_together(self) -> None:
        release = _amd_release()

        plan = create_update_plan(
            release,
            current_version="0.2.2",
            runtime_version="2",
            desired_rvc_profile="rocm-win",
            installed_rvc_profile="cu118",
        )

        self.assertEqual(plan.rvc_profile, "rocm-win")
        self.assertEqual(plan.rvc_fallback_profile, "directml")
        self.assertTrue(plan.runtime_required)
        self.assertEqual(
            [artifact.name for artifact in plan.artifacts],
            ["runtime.zip", "rocm.zip", "directml.zip"],
        )

    def test_failed_rocm_version_is_quarantined_until_a_new_profile_version(self) -> None:
        release = _amd_release()

        quarantined = create_update_plan(
            release,
            current_version="0.2.2",
            runtime_version="2",
            desired_rvc_profile="rocm-win",
            installed_rvc_profile="directml",
            installed_rvc_profile_version="1",
            installed_rvc_preferred_profile="rocm-win",
            installed_rvc_preferred_version="1",
        )

        self.assertEqual(quarantined.rvc_profile, "directml")
        self.assertFalse(quarantined.rvc_profile_required)

        upgraded_components = tuple(
            ReleaseComponent(component.component_id, "2", component.install_mode, component.artifacts)
            if component.component_id == "rvc-runtime-rocm-win"
            else component
            for component in release.components
        )
        retry = create_update_plan(
            ReleaseManifest(release.version, upgraded_components),
            current_version="0.2.2",
            runtime_version="2",
            desired_rvc_profile="rocm-win",
            installed_rvc_profile="directml",
            installed_rvc_profile_version="1",
            installed_rvc_preferred_profile="rocm-win",
            installed_rvc_preferred_version="1",
        )

        self.assertEqual(retry.rvc_profile, "rocm-win")
        self.assertTrue(retry.rvc_profile_required)

    def test_missing_rocm_component_selects_directml_without_blocking_install(self) -> None:
        release = _amd_release(include_rocm=False)

        plan = create_update_plan(
            release,
            current_version="0.2.2",
            runtime_version="2",
            desired_rvc_profile="rocm-win",
            installed_rvc_profile="cu118",
        )

        self.assertEqual(plan.rvc_profile, "directml")
        self.assertEqual(plan.rvc_preferred_profile, "rocm-win")
        self.assertIn("unavailable", plan.rvc_fallback_reason)

    def test_missing_amd_profiles_records_cpu_fallback_once(self) -> None:
        release = ReleaseManifest(
            "0.2.2",
            (
                ReleaseComponent(
                    "application",
                    "0.2.2",
                    "installer",
                    (
                        ReleaseArtifact(
                            "app.exe",
                            1,
                            "a" * 64,
                            "https://example.test/app.exe",
                        ),
                    ),
                ),
                ReleaseComponent(
                    "ai-runtime",
                    "2",
                    "extract",
                    (
                        ReleaseArtifact(
                            "runtime.zip",
                            1,
                            "b" * 64,
                            "https://example.test/runtime.zip",
                        ),
                    ),
                ),
            ),
        )

        first = create_update_plan(
            release,
            current_version="0.2.2",
            runtime_version="2",
            desired_rvc_profile="rocm-win",
            installed_rvc_profile="cu118",
            installed_rvc_profile_version="2",
        )
        recorded = create_update_plan(
            release,
            current_version="0.2.2",
            runtime_version="2",
            desired_rvc_profile="rocm-win",
            installed_rvc_profile="cpu",
            installed_rvc_profile_version="2",
            installed_rvc_preferred_profile="rocm-win",
            installed_rvc_preferred_version="",
        )

        self.assertTrue(first.rvc_profile_required)
        self.assertFalse(first.runtime_required)
        self.assertEqual(first.rvc_profile, "cpu")
        self.assertFalse(recorded.required)

    def test_cpu_fallback_waits_for_a_new_directml_version_before_retrying(self) -> None:
        release = _amd_release()

        stable_cpu = create_update_plan(
            release,
            current_version="0.2.2",
            runtime_version="2",
            desired_rvc_profile="rocm-win",
            installed_rvc_profile="cpu",
            installed_rvc_profile_version="2",
            installed_rvc_preferred_profile="rocm-win",
            installed_rvc_preferred_version="1",
            installed_rvc_failed_fallback_profile="directml",
            installed_rvc_failed_fallback_version="1",
        )

        self.assertEqual(stable_cpu.rvc_profile, "cpu")
        self.assertFalse(stable_cpu.required)

        upgraded_components = tuple(
            ReleaseComponent(component.component_id, "2", component.install_mode, component.artifacts)
            if component.component_id == "rvc-runtime-directml"
            else component
            for component in release.components
        )
        retry = create_update_plan(
            ReleaseManifest(release.version, upgraded_components),
            current_version="0.2.2",
            runtime_version="2",
            desired_rvc_profile="rocm-win",
            installed_rvc_profile="cpu",
            installed_rvc_profile_version="2",
            installed_rvc_preferred_profile="rocm-win",
            installed_rvc_preferred_version="1",
            installed_rvc_failed_fallback_profile="directml",
            installed_rvc_failed_fallback_version="1",
        )

        self.assertEqual(retry.rvc_profile, "directml")
        self.assertTrue(retry.rvc_profile_required)

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

    def test_conditional_manifest_check_reuses_http_cache_validators(self) -> None:
        payload = json.dumps(
            {
                "schema_version": 2,
                "product": "JJZero Audio",
                "version": "0.2.2",
                "components": [
                    {
                        "id": "application",
                        "version": "0.2.2",
                        "install_mode": "installer",
                        "artifacts": [_artifact("app.exe", b"app")],
                    }
                ],
            }
        ).encode("utf-8")
        requests: list[Request] = []

        def opener(request: Request, timeout: float) -> _Response:
            requests.append(request)
            if len(requests) == 1:
                return _Response(
                    payload,
                    headers={
                        "ETag": '"release-022"',
                        "Last-Modified": "Wed, 05 Aug 2026 13:00:00 GMT",
                    },
                )
            return _Response(b"", status=304)

        first = fetch_release_manifest_if_changed(
            "https://example.test/latest.json",
            opener=opener,
        )
        second = fetch_release_manifest_if_changed(
            "https://example.test/latest.json",
            etag=first.etag,
            last_modified=first.last_modified,
            opener=opener,
        )

        request_headers = {key.lower(): value for key, value in requests[1].header_items()}
        self.assertEqual(first.release.version if first.release else "", "0.2.2")
        self.assertEqual(first.etag, '"release-022"')
        self.assertTrue(second.not_modified)
        self.assertIsNone(second.release)
        self.assertEqual(request_headers["if-none-match"], '"release-022"')
        self.assertEqual(
            request_headers["if-modified-since"],
            "Wed, 05 Aug 2026 13:00:00 GMT",
        )

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


def _amd_release(*, include_rocm: bool = True) -> ReleaseManifest:
    def artifact(name: str) -> ReleaseArtifact:
        return ReleaseArtifact(name, 1, "a" * 64, f"https://example.test/{name}")

    components = [
        ReleaseComponent("application", "0.2.2", "installer", (artifact("app.exe"),)),
        ReleaseComponent("ai-runtime", "2", "extract", (artifact("runtime.zip"),)),
        ReleaseComponent(
            "rvc-runtime-directml",
            "1",
            "extract",
            (artifact("directml.zip"),),
        ),
    ]
    if include_rocm:
        components.append(
            ReleaseComponent(
                "rvc-runtime-rocm-win",
                "1",
                "extract",
                (artifact("rocm.zip"),),
            )
        )
    return ReleaseManifest("0.2.2", tuple(components))


if __name__ == "__main__":
    unittest.main()
