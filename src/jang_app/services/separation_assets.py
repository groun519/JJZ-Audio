from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from jang_app.config import DEMUCS_RUNTIME_DIR, ROFORMER_MODEL_DIR
from jang_app.services.separation_recipe import SeparationRecipe


_CHECKPOINT_BYTES = 84_141_911
_DEMUCS_MODEL_FILES = {
    "htdemucs": ("955717e8-8726e21a.th",),
    "htdemucs_ft": (
        "f7e0c4bc-ba3fe64a.th",
        "d12395a8-e57c48e6.th",
        "92cfc3b6-ef3bcb9c.th",
        "04573f0d-f3cf25b2.th",
    ),
}


@dataclass(frozen=True)
class RoFormerModelFile:
    filename: str
    size: int
    sha256: str
    url: str


@dataclass(frozen=True)
class RoFormerModelAssets:
    model: str
    config: str
    registry_name: str
    files: tuple[RoFormerModelFile, ...]
    managed_download: bool = False
    config_source: str = ""
    config_replacements: tuple[tuple[str, str], ...] = ()


_MODEL_REPOSITORY = (
    "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models"
)
_MODEL_CONFIG_REPOSITORY = (
    "https://raw.githubusercontent.com/TRvlvr/application_data/main/"
    "mdx_model_data/mdx_c_configs"
)
_ROFORMER_MODEL_ASSETS = {
    "model_bs_roformer_ep_317_sdr_12.9755.ckpt": RoFormerModelAssets(
        model="model_bs_roformer_ep_317_sdr_12.9755.ckpt",
        config="model_bs_roformer_ep_317_sdr_12.9755.yaml",
        registry_name="JJZero Audio: BS-RoFormer 317",
        files=(
            RoFormerModelFile(
                "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
                639_331_213,
                "5b84f37e8d444c8cb30c79d77f613a41c05868ff9c9ac6c7049c00aefae115aa",
                f"{_MODEL_REPOSITORY}/model_bs_roformer_ep_317_sdr_12.9755.ckpt",
            ),
            RoFormerModelFile(
                "model_bs_roformer_ep_317_sdr_12.9755.yaml",
                2_273,
                "2bfdd16c656bd9519aba757cc4f8834b7ede675eb1e00ec4772d74ae1c41af7f",
                f"{_MODEL_CONFIG_REPOSITORY}/model_bs_roformer_ep_317_sdr_12.9755.yaml",
            ),
        ),
    ),
    "MelBandRoformer.ckpt": RoFormerModelAssets(
        model="MelBandRoformer.ckpt",
        config="config_vocals_mel_band_roformer_kim.yaml",
        registry_name="JJZero Audio: Vocal MelBand-RoFormer",
        files=(
            RoFormerModelFile(
                "MelBandRoformer.ckpt",
                913_106_900,
                "87201f4d31afb5bc79993230fc49446918425574db48c01c405e44f365c7559e",
                "https://huggingface.co/KimberleyJSN/melbandroformer/resolve/main/"
                "MelBandRoformer.ckpt",
            ),
            RoFormerModelFile(
                "config_vocals_mel_band_roformer_kim.yaml",
                968,
                "32419582fa8c313199ab49be8f5cb2b5e3860769ca045b4788a960d72140cd39",
                f"{_MODEL_CONFIG_REPOSITORY}/config_vocals_mel_band_roformer_kim.yaml",
            ),
        ),
        managed_download=True,
    ),
    "deverb_bs_roformer_8_256dim_8depth.ckpt": RoFormerModelAssets(
        model="deverb_bs_roformer_8_256dim_8depth.ckpt",
        config="deverb_bs_roformer_8_256dim_8depth_jjzero.yaml",
        registry_name="JJZero Audio: BS-RoFormer De-Reverb",
        files=(
            RoFormerModelFile(
                "deverb_bs_roformer_8_256dim_8depth.ckpt",
                170_770_820,
                "ee204fc59fa4111674536d47bd1ef3759acb9f7cf5a759ec4b867a828bb76c64",
                "https://huggingface.co/anvuew/dereverb_bs_roformer/resolve/main/"
                "archive/deverb_bs_roformer_8_256dim_8depth.ckpt",
            ),
            RoFormerModelFile(
                "deverb_bs_roformer_8_256dim_8depth_upstream.yaml",
                2_357,
                "8a7a2e058bf21c73ae6e08301808c8de18cf113c343ede836a290d26e83af283",
                "https://huggingface.co/anvuew/dereverb_bs_roformer/resolve/main/"
                "archive/deverb_bs_roformer_8_256dim_8depth.yaml",
            ),
        ),
        managed_download=True,
        config_source="deverb_bs_roformer_8_256dim_8depth_upstream.yaml",
        config_replacements=(
            ("  dim_t: 801", "  dim_t: 690"),
            ("  hop_length: 441", "  hop_length: 512"),
            (
                "  instruments:\n  - noreverb\n  - reverb",
                "  instruments:\n  - Vocals",
            ),
            ("  target_instrument: noreverb", "  target_instrument: Vocals"),
        ),
    ),
}


