# Vocal Separation Model Survey

## Document Status

- Status: Initial screening complete; upper-tier listening pack prepared
- Survey date: 2026-08-12
- Scope: Singing-vocal extraction for downstream RVC conversion
- Decision stage: Candidate selection, before checkpoint integration
- Related plan: [Adaptive Vocal Separation Research Plan](adaptive-vocal-separation-research-plan.md)

## Executive Conclusion

There is no verified universal replacement for every current separator. Model
architecture, training target, and checkpoint data all affect the result, and a
higher SDR does not guarantee a better RVC-converted vocal.

The useful candidate set is much smaller than the public checkpoint list:

1. **HyperACE v2 vocal** is the strongest recent community RoFormer checkpoint
   by the screened MVSep metric, but its checkpoint license is not reviewed and
   it cannot enter product distribution yet.
2. **BS PolarFormer** is the strongest lightweight official-release candidate
   inside the RoFormer family. It is not a new family: the released configuration
   uses the BS-RoFormer implementation with PoPE positional encoding instead of
   RoPE.
3. **MDX23C vocal** is the highest-priority independent frequency-domain expert.
   It is valuable because its errors should differ from Demucs and RoFormer.
4. **SCNet XL IHF** is a relatively compact, efficient multi-stem expert. It is
   not an obvious quality replacement, but it may provide useful context or
   rescue regions that fail in a direct vocal model.
5. **BS Mamba2 vocal** is a preservation-oriented research candidate. Its
   two-stage mask and residual design is specifically interesting for details
   omitted by mask-only separation, but its public score does not justify making
   it the default without listening tests.
6. **HTDemucs** remains necessary as a distinct compatibility baseline. Its
   different waveform/spectrogram design means it can succeed where a RoFormer
   checkpoint fails, even though its average vocal metric is lower.

Most public MelBand-RoFormer and BS-RoFormer checkpoints are **policy variants**,
not new separation strategies. They should be screened by intended target such
as wet vocal, dry vocal, bleedless vocal, lead vocal, de-reverb, or denoise and
must not each become a user-facing mode.

## How To Read The Metrics

- Checkpoint size is an exact download-size observation from the local asset
  registry or the official release asset.
- SDR values are copied from the MSST pretrained-model table. Values from
  different datasets or target definitions are not directly interchangeable.
- `Multisong` is more useful than a MUSDB-only score for generalization, but it
  still does not predict RVC quality on every song.
- Runtime and VRAM rankings are provisional until measured in the JJZero Audio
  runtime on the same clips and hardware.
- Character descriptions are architectural hypotheses or current listening
  observations. They are not accepted product behavior until the controlled
  listening benchmark confirms them.

## Current JJZero Audio Inventory

| Product role | Checkpoint | Family | Download size | Current behavior |
| --- | --- | --- | ---: | --- |
| Fast Separation | `htdemucs` | Hybrid Demucs | 80.2 MB | Fast, robust compatibility baseline; can miss effect-heavy vocal material |
| Legacy fine-tuned Demucs | `htdemucs_ft` | Hybrid Demucs | 320.8 MB total | Four approximately 80.2 MB source experts; upstream documents roughly four times the processing cost |
| Precision default | BS-RoFormer ep 317 | Band-Split RoFormer | 609.7 MB | Strong direct vocal capture; official MSST Multisong vocal SDR 10.87 |
| Precision alternative | Kimberley vocal MelBand | MelBand-RoFormer | 870.8 MB | Strong vocal-focused checkpoint; official MSST Multisong vocal SDR 10.98 |
| Effect cleanup | BS-RoFormer de-reverb | Band-Split RoFormer | 162.9 MB | Refinement only; current listening found that aggressive use can remove wanted vocal energy |

The three managed RoFormer checkpoints consume approximately **1.60 GiB** before
runtime dependencies and caches. New research checkpoints and their isolated
CUDA 12.8 runtime are stored under `S:\JJZeroAudioResearch`; they are not part of
the product runtime or distributable assets.

## Upper-Tier Probe Status (2026-08-12)

BS PolarFormer and the separate HyperACE v2 vocal and instrumental checkpoints
passed an RTX 3060 CUDA smoke test and were rendered across the four fixed
benchmark clips. The comparison contains four anonymous candidates:

1. Kimberley MelBand baseline
2. BS PolarFormer
3. HyperACE v2 vocal plus HyperACE v2 instrumental
4. Kimberley MelBand vocal plus HyperACE v2 instrumental

