from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol
from urllib.error import HTTPError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen

from jang_app.runtime_version import AI_RUNTIME_VERSION
from jang_app.services.command import run_command
from jang_app.services.rvc_runtime_profile import (
    RVC_BASE_RUNTIME_PROFILES,
    RVC_PROFILE_CU118,
    RVC_PROFILE_CPU,
    normalize_rvc_profile,
    rvc_profile_candidates,
    rvc_profile_component_id,
    rvc_profile_requires_overlay,
)
from jang_app.version import __version__


DEFAULT_MANIFEST_URL = (
    "https://github.com/groun519/JJZ-Audio/releases/latest/download/latest.json"
)
MAX_MANIFEST_BYTES = 1024 * 1024
DOWNLOAD_CHUNK_SIZE = 8 * 1024 * 1024
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_FEATURE_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SOURCE_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40,64}$")
_WINDOWS_VERSION_PATTERN = re.compile(
    r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<build>\d+)$"
)
_SUPPORTED_MANIFEST_ARCHITECTURES = {"x64", "arm64"}


class UpdateError(RuntimeError):
    pass


class Response(Protocol):
    status: int

    def read(self, size: int = -1) -> bytes: ...

    def __enter__(self) -> Response: ...

    def __exit__(self, *args: object) -> None: ...


OpenUrl = Callable[[Request, float], Response]
ProgressReporter = Callable[[int], None]


@dataclass(frozen=True)
class ReleaseArtifact:
    name: str
    size: int
    sha256: str
    url: str
    signature_required: bool = False
    publisher: str = ""
    unpacked_size: int = 0
    file_count: int = 0
    certificate_sha256: str = ""


@dataclass(frozen=True)
class ReleaseComponent:
    component_id: str
    version: str
    install_mode: str
    artifacts: tuple[ReleaseArtifact, ...]


@dataclass(frozen=True)
class ReleaseManifest:
    version: str
    components: tuple[ReleaseComponent, ...]
    disabled_features: frozenset[str] = frozenset()
    source_revision: str = ""
    architecture: str = ""
    minimum_windows: str = ""

    def component(self, component_id: str) -> ReleaseComponent | None:
        return next(
            (item for item in self.components if item.component_id == component_id),
            None,
        )

    @property
    def application(self) -> ReleaseComponent:
        component = self.component("application")
        if component is None:
            raise UpdateError("The release manifest has no application component.")
        return component

    @property
    def ai_runtime(self) -> ReleaseComponent | None:
        return self.component("ai-runtime")

    def rvc_runtime_profile(self, profile: str) -> ReleaseComponent | None:
        return self.component(rvc_profile_component_id(profile))


@dataclass(frozen=True)
class UpdatePlan:
    release: ReleaseManifest
    application_required: bool
    runtime_required: bool
    rvc_profile_required: bool = False
    rvc_profile: str = ""
    rvc_preferred_profile: str = ""
    rvc_preferred_version: str = ""
    rvc_fallback_profile: str = ""
    rvc_fallback_reason: str = ""

    @property
    def required(self) -> bool:
        return self.application_required or self.runtime_required or self.rvc_profile_required

    @property
    def rvc_profile_component(self) -> ReleaseComponent | None:
        return self.release.rvc_runtime_profile(self.rvc_profile) if self.rvc_profile else None

    @property
    def rvc_fallback_component(self) -> ReleaseComponent | None:
        return (
            self.release.rvc_runtime_profile(self.rvc_fallback_profile)
            if self.rvc_fallback_profile
            else None
        )

    @property
    def artifacts(self) -> tuple[ReleaseArtifact, ...]:
        selected: list[ReleaseArtifact] = []
        if self.application_required:
            selected.extend(self.release.application.artifacts)
        selected.extend(self.runtime_artifacts)
        return tuple(selected)

    @property
    def runtime_artifacts(self) -> tuple[ReleaseArtifact, ...]:
        selected: list[ReleaseArtifact] = []
        if self.runtime_required and self.release.ai_runtime is not None:
            selected.extend(self.release.ai_runtime.artifacts)
        if self.rvc_profile_required and self.rvc_profile_component is not None:
            selected.extend(self.rvc_profile_component.artifacts)
        return tuple(selected)

    @property
    def fallback_runtime_artifacts(self) -> tuple[ReleaseArtifact, ...]:
        selected: list[ReleaseArtifact] = []
        if self.rvc_profile_required and self.rvc_fallback_component is not None:
            selected.extend(self.rvc_fallback_component.artifacts)
        return tuple(selected)


