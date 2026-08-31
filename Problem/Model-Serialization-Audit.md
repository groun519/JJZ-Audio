# RVC Model Serialization Audit

## Session status

- Status: fixed in the current worktree; full regression verification in progress
- Started: 2026-08-27 KST
- Scope: RVC inference models, shared training checkpoints, generated spectrogram
  caches, artifact inspection, and runtime-package patching

## Confirmed finding

### MODEL-SER-01: Shared RVC files were loaded with unrestricted pickle deserialization

- Severity: critical
- Trigger: import or link an RVC model/model-work package containing a crafted `.pth`,
  then inspect, convert with, or continue training that model.
- Root cause: inference, artifact-inspection, checkpoint-resume, model-processing, and
  spectrogram-cache paths called `torch.load()` without `weights_only=True`. PyTorch
  therefore used pickle-compatible object loading for files that can originate from
  public Google Drive links or local external folders.
- Impact: opening or using a malicious shared model could execute code with the current
  user's permissions.
- Fix: every user-reachable RVC model, G/D checkpoint, pretrain, model-processing, and
  spectrogram load now uses restricted weights-only deserialization. The tracked
  runtime patcher applies the same invariant to newly prepared CUDA, DirectML, and
  ROCm runtime packages. Diagnostics classify rejected files as `RVC_MODEL_UNSAFE`.
- Compatibility verification: existing v2/40k inference models, G/D resume checkpoints,
  and spectrogram caches loaded successfully with the bundled Torch 2.0 CUDA runtime;
  the same inference model loaded with the DirectML Torch 2.4 runtime.
- Security verification: an executable checkpoint whose pickle payload attempted to
  create a marker file was rejected with `WeightsUnpickler`; the worker returned a
  failure and the marker was not created.