The research runtime uses Python 3.11 and PyTorch 2.7.1 with CUDA 12.8. The exact
checkpoint and config hashes are stored in
`S:\JJZeroAudioResearch\benchmarks\vocal-separation-candidates-v2\experiment-definition.json`.
On the local RTX 3060, PolarFormer processed all four clips in approximately 29
seconds. Each HyperACE checkpoint required approximately 70 seconds for the same
four clips. HyperACE's upstream folder runner lost its chunk setting after the
first file, so each clip was executed in a fresh process to prevent mutable
configuration state from crossing tracks.

All outputs are 44.1 kHz stereo and have the expected duration. PolarFormer and
the residual output of the HyperACE vocal model reconstruct the source to the
numeric floor. The independently trained HyperACE vocal/instrumental pair does
not enforce exact reconstruction and measured residuals from approximately
-36 to -46 dBFS. PolarFormer and HyperACE also produced peaks around +1.3 dBFS
on the Dracula control clip. These are listening-review warnings, not automatic
rejections.

The fixed pq-a conversion and 35% instrumental mixes completed for all 16
candidate/clip combinations. The primary review is incremental: each of the
four songs is one page, A is the previously approved stem, and the two new
candidates receive only `better`, `same`, or `worse` judgments. Vocal and
instrumental tabs use consistent candidate codes and exact duplicate stems are
removed by hash. The earlier full review packs remain available for diagnosis,
but are not the normal evaluation path. The incremental review is stored at
`S:\JJZeroAudioResearch\benchmarks\vocal-separation-candidates-v2\review\incremental-review.json`.
The completed raw review advanced HyperACE for both Popin2 stems, PolarFormer
for the 999999 vocal, and PolarFormer for the O3ohn instrumental. Neither model
advanced on Dracula. The focused pq-a follow-up contains only those three songs
and five relative decisions. HyperACE remains research-only because its
checkpoint license is still not reviewed.

## Candidate Matrix

| Candidate | Architecture and target | Published or screened vocal result | Checkpoint | Expected character | Replacement assessment | Survey action |
| --- | --- | ---: | ---: | --- | --- | --- |
| HyperACE v2 vocal | BS-RoFormer trunk with a modified HyperACE mask-estimator head, vocal/other | MVSep-reported SDR 11.39 | 275.3 MB | Recent direct-vocal checkpoint with stronger reported separation than the older public RoFormer set; still likely to share RoFormer-family errors | **Potential quality replacement**, blocked from distribution while license is unreviewed | Research-only probe after provenance and terms review |
| BS PolarFormer | BS-RoFormer variant, PoPE positional encoding, vocal/other | Multisong SDR 11.00 | 97.7 MB, float16 | Same broad strengths as BS-RoFormer with a much smaller artifact; error diversity may be limited because it remains the same family | **Potential RoFormer-family replacement**, not a universal replacement | First direct test after license and runtime checks |
| MDX23C vocal | TFC-TDF v3 time-frequency convolutional model, vocal/other | Multisong SDR 10.17 | 427.3 MB | Likely to make different frequency-domain masking errors than Demucs or RoFormer; useful clean-vocal expert | **Complementary expert**; possible replacement only if RVC listening clearly wins | Second direct test |
| SCNet XL IHF | Sparse-compression frequency model, four stems | Multisong vocal SDR 9.68; MUSDB vocal SDR 11.42 | 204.1 MB | Efficient subband modeling and extra stem context; may help dense accompaniment, but public generalization score trails current RoFormer checkpoints | **Not an upper replacement**; strong routing or rescue candidate | Third direct test |
| BS Mamba2 vocal | Two-stage band-split Mamba2, mask then residual mapping, vocal/other | SDR 8.82, MUSDB-only training noted | 183.7 MB | Residual stage is designed to recover details missed by masking; promising for intermittent, quiet, or sparse vocal regions | **Preservation candidate**, not default-quality evidence | Fourth direct test on quiet and dropout cases |
| SCNet Small | Sparse-compression frequency model, four stems | Multisong vocal SDR 8.27 | 40.5 MB | Very small artifact and paper-reported CPU efficiency | **Low-resource fallback candidate**, not a quality upgrade | Defer until quality candidates are measured |
| BS Conformer Medium | Band-split Conformer, four stems | Multisong vocal SDR 8.75 | 142.5 MB | Local convolution plus global attention; compact but no clear advantage over higher-priority candidates | No current replacement case | Defer |
| VitLarge23 | Segmentation-style frequency model, vocal/other | Multisong SDR 9.77 | 823.7 MB | Large independent model, but storage is high relative to its public result | No current replacement case | Reject from first benchmark round |
| MVSep HTDemucs vocal | Fine-tuned HTDemucs, vocal/other | Multisong SDR 8.78 | 160.3 MB | Same broad architecture family as the existing compatibility model | Possible checkpoint variant, not a new strategy | Defer unless it fixes a documented HTDemucs failure |