@dataclass(frozen=True)
class ReleaseManifestCheck:
    release: ReleaseManifest | None
    etag: str = ""
    last_modified: str = ""
    not_modified: bool = False


def fetch_release_manifest(
    manifest_url: str = DEFAULT_MANIFEST_URL,
    *,
    timeout: float = 10.0,
    opener: OpenUrl | None = None,
) -> ReleaseManifest:
    request = Request(
        manifest_url,
        headers={"Accept": "application/json", "User-Agent": f"JJZero-Audio/{__version__}"},
    )
    open_request = opener or _open_url
    try:
        with open_request(request, timeout) as response:
            payload = response.read(MAX_MANIFEST_BYTES + 1)
    except OSError as exc:
        raise UpdateError(f"Could not retrieve the release manifest: {exc}") from exc
    if len(payload) > MAX_MANIFEST_BYTES:
        raise UpdateError("The release manifest is too large.")
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("The release manifest is not valid JSON.") from exc
    return parse_release_manifest(data, manifest_url)


def fetch_release_manifest_if_changed(
    manifest_url: str = DEFAULT_MANIFEST_URL,
    *,
    etag: str = "",
    last_modified: str = "",
    timeout: float = 10.0,
    opener: OpenUrl | None = None,
) -> ReleaseManifestCheck:
    headers = {
        "Accept": "application/json",
        "User-Agent": f"JJZero-Audio/{__version__}",
    }
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    request = Request(manifest_url, headers=headers)
    open_request = opener or _open_url
    try:
        with open_request(request, timeout) as response:
            response_etag = _response_header(response, "ETag") or etag
            response_modified = _response_header(response, "Last-Modified") or last_modified
            if getattr(response, "status", 200) == 304:
                return ReleaseManifestCheck(
                    None,
                    response_etag,
                    response_modified,
                    not_modified=True,
                )
            payload = response.read(MAX_MANIFEST_BYTES + 1)
    except HTTPError as exc:
        if exc.code == 304:
            return ReleaseManifestCheck(
                None,
                _response_header(exc, "ETag") or etag,
                _response_header(exc, "Last-Modified") or last_modified,
                not_modified=True,
            )
        raise UpdateError(f"Could not retrieve the release manifest: {exc}") from exc
    except OSError as exc:
        raise UpdateError(f"Could not retrieve the release manifest: {exc}") from exc
    if len(payload) > MAX_MANIFEST_BYTES:
        raise UpdateError("The release manifest is too large.")
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("The release manifest is not valid JSON.") from exc
    return ReleaseManifestCheck(
        parse_release_manifest(data, manifest_url),
        response_etag,
        response_modified,
    )


def parse_release_manifest(data: object, manifest_url: str) -> ReleaseManifest:
    if not isinstance(data, Mapping):
        raise UpdateError("The release manifest root must be an object.")
    if data.get("product") != "JJZero Audio":
        raise UpdateError("The release manifest product does not match JJZero Audio.")
    version = _required_text(data, "version")
    _version_tuple(version)
    schema_version = data.get("schema_version")
    if schema_version == 1:
        components = (_parse_legacy_application(data, manifest_url, version),)
    elif schema_version == 2:
        raw_components = data.get("components")
        if not isinstance(raw_components, list) or not raw_components:
            raise UpdateError("The release manifest has no components.")
        components = tuple(
            _parse_component(item, manifest_url) for item in raw_components
        )
    else:
        raise UpdateError(f"Unsupported release manifest schema: {schema_version!r}")
    if len({component.component_id for component in components}) != len(components):
        raise UpdateError("The release manifest contains duplicate components.")
    application = next(
        (component for component in components if component.component_id == "application"),
        None,
    )
    if application is not None and application.version != version:
        raise UpdateError(
            "The application component version does not match the release version."
        )
    artifact_names = [
        artifact.name.casefold()
        for component in components
        for artifact in component.artifacts
    ]
    if len(set(artifact_names)) != len(artifact_names):
        raise UpdateError("Release artifact names must be unique across components.")
    disabled_features = _parse_disabled_features(data.get("disabled_features"))
    source_revision = _parse_source_revision(data.get("source_revision"))
    architecture = _parse_manifest_architecture(data.get("architecture"))
    minimum_windows = _parse_minimum_windows(data.get("minimum_windows"))
    release = ReleaseManifest(
        version,
        components,
        disabled_features,
        source_revision,
        architecture,
        minimum_windows,
    )
    release.application
    _require_release_platform_compatibility(release)
    return release