@dataclass(frozen=True)
class SeparationAssetStatus:
    model: str
    ready: bool
    present_files: int
    required_files: int
    missing_bytes: int

    @property
    def status_text(self) -> str:
        if self.ready:
            return "Model ready"
        return f"First use downloads about {format_byte_size(self.missing_bytes)}"


def separation_asset_status(
    model: str,
    runtime_root: Path | None = None,
) -> SeparationAssetStatus:
    roformer_assets = _ROFORMER_MODEL_ASSETS.get(model)
    if roformer_assets is not None:
        model_root = (
            runtime_root.expanduser().resolve() / "models"
            if runtime_root is not None
            else ROFORMER_MODEL_DIR.expanduser().resolve()
        )
        present = tuple(
            item.filename
            for item in roformer_assets.files
            if (model_root / item.filename).is_file()
        )
        missing_bytes = sum(
            item.size
            for item in roformer_assets.files
            if not (model_root / item.filename).is_file()
        )
        return SeparationAssetStatus(
            model=model,
            ready=len(present) == len(roformer_assets.files),
            present_files=len(present),
            required_files=len(roformer_assets.files),
            missing_bytes=missing_bytes,
        )
    files = _DEMUCS_MODEL_FILES.get(model, ())
    demucs_root = (runtime_root or DEMUCS_RUNTIME_DIR).expanduser().resolve()
    checkpoint_root = demucs_root / "torch" / "hub" / "checkpoints"
    present = tuple(filename for filename in files if (checkpoint_root / filename).is_file())
    missing_count = len(files) - len(present)
    return SeparationAssetStatus(
        model=model,
        ready=bool(files) and missing_count == 0,
        present_files=len(present),
        required_files=len(files),
        missing_bytes=missing_count * _CHECKPOINT_BYTES,
    )


def separation_model_component_count(model: str) -> int:
    return max(1, len(_DEMUCS_MODEL_FILES.get(model, ())))


def roformer_model_assets(model: str) -> RoFormerModelAssets | None:
    return _ROFORMER_MODEL_ASSETS.get(model)


def separation_recipe_asset_status(
    recipe: SeparationRecipe,
    runtime_root: Path | None = None,
) -> SeparationAssetStatus:
    return combine_separation_asset_status(
        separation_asset_status(model, runtime_root) for model in recipe.required_models
    )


def combine_separation_asset_status(
    statuses: Iterable[SeparationAssetStatus],
) -> SeparationAssetStatus:
    values = tuple(statuses)
    if not values:
        return SeparationAssetStatus("", False, 0, 0, 0)
    return SeparationAssetStatus(
        model=" + ".join(status.model for status in values),
        ready=all(status.ready for status in values),
        present_files=sum(status.present_files for status in values),
        required_files=sum(status.required_files for status in values),
        missing_bytes=sum(status.missing_bytes for status in values),
    )


def format_byte_size(byte_count: int) -> str:
    size = max(0, byte_count)
    if size >= 1024**3:
        return f"{size / 1024**3:.1f} GB"
    return f"{size / 1024**2:.0f} MB"