## Recent Community and Research Watch List

These candidates are technically relevant but are not ready for product
integration. They are separated from the primary matrix because either their
checkpoint terms or reproducible artifacts are incomplete.

| Candidate | Evidence | Size or availability | Why it matters | Blocker |
| --- | --- | ---: | --- | --- |
| Leap XE vocal | Public pcunwa checkpoint; standard BS-RoFormer trunk; used by third-party RVC-oriented dry-vocal workflows | 255.4 MB | May capture a lead-vocal target that is more useful for RVC than a generic wet vocal stem | Registry marks license `not-reviewed`; no screened paper or comparable official score |
| HyperACE v2 instrumental | Matching modified-head instrumental checkpoint; MVSep reports instrumental SDR 17.40 | 275.4 MB | An instrumental-target estimate can provide a complementary vocal reconstruction by source subtraction | Same unreviewed checkpoint-license blocker; subtraction must preserve scale and alignment |
| Mamba2 Meets Silence BSMamba2 | 2025 paper reports cSDR 11.03 and improved short/intermittent-vocal behavior | No author checkpoint or official implementation located during this survey | Directly targets sparse and intermittent vocals, one of JJZero Audio's observed failure classes | Paper-only watch item until reproducible code and weights exist |
| Siamese and value-residual RoFormer variants | Public community registry records distinct trunk variations | Public artifacts exist; sizes vary | May provide more error diversity than ordinary RoFormer fine-tunes | No screened benchmark, model card, or reviewed checkpoint license |

`TS-BSMamba2` and `Mamba2 Meets Silence BSMamba2` are different research lines.
The former has public code and an MSST checkpoint; the latter reports stronger
intermittent-vocal results but currently lacks a verified artifact path.

## Family Notes

### Hybrid Demucs

HTDemucs combines waveform and spectrogram processing. It is the only installed
direct model from a clearly different time-domain-aware family, so replacing it
with another RoFormer would reduce failure diversity. The fine-tuned
`htdemucs_ft` package contains four source-specific models and is documented as
roughly four times slower than the single HTDemucs model for a relatively small
quality gain.

**Keep for:** compatibility, transient and timing reference, fallback routing.

**Do not assume:** that its lower average SDR means it always loses on an
effect-heavy or unusual mix.

### Band-Split and MelBand RoFormer

BS-RoFormer splits the spectrum into bands and alternates time and frequency
attention. MelBand-RoFormer uses mel-spaced bands for a more perceptually focused
frequency allocation. These are currently the strongest installed direct
separators, but the public ecosystem contains many checkpoints with different
training targets and inconsistent licensing metadata.

**Keep for:** primary high-quality capture and target-specific refinements.

**Do not assume:** that another large RoFormer checkpoint is an independent
strategy or that a higher checkpoint SDR preserves dry lead vocals better.

### BS PolarFormer

The official v1.0.20 configuration loads the BS-RoFormer implementation with
`use_pope: true`. It therefore replaces rotary position encoding with PoPE while
retaining the band-split transformer structure. The 97.7 MB artifact is float16,
uses a 256-dimensional, 12-block configuration, and processes approximately
20-second inference chunks with overlap 2.

Its official Multisong vocal SDR of 11.00 and small artifact make it a serious
candidate to replace the current 609.7 MB BS-RoFormer checkpoint. That conclusion
is provisional because the architecture is still closely related and its
runtime dependency, VRAM use, licensing, and RVC listening result remain to be
verified.

### HyperACE and Leap XE

HyperACE v2 keeps a BS-RoFormer trunk but changes the mask-estimator head. MVSep
reported vocal SDR 11.39 and instrumental SDR 17.40 in March 2026. A separately
maintained inference registry records pinned downloads and hashes for both
approximately 275 MB checkpoints, but explicitly marks their licenses as
`not-reviewed`.

