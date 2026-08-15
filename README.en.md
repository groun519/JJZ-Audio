<p align="center">
  <img src="src/jang_app/assets/jjzero_logo.svg" width="96" alt="JJZero Audio logo">
</p>

<h1 align="center">JJZero Audio</h1>

<p align="center">
  From source audio to vocal separation, RVC conversion, mixing, and export in one local app.
</p>

<p align="center">
  <a href="README.md">한국어</a> ·
  <a href="README.en.md"><strong>English</strong></a>
</p>

<p align="center">
  <a href="https://github.com/groun519/JJZ-Audio/releases/latest"><img src="https://img.shields.io/github/v/release/groun519/JJZ-Audio?display_name=tag&sort=semver&style=flat-square&label=Release" alt="Latest release"></a>
  <img src="https://img.shields.io/badge/Windows-10%20%7C%2011-2f3136?style=flat-square&logo=windows11&logoColor=white" alt="Windows 10 and 11">
  <img src="https://img.shields.io/badge/Local--first-your%20data%20stays%20local-2f3136?style=flat-square" alt="Local-first">
</p>

> [!NOTE]
> This document describes the released **JJZero Audio 0.3.7**. Download the installer from [GitHub Releases](https://github.com/groun519/JJZ-Audio/releases/latest).

See the [0.3.7 release notes](docs/releases/0.3.7.md) for the single-device RVC training hotfix.

## One Connected Workflow

```text
Import  →  Separate vocals  →  Convert with RVC  →  Edit in Studio  →  Export audio or video
```

JJZero Audio keeps songs, voice models, separation runs, converted takes, timeline edits, and exports connected in one managed workspace. Processing is nondestructive: imported sources and linked external RVC folders are never edited in place.

## Features

| Workspace | Capabilities |
| --- | --- |
| **Library** | Import local files or YouTube audio, search and sort, edit metadata, preview audio, and manage the active work song |
| **Models** | Link or copy RVC models, edit and analyze training material, train or resume training, and manage checkpoints and indexes |
| **Vocal Separation** | Fast, Precision, and Custom separation; retained runs; paired vocal and instrumental comparison with synchronized playback |
| **RVC Conversion** | Select the source stem and RVC model, create and compare multiple takes, and audition them with the original vocal and instrumental |
| **Studio** | Audio and video pools, nondestructive timeline editing, split, trim, move, mute, level control, and mixing |
| **Export and Sharing** | Render final audio or video, keep outputs attached to their source song, and share models or outputs through Google Drive |

The app supports Korean and English, light and dark themes, background processing, structured diagnostics, and in-app updates.

## Quick Start

1. Download `JJZero-Audio-X.Y.Z-Setup.exe` from the [latest GitHub Release](https://github.com/groun519/JJZ-Audio/releases/latest).
2. Run the installer and launch JJZero Audio. A separate Python installation is not required.
3. Choose where songs, models, exports, and the managed runtime should be stored.
4. Wait for system diagnostics and installation of the audio runtime that matches the computer, then import a song.

ZIP parts and `latest.json` on the same release are app update components, not manual installers.

## Platform and Acceleration

JJZero Audio targets **Windows 10/11 x64**. First-run setup detects the graphics adapter and installs the shared audio engine plus only the matching acceleration profile.

| Hardware | RVC runtime | Training |
| --- | --- | --- |
| NVIDIA RTX 50 series | CUDA 12.8 (`cu128`) | GPU |
| Other supported NVIDIA GPUs | CUDA 11.8 (`cu118`) | GPU |
| Supported AMD Windows ROCm systems | `rocm-win` | Experimental GPU |
| Other AMD GPUs | DirectML inference | CPU |
| No supported GPU | CPU fallback | CPU |

A new acceleration profile becomes active only after validation. Failed GPU setup does not replace a working runtime or modify user media and model data.

## Data and Updates

The selected storage location contains separate roots for each data class.

```text
JJZero storage root/
  Data/       songs, models, projects, and catalogs
  Output/     rendered audio and video
  Runtime/    FFmpeg, separation models, RVC, and acceleration profiles
  Cache/      downloadable packages and temporary data
```

- App updates retain songs, models, Studio projects, and exports.
- Moving storage copies and verifies data before switching and leaves the previous location as a recovery copy.
- Normal uninstall removes the app, generated runtime, and cache while retaining `Data` and `Output`.
- See [Storage and Data Safety](docs/STORAGE.md) for migration, update, and removal details.

## Documentation

| Document | Contents |
| --- | --- |
| [Development](docs/DEVELOPMENT.md) | Source setup, local execution, tests, and project structure |
| [Windows Builds](docs/BUILDING.md) | Application distribution, installer, and runtime component builds |
| [Releasing](docs/RELEASING.md) | Versioning, signing, verification, and GitHub Release publishing |
| [Storage and Data Safety](docs/STORAGE.md) | Storage layout, migration, updates, and removal behavior |
| [Vocal Separation Model Survey](docs/vocal-separation-model-survey.md) | Separation model characteristics and comparison research |

## Diagnostics

When a job fails, copy its diagnostic report or open its detailed log folder from the **Processing Queue**. Logs are stored under `%LOCALAPPDATA%\JJZero Audio\logs` by default. Reports prepared for sharing redact sensitive paths and account details.

If the problem is reproducible, include the affected workflow, hardware information, and diagnostic report in a [GitHub Issue](https://github.com/groun519/JJZ-Audio/issues).