def create_update_plan(
    release: ReleaseManifest,
    *,
    current_version: str = __version__,
    runtime_version: str | None = AI_RUNTIME_VERSION,
    runtime_ready: bool = True,
    desired_rvc_profile: str = "",
    installed_rvc_profile: str = "",
    installed_rvc_profile_version: str = "",
    installed_rvc_preferred_profile: str = "",
    installed_rvc_preferred_version: str = "",
    installed_rvc_failed_fallback_profile: str = "",
    installed_rvc_failed_fallback_version: str = "",
) -> UpdatePlan:
    _require_release_platform_compatibility(release)
    application_required = _version_tuple(release.version) > _version_tuple(current_version)
    if application_required:
        require_trusted_application_artifacts(release.application)
    runtime = release.ai_runtime
    runtime_required = runtime is not None and (
        not runtime_ready
        or _component_upgrade_required(runtime.version, runtime_version or "")
    )
    preferred_profile = (
        normalize_rvc_profile(desired_rvc_profile) if desired_rvc_profile.strip() else ""
    )
    preferred_component = (
        release.rvc_runtime_profile(preferred_profile) if preferred_profile else None
    )
    preferred_version = preferred_component.version if preferred_component is not None else ""
    preferred_quarantined = bool(
        preferred_profile
        and installed_rvc_profile
        and normalize_rvc_profile(installed_rvc_profile) != preferred_profile
        and normalize_rvc_profile(installed_rvc_preferred_profile) == preferred_profile
        and installed_rvc_preferred_version == preferred_version
        and preferred_version
    )
    skipped_profiles = {preferred_profile} if preferred_quarantined else set()
    failed_fallback_component = (
        release.rvc_runtime_profile(installed_rvc_failed_fallback_profile)
        if installed_rvc_failed_fallback_profile
        else None
    )
    if (
        failed_fallback_component is not None
        and failed_fallback_component.version == installed_rvc_failed_fallback_version
    ):
        skipped_profiles.add(normalize_rvc_profile(installed_rvc_failed_fallback_profile))
    selected_profile, fallback_profile = select_release_rvc_profiles(
        release,
        preferred_profile,
        skipped_profiles=frozenset(skipped_profiles),
    )
    profile_component = (
        release.rvc_runtime_profile(selected_profile)
        if selected_profile
        else None
    )
    legacy_base_selected = bool(
        selected_profile in RVC_BASE_RUNTIME_PROFILES
        and profile_component is None
    )
    base_fallback_recorded = bool(
        legacy_base_selected
        and installed_rvc_profile
        and normalize_rvc_profile(installed_rvc_profile) in RVC_BASE_RUNTIME_PROFILES
        and normalize_rvc_profile(installed_rvc_preferred_profile) == preferred_profile
        and installed_rvc_preferred_version == preferred_version
    )
    if (
        legacy_base_selected
        and installed_rvc_profile
        and normalize_rvc_profile(installed_rvc_profile) not in RVC_BASE_RUNTIME_PROFILES
        and runtime is not None
    ):
        runtime_required = True
    base_fallback_required = bool(
        preferred_profile
        and legacy_base_selected
        and selected_profile != preferred_profile
        and not base_fallback_recorded
    )
    profile_required = base_fallback_required or (
        profile_component is not None
        and (
            normalize_rvc_profile(installed_rvc_profile) != selected_profile
            or _component_upgrade_required(
                profile_component.version,
                installed_rvc_profile_version,
            )
            or normalize_rvc_profile(installed_rvc_preferred_profile or installed_rvc_profile)
            != preferred_profile
            or _component_upgrade_required(
                preferred_version,
                installed_rvc_preferred_version,
            )
        )
    )
    fallback_reason = ""
    cpu_uses_cu118 = (
        preferred_profile == RVC_PROFILE_CPU
        and selected_profile == RVC_PROFILE_CU118
    )
    if (
        selected_profile
        and preferred_profile
        and selected_profile != preferred_profile
        and not cpu_uses_cu118
    ):
        fallback_reason = (
            f"RVC {preferred_profile} activation previously failed for version {preferred_version}."
            if preferred_quarantined
            else f"RVC {preferred_profile} is unavailable in this release."
        )
    return UpdatePlan(
        release=release,
        application_required=application_required,
        runtime_required=runtime_required,
        rvc_profile_required=profile_required,
        rvc_profile=selected_profile,
        rvc_preferred_profile=preferred_profile,
        rvc_preferred_version=preferred_version,
        rvc_fallback_profile=fallback_profile,
        rvc_fallback_reason=fallback_reason,
    )


