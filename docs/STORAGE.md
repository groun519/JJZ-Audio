# Storage and Data Safety

[한국어 README](../README.md) | [English README](../README.en.md)

## Storage Layout

First-run setup asks for one storage location and creates four independent roots:

```text
JJZero storage root/
  Data/       songs, managed models, projects, manifests, and catalogs
  Output/     rendered audio and video
  Runtime/    FFmpeg, separation models, RVC, and acceleration profiles
  Cache/      downloaded packages and regenerable temporary data
```

Small bootstrap settings, credentials protected by Windows, and diagnostic logs remain under `%LOCALAPPDATA%\JJZero Audio`. This bootstrap data lets the app locate the selected storage root before the main workspace is loaded.

## Nondestructive Processing

- Imported media is copied into the managed library before processing.
- Linked external RVC folders are read without modifying their source files.
- Separation, conversion, Studio, and export results are written as derived assets.
- Removing a derived asset does not modify the imported source.

## Updates and Migrations

Existing 0.2.x storage layouts remain readable. Data migrations are schema-driven and run in order, so an installation can move across multiple application versions without installing every intermediate release.

Application and runtime updates are independent:

- a normal application update keeps an existing compatible runtime;
- only changed or missing runtime components are downloaded;
- songs, models, Studio projects, and exports remain in place;
- profile activation is validated before replacing a working acceleration profile.

Running a newer version should create or upgrade metadata without rewriting original media.

## Moving Storage

Storage changes are performed from Settings. The app:

1. checks the destination and available space;
2. copies the selected data classes;
3. verifies copied files;
4. switches the active paths only after verification;
5. leaves the previous data as a recovery copy.

Do not manually merge active `Data`, `Runtime`, or catalog folders while the app is running.

## Uninstall

Open **Windows Settings > Apps > Installed apps** (**Apps & features** on older Windows 10), select **JJZero Audio**, and choose **Uninstall**. If the Windows entry is unavailable, run `unins000.exe` from the installation directory.

Normal uninstall removes:

- application files;
- the generated managed runtime;
- downloaded cache data.

Normal uninstall intentionally keeps:

- songs, managed models, Studio projects, and exports under `Data` and `Output`;
- bootstrap settings and diagnostic logs under `%LOCALAPPDATA%\JJZero Audio`;
- personal RVC `weights` and `logs`.

Before a managed runtime is removed, personal RVC files are moved to:

```text
%LOCALAPPDATA%\JJZero Audio\preserved-runtime\<timestamp>
```

Installer verification tests this preservation behavior against user-selected external storage roots.

## Complete Reset

To remove every JJZero Audio file:

1. back up any songs, models, outputs, or RVC files that should be retained;
2. uninstall JJZero Audio normally;
3. remove the selected JJZero storage root;
4. remove `%LOCALAPPDATA%\JJZero Audio`.

This permanently deletes remaining songs, models, exports, settings, logs, credentials, and preserved RVC files.

## Diagnostics

Runtime and job logs are stored under `%LOCALAPPDATA%\JJZero Audio\logs` unless a diagnostic path is explicitly redirected for testing. The Processing Queue can copy a redacted job report or open the detailed job folder.

Before sharing raw logs, check them for media titles, local paths, account identifiers, and other personal information.