Leap XE uses the standard BS-RoFormer trunk with a different community training
target. Its vocal checkpoint is approximately 255 MB and is used by some
RVC-oriented workflows as a dry or lead-vocal capture stage. That intended
character is worth testing, but it is not yet supported by an author paper,
comparable official metric, or reviewed redistribution terms.

Both candidates are checkpoint-policy research, not independent architecture
families.

### MDX23C

MSST identifies MDX23C as a TFC-TDF v3 architecture. It works in the
time-frequency domain using convolutional processing rather than the same
attention structure as the current RoFormer models. Its official vocal-only
checkpoint is 427.3 MB with Multisong vocal SDR 10.17.

Its main value is **error diversity**, not a claim that 10.17 exceeds 10.98. A
segment router or guarded fusion stage needs at least one credible model that
fails differently from the primary RoFormer.

### SCNet

SCNet splits a spectrogram into subbands and applies stronger compression to
bands with less information. The paper reports lower computational consumption
and CPU inference at 48% of HTDemucs for the evaluated setup. The XL IHF
checkpoint has strong MUSDB vocal performance but falls from 11.42 on MUSDB to
9.68 on the broader MSST Multisong test.

That drop is important evidence against treating an in-domain leaderboard result
as a universal replacement claim. SCNet is better positioned as an efficient
multi-stem context or rescue expert.

### BS Mamba2

TS-BSMamba2 first estimates a source with masking, then applies residual mapping
to recover details omitted by the mask. Bidirectional Mamba2 blocks model long
sequences without using the same transformer attention path as RoFormer.

The architecture directly addresses the type of vocal loss that matters to RVC,
but the available MSST vocal checkpoint is trained on MUSDB18 and its published
score is below the current RoFormer checkpoints. It should be tested on quiet,
breathy, intermittent, and partially dropped vocal regions rather than promoted
as a general default.

### BandIt and Apollo

BandIt is a generalized bandsplit architecture, but its official application is
cinematic dialogue, music, and effects separation. No screened singing-vocal
checkpoint currently justifies a product test.

Apollo is an audio restoration model for lossy high-sample-rate audio, not a
source separator. It could later become a conditional pre-processing policy for
poor MP3 sources, but placing it in the direct-separator benchmark would compare
different tasks.

### DiCoSe and Other Refiners

DiCoSe applies diffusion or consistency refinement to a separator such as
BS-RoFormer. De-reverb, denoise, aspiration, lead/backing-vocal, and karaoke
checkpoints likewise change an existing stem rather than replace the first
capture model.

These are phase-two policy components. They should only run behind a vocal-loss
guard and must preserve the unrefined result for recovery.

## Superset Assessment

A strict upper-compatible replacement must satisfy all of the following:

- preserve or improve vocal completeness across dry, wet, quiet, doubled, and
  dense-mix material;
- reduce or preserve instrumental leakage;
- improve or preserve RVC stability and final-mix naturalness;
- fit the supported CPU, NVIDIA, and AMD runtime paths;
- have acceptable download, disk, VRAM, and processing cost;
- have checkpoint terms that permit the intended distribution model.

No surveyed model currently meets all criteria with evidence.

| Scope | Current conclusion |
| --- | --- |
| Replace current BS-RoFormer checkpoint | BS PolarFormer is the strongest provisional candidate |
| Replace current BS-RoFormer on pure quality | HyperACE v2 is a research-only candidate until checkpoint terms are resolved |
| Replace all RoFormer variants | No candidate; training targets remain materially different |
| Replace HTDemucs fallback | No; it provides useful architecture diversity |
| Improve difficult regions | MDX23C, SCNet XL IHF, and BS Mamba2 are complementary candidates |
| Improve effect-heavy vocals | Requires guarded refinement or segment routing; no direct model is proven universal |

## Resource Screening

Checkpoint size alone is not VRAM usage. Chunk length, model width and depth,
overlap, precision, attention backend, and number of output stems all matter.
The following must be measured instead of estimated for product decisions:

- cold model load time;
- peak process RAM and peak GPU VRAM;
- real-time factor on CPU and each supported GPU backend;
- output stability after CUDA or DirectML fallback;
- first-download size and expanded cache size;
- failure behavior under low VRAM and low disk space.

The benchmark should use the same 30-second dry, wet/effect-heavy, quiet, and
dense-mix clips. Each run must use the same sample rate, output precision, chunk
policy, and warm/cold state.