def select_release_rvc_profiles(
    release: ReleaseManifest,
    preferred_profile: str,
    *,
    skipped_profiles: frozenset[str] = frozenset(),
) -> tuple[str, str]:
    candidates = list(rvc_profile_candidates(preferred_profile or RVC_PROFILE_CPU))
    candidates = [profile for profile in candidates if profile not in skipped_profiles]
    available = [
        profile
        for profile in candidates
        if not rvc_profile_requires_overlay(profile)
        or release.rvc_runtime_profile(profile) is not None
    ]
    if not available:
        return RVC_PROFILE_CPU, ""
    selected = available[0]
    fallback = available[1] if len(available) > 1 else ""
    return selected, fallback


def download_artifact(
    artifact: ReleaseArtifact,
    destination_dir: Path,
    *,
    progress: ProgressReporter | None = None,
    timeout: float = 60.0,
    opener: OpenUrl | None = None,
) -> Path:
    destination = destination_dir.expanduser().resolve() / artifact.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and _artifact_ready(destination, artifact):
        _report(progress, 100)
        return destination

    partial = destination.with_suffix(f"{destination.suffix}.part")
    offset = partial.stat().st_size if partial.is_file() else 0
    if offset == artifact.size:
        if _artifact_ready(partial, artifact):
            os.replace(partial, destination)
            _report(progress, 100)
            return destination
        partial.unlink()
        offset = 0
    if offset > artifact.size:
        partial.unlink()
        offset = 0
    fresh_candidate = partial.with_suffix(f"{partial.suffix}.fresh")
    fresh_candidate.unlink(missing_ok=True)
    download_path = partial
    appended_to_partial = False
    open_request = opener or _open_url
    request_offset = offset
    try:
        for attempt in range(2):
            request = Request(
                artifact.url,
                headers={
                    "User-Agent": f"JJZero-Audio/{__version__}",
                    **({"Range": f"bytes={request_offset}-"} if request_offset else {}),
                },
            )
            with open_request(request, timeout) as response:
                status = getattr(response, "status", 200)
                if request_offset:
                    if status == 206 and _valid_content_range(
                        response,
                        request_offset,
                        artifact.size,
                    ):
                        download_path = partial
                        appended_to_partial = True
                        _write_download(
                            response,
                            download_path,
                            artifact.size,
                            request_offset,
                            True,
                            progress,
                        )
                        break
                    if status == 200:
                        download_path = fresh_candidate
                        _write_download(
                            response,
                            download_path,
                            artifact.size,
                            0,
                            False,
                            progress,
                        )
                        break
                    if attempt == 0:
                        request_offset = 0
                        continue
                    raise UpdateError(
                        f"Download server returned an invalid range for {artifact.name}."
                    )
                if status == 206 and not _valid_content_range(
                    response,
                    0,
                    artifact.size,
                ):
                    raise UpdateError(
                        f"Download server returned an invalid range for {artifact.name}."
                    )
                _write_download(
                    response,
                    fresh_candidate if offset else partial,
                    artifact.size,
                    0,
                    False,
                    progress,
                )
                download_path = fresh_candidate if offset else partial
                break
    except OSError as exc:
        if appended_to_partial:
            _truncate_partial(partial, offset)
        fresh_candidate.unlink(missing_ok=True)
        raise UpdateError(f"Could not download {artifact.name}: {exc}") from exc
    except UpdateError:
        if appended_to_partial:
            _truncate_partial(partial, offset)
        fresh_candidate.unlink(missing_ok=True)
        raise

    if not _artifact_ready(download_path, artifact):
        if download_path == partial:
            if offset:
                _truncate_partial(partial, offset)
            else:
                partial.unlink(missing_ok=True)
        else:
            fresh_candidate.unlink(missing_ok=True)
        raise UpdateError(f"Downloaded artifact verification failed: {artifact.name}")
    os.replace(download_path, destination)
    if download_path != partial:
        partial.unlink(missing_ok=True)
    _report(progress, 100)
    return destination


