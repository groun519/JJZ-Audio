# JJZero Audio Update Cache Cleanup Design

## Goal

JJZero Audio must remove update artifacts after they have served their purpose without deleting resumable downloads, reusable media caches, runtimes, models, or user data.

## Managed Scope

Cleanup is restricted to `Cache/updates/<release-version>/`. Paths outside this root are ignored even when passed by a caller. The cleanup service does not inspect or remove waveform previews, separation models, library media, output files, logs, settings, OAuth data, or runtime installations.

## Lifecycle

### Runtime-only update

1. Download verified runtime ZIP files into the release update directory.
2. Install and verify every selected runtime component.
3. Remove the completed release update directory.
4. Restart the application.

Failed downloads and failed installations retain their artifacts so the existing resume and retry behavior remains available.

### Application update

1. Download the installer and any required runtime packages into the release update directory.
2. Install and verify runtime packages, then remove only the consumed ZIP files.
3. Start the installer successfully.
4. Write a cleanup marker into the managed release update directory.
5. On startup, remove marked artifacts only when the running application version is at least the marker's target version.

Writing the marker after the installer process starts prevents failed launch attempts from discarding the installer. Checking the running version prevents the old application from deleting an installer when installation did not complete.

## Failure Handling

- Cleanup is best effort and never changes a successful update into a failed update.
- A locked file leaves the cleanup marker in place so the next startup retries.
- The marker is removed last.
- Unmarked directories and `.part` files remain untouched because they may represent resumable downloads.
- Symlinks, junctions, and resolved paths outside the managed update root are skipped.
- Cleanup results are written to the application log with removed file count, reclaimed bytes, and failed path count. No user-facing notification is added.

## Components

- `update_cache.py`: owns marker validation, managed-path checks, completed-directory removal, and cleanup reporting.
- `main_window.py`: marks application updates after the installer starts and removes runtime-only update directories after verified installation.
- `app_bootstrap.py`: runs marked cleanup during startup after the cache root exists.

## Verification

Tests cover managed-path confinement, version gating, marker-last retry behavior, preservation of unmarked partial downloads, runtime-only directory cleanup, startup integration, and installer-launch marker creation. Existing update download, resume, runtime installation, and full application tests must continue to pass.