## Recommended First Benchmark Round

Do not download all public models. Test this representative set in order:

1. Freeze `htdemucs`, current BS-RoFormer 317, and Kimberley MelBand outputs.
   This baseline round is complete: Kimberley led every vocal-stem rating,
   HTDemucs remained strongest for several instrumental stems, and BS-RoFormer
   317 had no full-pair win.
2. Complete the prepared BS PolarFormer and HyperACE v2 blind review. Do not
   promote either checkpoint from objective metrics alone.
3. Test MDX23C vocal as the first genuinely different direct expert. Error
   diversity has higher quality value than repeatedly adding RoFormer-family
   variants.
4. Test SCNet XL IHF for efficient multi-stem context and dense-mix rescue.
5. Test BS Mamba2 only on preservation cases where other models omit vocals.
6. Review HyperACE v2 and Leap XE checkpoint terms and provenance. If acceptable
   for internal evaluation, run research-only probes without product bundling.
7. Advance a model to full-song and RVC tests only after short blind probes show
   a meaningful difference.

The first new checkpoint set is approximately **913 MB** in downloads before
dependencies: PolarFormer 97.7 MB, MDX23C 427.3 MB, SCNet XL IHF 204.1 MB, and
BS Mamba2 183.7 MB. Download one candidate at a time and retain it only when it
passes screening.

## Intermediate Structure Implications

This survey supports a three-layer model registry rather than a flat list:

1. **Capture models:** HTDemucs, selected RoFormer, MDX23C, SCNet, or Mamba2.
2. **Targeted refiners:** de-reverb, denoise, lead/background split, restoration.
3. **Policies:** model plus chunk, overlap, precision, refinement, fallback, and
   vocal-loss guard settings.

Only policies should be visible to the main workflow. Architecture and
checkpoint details belong in diagnostics and the research registry. This keeps
the future router free to replace a checkpoint without changing the user-facing
mode names.

## License and Distribution Gate

Repository code licenses and checkpoint redistribution rights are separate.
Before bundling or managed downloading any model, record:

- exact checkpoint URL and SHA-256;
- author or organization;
- explicit checkpoint/model-card license;
- training dataset provenance where disclosed;
- whether commercial use, redistribution, and modification are allowed;
- required attribution and notice files.

An MIT architecture repository does not automatically grant rights to every
community checkpoint trained with that code. A missing checkpoint license is a
blocker for product distribution, not permission by omission.

## Primary Sources

- [MSST repository and supported architectures](https://github.com/ZFTurbo/Music-Source-Separation-Training)
- [MSST official pretrained-model table](https://github.com/ZFTurbo/Music-Source-Separation-Training/blob/main/docs/pretrained_models.md)
- [Demucs repository and model documentation](https://github.com/facebookresearch/demucs)
- [BS-RoFormer paper](https://arxiv.org/abs/2309.02612)
- [MelBand-RoFormer vocal paper](https://arxiv.org/abs/2409.04702)
- [BS-RoFormer reference implementation](https://github.com/lucidrains/BS-RoFormer)
- [SCNet paper](https://arxiv.org/abs/2401.13276)
- [SCNet official implementation](https://github.com/starrytong/SCNet)
- [TS-BSMamba2 paper](https://arxiv.org/abs/2409.06245)
- [TS-BSMamba2 official implementation](https://github.com/baijinglin/TS-BSmamba2)
- [Mamba2 Meets Silence paper](https://arxiv.org/abs/2508.14556)
- [MVSep March 2026 model announcement](https://mvsep.com/news/67)
- [BS-RoFormer inference registry and checkpoint provenance](https://github.com/openmirlab/bs-roformer-infer)
- [BandIt official implementation](https://github.com/kwatcharasupat/bandit)
- [Apollo official implementation](https://github.com/JusperLee/Apollo)
- [DiCoSe project](https://consistency-separation.github.io/)
- [GitHub guidance for repositories without a license](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)

## Next Decision

Before designing the intermediate execution structure, decide which of these
questions the first benchmark must answer:

- Can PolarFormer replace the current direct BS-RoFormer checkpoint?
- Does MDX23C add enough error diversity to justify a second capture runtime?
- Does SCNet's multi-stem context improve dense sections after RVC conversion?
- Does BS Mamba2 recover quiet or intermittent vocal without adding leakage?

The intermediate architecture should be based on those observed roles, not on
the number of available checkpoints.