def verify_artifact(path: Path, artifact: ReleaseArtifact) -> bool:
    resolved = path.expanduser().resolve()
    return (
        resolved.is_file()
        and resolved.stat().st_size == artifact.size
        and _sha256(resolved) == artifact.sha256
    )


def discard_cached_artifacts(paths: tuple[Path, ...], cache_root: Path) -> None:
    """Best-effort cleanup for verified packages after a successful install."""
    root = cache_root.expanduser().resolve()
    for path in paths:
        candidate = path.expanduser().resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            continue
        parent = candidate.parent
        while parent != root and root in parent.parents:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent


def verify_authenticode_signature(
    path: Path,
    publisher: str = "",
    certificate_sha256: str = "",
) -> bool:
    environment = os.environ.copy()
    environment["JJZERO_VERIFY_SIGNATURE_PATH"] = str(path.expanduser().resolve())
    command = (
        "$signature = Get-AuthenticodeSignature -LiteralPath "
        "$env:JJZERO_VERIFY_SIGNATURE_PATH; "
        "$sha = [Security.Cryptography.SHA256]::Create(); "
        "$certificateSha256 = if ($signature.SignerCertificate) { "
        "(($sha.ComputeHash($signature.SignerCertificate.RawData) | "
        "ForEach-Object { $_.ToString('x2') }) -join '') } else { '' }; "
        "[pscustomobject]@{Status=[string]$signature.Status; "
        "Subject=[string]$signature.SignerCertificate.Subject; "
        "SimpleName=[string]$signature.SignerCertificate.GetNameInfo('SimpleName',$false); "
        "CertificateSha256=$certificateSha256} "
        "| ConvertTo-Json -Compress"
    )
    completed = run_command(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        env=environment,
        timeout_seconds=30,
    )
    try:
        data = json.loads(completed.stdout.strip())
    except json.JSONDecodeError:
        return False
    subject = str(data.get("Subject", "")) if isinstance(data, Mapping) else ""
    simple_name = str(data.get("SimpleName", "")) if isinstance(data, Mapping) else ""
    expected = publisher.strip().casefold()
    expected_certificate = certificate_sha256.strip().casefold()
    actual_certificate = (
        str(data.get("CertificateSha256", "")).strip().casefold()
        if isinstance(data, Mapping)
        else ""
    )
    return (
        completed.returncode == 0
        and isinstance(data, Mapping)
        and data.get("Status") == "Valid"
        and (not expected_certificate or actual_certificate == expected_certificate)
        and (
            not expected
            or expected == simple_name.strip().casefold()
            or expected == subject.strip().casefold()
        )
    )


def _parse_component(data: object, manifest_url: str) -> ReleaseComponent:
    if not isinstance(data, Mapping):
        raise UpdateError("A release component must be an object.")
    component_id = _required_text(data, "id")
    version = _required_text(data, "version")
    install_mode = _required_text(data, "install_mode")
    if install_mode not in {"installer", "extract"}:
        raise UpdateError(f"Unsupported install mode: {install_mode}")
    artifacts = _parse_artifacts(data.get("artifacts"), manifest_url)
    return ReleaseComponent(component_id, version, install_mode, artifacts)


def _parse_disabled_features(data: object) -> frozenset[str]:
    if data is None:
        return frozenset()
    if not isinstance(data, list):
        raise UpdateError("The disabled feature list must be an array.")
    features: set[str] = set()
    for value in data:
        if not isinstance(value, str) or _FEATURE_NAME_PATTERN.fullmatch(value) is None:
            raise UpdateError(f"Invalid disabled feature name: {value!r}")
        features.add(value)
    return frozenset(features)


def _parse_source_revision(data: object) -> str:
    if data is None:
        return ""
    if not isinstance(data, str):
        raise UpdateError("Invalid release source revision.")
    revision = data.strip().lower()
    if _SOURCE_REVISION_PATTERN.fullmatch(revision) is None:
        raise UpdateError("Invalid release source revision.")
    return revision


