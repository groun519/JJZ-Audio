from __future__ import annotations


def resolve_torch_device(requested: str):
    import torch

    value = str(requested or "cpu").strip().lower()
    if value in {"directml", "dml", "privateuseone", "privateuseone:0"}:
        import torch_directml

        _patch_fairseq_for_directml()
        return torch_directml.device(torch_directml.default_device()), "directml"
    if value.startswith("cuda") and torch.cuda.is_available():
        return value, "rocm" if getattr(torch.version, "hip", None) else "cuda"
    if value == "mps" and torch.backends.mps.is_available():
        return "mps", "mps"
    return "cpu", "cpu"


def _patch_fairseq_for_directml() -> None:
    import fairseq

    def forward_dml(ctx, tensor, scale):
        ctx.scale = scale
        return tensor.clone().detach()

    fairseq.modules.grad_multiply.GradMultiply.forward = forward_dml
