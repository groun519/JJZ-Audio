from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen

from jang_app.runtime_version import AI_RUNTIME_VERSION
from jang_app.version import __version__


DEFAULT_MANIFEST_URL = (
    "https://github.com/groun519/Jang/releases/latest/download/latest.json"
)
MAX_MANIFEST_BYTES = 1024 * 1024
DOWNLOAD_CHUNK_SIZE = 8 * 1024 * 1024
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


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


@dataclass(frozen=True)
class UpdatePlan:
    release: ReleaseManifest
    application_required: bool
    runtime_required: bool

    @property
    def required(self) -> bool:
        return self.application_required or self.runtime_required

    @property
    def artifacts(self) -> tuple[ReleaseArtifact, ...]:
        selected: list[ReleaseArtifact] = []
        if self.application_required:
            selected.extend(self.release.application.artifacts)
        if self.runtime_required and self.release.ai_runtime is not None:
            selected.extend(self.release.ai_runtime.artifacts)
        return tuple(selected)


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
    release = ReleaseManifest(version, components)
    release.application
    return release


def create_update_plan(
    release: ReleaseManifest,
    *,
    current_version: str = __version__,
    runtime_version: str | None = AI_RUNTIME_VERSION,
    runtime_ready: bool = True,
) -> UpdatePlan:
    application_required = _version_tuple(release.version) > _version_tuple(current_version)
    runtime = release.ai_runtime
    runtime_required = runtime is not None and (
        not runtime_ready or runtime_version != runtime.version
    )
    return UpdatePlan(release, application_required, runtime_required)


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
    if offset > artifact.size:
        partial.unlink()
        offset = 0
    request = Request(
        artifact.url,
        headers={
            "User-Agent": f"JJZero-Audio/{__version__}",
            **({"Range": f"bytes={offset}-"} if offset else {}),
        },
    )
    open_request = opener or _open_url
    try:
        with open_request(request, timeout) as response:
            append = offset > 0 and getattr(response, "status", 200) == 206
            if offset and not append:
                offset = 0
            _write_download(response, partial, artifact.size, offset, append, progress)
    except OSError as exc:
        raise UpdateError(f"Could not download {artifact.name}: {exc}") from exc

    if not _artifact_ready(partial, artifact):
        partial.unlink(missing_ok=True)
        raise UpdateError(f"Downloaded artifact verification failed: {artifact.name}")
    os.replace(partial, destination)
    _report(progress, 100)
    return destination


def verify_artifact(path: Path, artifact: ReleaseArtifact) -> bool:
    resolved = path.expanduser().resolve()
    return (
        resolved.is_file()
        and resolved.stat().st_size == artifact.size
        and _sha256(resolved) == artifact.sha256
    )


def verify_authenticode_signature(path: Path, publisher: str = "") -> bool:
    environment = os.environ.copy()
    environment["JJZERO_VERIFY_SIGNATURE_PATH"] = str(path.expanduser().resolve())
    command = (
        "$signature = Get-AuthenticodeSignature -LiteralPath "
        "$env:JJZERO_VERIFY_SIGNATURE_PATH; "
        "[pscustomobject]@{Status=[string]$signature.Status; "
        "Subject=[string]$signature.SignerCertificate.Subject} | ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        data = json.loads(completed.stdout.strip())
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return False
    subject = str(data.get("Subject", "")) if isinstance(data, Mapping) else ""
    return (
        completed.returncode == 0
        and isinstance(data, Mapping)
        and data.get("Status") == "Valid"
        and (not publisher or publisher.casefold() in subject.casefold())
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
    signature_required, publisher = _parse_authenticode(data.get("authenticode"), name)
    return ReleaseArtifact(
        name,
        size,
        sha256,
        url,
        signature_required,
        publisher,
    )


def _parse_authenticode(data: object, name: str) -> tuple[bool, str]:
    if data is None:
        return False, ""
    if not isinstance(data, Mapping):
        raise UpdateError(f"Invalid Authenticode metadata: {name}")
    required = data.get("required")
    publisher = data.get("publisher")
    if required is not True or not isinstance(publisher, str) or not publisher.strip():
        raise UpdateError(f"Incomplete Authenticode metadata: {name}")
    return True, publisher.strip()


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
            target.write(chunk)
            downloaded += len(chunk)
            _report(progress, int(downloaded * 100 / expected_size))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(DOWNLOAD_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_ready(path: Path, artifact: ReleaseArtifact) -> bool:
    return verify_artifact(path, artifact) and (
        not artifact.signature_required
        or verify_authenticode_signature(path, artifact.publisher)
    )


def _report(progress: ProgressReporter | None, value: int) -> None:
    if progress is not None:
        progress(max(0, min(value, 100)))


def _open_url(request: Request, timeout: float) -> Response:
    return urlopen(request, timeout=timeout)  # type: ignore[return-value]