def _parse_manifest_architecture(data: object) -> str:
    if data is None:
        return ""
    if not isinstance(data, str):
        raise UpdateError("Invalid release architecture.")
    architecture = data.strip().casefold()
    if architecture not in _SUPPORTED_MANIFEST_ARCHITECTURES:
        raise UpdateError(f"Unsupported release architecture: {architecture or data!r}")
    return architecture


def _parse_minimum_windows(data: object) -> str:
    if data is None:
        return ""
    if not isinstance(data, str):
        raise UpdateError("Invalid minimum Windows version.")
    version = data.strip()
    if _WINDOWS_VERSION_PATTERN.fullmatch(version) is None:
        raise UpdateError(f"Invalid minimum Windows version: {version!r}")
    return version


def _require_release_platform_compatibility(release: ReleaseManifest) -> None:
    host_architecture = _host_architecture()
    if (
        release.architecture
        and host_architecture
        and release.architecture != host_architecture
    ):
        raise UpdateError(
            "This release requires "
            f"{release.architecture}, but this PC uses {host_architecture}."
        )
    required_windows = _windows_version_tuple(release.minimum_windows)
    host_windows = _host_windows_version()
    if required_windows and host_windows and host_windows < required_windows:
        raise UpdateError(
            "This release requires Windows "
            f"{release.minimum_windows} or newer."
        )


def _host_architecture() -> str:
    if os.name != "nt":
        return ""
    machine = platform.machine().strip().casefold()
    if machine in {"amd64", "x86_64"}:
        return "x64"
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    return machine


def _host_windows_version() -> tuple[int, int, int] | None:
    if os.name != "nt":
        return None
    get_version = getattr(sys, "getwindowsversion", None)
    if get_version is None:
        return None
    version = get_version()
    return int(version.major), int(version.minor), int(version.build)


def _windows_version_tuple(value: str) -> tuple[int, int, int] | None:
    if not value:
        return None
    match = _WINDOWS_VERSION_PATTERN.fullmatch(value)
    if match is None:
        return None
    return tuple(int(match.group(name)) for name in ("major", "minor", "build"))


def _parse_legacy_application(
    data: Mapping[object, object],
    manifest_url: str,
    version: str,
) -> ReleaseComponent:
    return ReleaseComponent(
        "application",
        version,
        "installer",
        _parse_artifacts(data.get("artifacts"), manifest_url),
    )


def _parse_artifacts(data: object, manifest_url: str) -> tuple[ReleaseArtifact, ...]:
    if not isinstance(data, list) or not data:
        raise UpdateError("A release component has no artifacts.")
    artifacts = tuple(_parse_artifact(item, manifest_url) for item in data)
    if len({artifact.name for artifact in artifacts}) != len(artifacts):
        raise UpdateError("A release component contains duplicate artifacts.")
    return artifacts


def _parse_artifact(data: object, manifest_url: str) -> ReleaseArtifact:
    if not isinstance(data, Mapping):
        raise UpdateError("A release artifact must be an object.")
    name = _required_text(data, "name")
    if Path(name).name != name or name in {".", ".."}:
        raise UpdateError(f"Unsafe release artifact name: {name!r}")
    size = data.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise UpdateError(f"Invalid release artifact size: {name}")
    sha256 = _required_text(data, "sha256").lower()
    if _SHA256_PATTERN.fullmatch(sha256) is None:
        raise UpdateError(f"Invalid release artifact checksum: {name}")
    url = data.get("url")
    if url is None:
        url = urljoin(manifest_url, quote(name))
    if not isinstance(url, str) or not url.startswith("https://"):
        raise UpdateError(f"Invalid release artifact URL: {name}")
    signature_required, publisher, certificate_sha256 = _parse_authenticode(
        data.get("authenticode"),
        name,
    )
    unpacked_size = _optional_positive_int(data, "unpacked_size", name)
    file_count = _optional_positive_int(data, "file_count", name)
    return ReleaseArtifact(
        name,
        size,
        sha256,
        url,
        signature_required,
        publisher,
        unpacked_size,
        file_count,
        certificate_sha256,
    )


