from __future__ import annotations

import re


def parse_cuda_capability(value: object) -> tuple[int, int]:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return ()
    try:
        return int(value[0]), int(value[1])
    except (TypeError, ValueError):
        return ()


def parse_cuda_arch_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def cuda_architecture_error(
    torch_version: str,
    cuda_version: str,
    device_capability: tuple[int, int],
    cuda_arch_list: tuple[str, ...],
) -> str:
    if not device_capability or device_capability < (12, 0):
        return ""
    architecture = f"sm_{device_capability[0]}{device_capability[1]}"
    compatible = (
        _version_at_least(torch_version, (2, 7, 1))
        and _version_at_least(cuda_version, (12, 8))
        and architecture in cuda_arch_list
    )
    if compatible:
        return ""
    found_arches = ", ".join(cuda_arch_list) or "unknown"
    return (
        f"RTX 50-series CUDA architecture {architecture} requires Torch 2.7.1+cu128 or newer. "
        f"Found Torch {torch_version or 'unknown'}, CUDA {cuda_version or 'unknown'}, "
        f"architectures [{found_arches}]."
    )


def _version_at_least(value: str, minimum: tuple[int, ...]) -> bool:
    match = re.search(r"\d+(?:\.\d+)+", value)
    if match is None:
        return False
    parts = tuple(int(part) for part in match.group(0).split("."))
    padded = parts + (0,) * max(0, len(minimum) - len(parts))
    return padded[: len(minimum)] >= minimum