def _optional_positive_int(
    data: Mapping[object, object],
    key: str,
    name: str,
) -> int:
    value = data.get(key)
    if value is None:
        return 0
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise UpdateError(f"Invalid release artifact {key}: {name}")
    return value


def _parse_authenticode(data: object, name: str) -> tuple[bool, str, str]:
    if data is None:
        return False, "", ""
    if not isinstance(data, Mapping):
        raise UpdateError(f"Invalid Authenticode metadata: {name}")
    required = data.get("required")
    publisher = data.get("publisher")
    certificate_sha256 = data.get("certificate_sha256")
    if (
        required is not True
        or not isinstance(publisher, str)
        or not publisher.strip()
        or not isinstance(certificate_sha256, str)
        or _SHA256_PATTERN.fullmatch(certificate_sha256.strip().casefold()) is None
    ):
        raise UpdateError(f"Incomplete Authenticode metadata: {name}")
    return True, publisher.strip(), certificate_sha256.strip().casefold()


def require_trusted_application_artifacts(component: ReleaseComponent) -> None:
    for artifact in component.artifacts:
        if not (
            artifact.signature_required
            and artifact.publisher.strip()
            and _SHA256_PATTERN.fullmatch(artifact.certificate_sha256.casefold())
        ):
            raise UpdateError(
                "Application updates require a pinned Authenticode certificate."
            )


def _required_text(data: Mapping[object, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise UpdateError(f"Missing release manifest field: {key}")
    return value.strip()


def _version_tuple(version: str) -> tuple[int, int, int]:
    parts = version.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise UpdateError(f"Invalid semantic version: {version!r}")
    return tuple(int(part) for part in parts)  # type: ignore[return-value]


def _component_upgrade_required(target: str, installed: str) -> bool:
    if not target or target == installed:
        return False
    if not installed:
        return True
    target_parts = _numeric_version_parts(target)
    installed_parts = _numeric_version_parts(installed)
    if target_parts is None or installed_parts is None:
        return False
    width = max(len(target_parts), len(installed_parts))
    return target_parts + (0,) * (width - len(target_parts)) > (
        installed_parts + (0,) * (width - len(installed_parts))
    )


def _numeric_version_parts(value: str) -> tuple[int, ...] | None:
    parts = value.strip().split(".")
    if not parts or any(not part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def _write_download(
    response: BinaryIO,
    path: Path,
    expected_size: int,
    offset: int,
    append: bool,
    progress: ProgressReporter | None,
) -> None:
    downloaded = offset
    with path.open("ab" if append else "wb") as target:
        while chunk := response.read(DOWNLOAD_CHUNK_SIZE):
            if downloaded + len(chunk) > expected_size:
                raise UpdateError(
                    f"Downloaded artifact exceeds its declared size: {path.name}"
                )
            target.write(chunk)
            downloaded += len(chunk)
            _report(progress, int(downloaded * 100 / expected_size))


def _truncate_partial(path: Path, size: int) -> None:
    try:
        with path.open("r+b") as target:
            target.truncate(size)
    except OSError:
        # Keep the primary download error. A later retry still verifies the file
        # length and hash before using whatever Windows allowed us to preserve.
        pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(DOWNLOAD_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_ready(path: Path, artifact: ReleaseArtifact) -> bool:
    return verify_artifact(path, artifact) and (
        not artifact.signature_required
        or verify_authenticode_signature(
            path,
            artifact.publisher,
            artifact.certificate_sha256,
        )
    )


def _report(progress: ProgressReporter | None, value: int) -> None:
    if progress is not None:
        progress(max(0, min(value, 100)))


def _response_header(response: object, name: str) -> str:
    headers = getattr(response, "headers", None)
    get_header = getattr(headers, "get", None)
    if not callable(get_header):
        return ""
    value = get_header(name, "")
    return str(value).strip() if value else ""


def _valid_content_range(
    response: object,
    expected_start: int,
    expected_total: int,
) -> bool:
    value = _response_header(response, "Content-Range")
    match = re.fullmatch(r"bytes\s+(\d+)-(\d+)/(\d+)", value, re.IGNORECASE)
    if match is None:
        return False
    start, end, total = (int(part) for part in match.groups())
    return (
        start == expected_start
        and total == expected_total
        and start <= end < total
    )


def _open_url(request: Request, timeout: float) -> Response:
    return urlopen(request, timeout=timeout)  # type: ignore[return-value]
