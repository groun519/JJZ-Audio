from pathlib import Path

from jang_app.services.app_paths import discover_app_paths


PACKAGE_ROOT = Path(__file__).resolve().parent
APP_PATHS = discover_app_paths(PACKAGE_ROOT)
SOURCE_ROOT = APP_PATHS.source_root
INSTALL_ROOT = APP_PATHS.install_root
PROJECT_ROOT = APP_PATHS.workspace_anchor
APP_NAME = "JJZero Audio"
ASSETS_DIR = PACKAGE_ROOT / "assets"
APP_ICON_PATH = ASSETS_DIR / "jjzero_logo.svg"
GOOGLE_ICON_PATH = ASSETS_DIR / "google_g.svg"
GOOGLE_OAUTH_CLIENT_PATH = ASSETS_DIR / "google_oauth_client.json"
RVC_RUNTIME_DIR = APP_PATHS.runtime_root / "rvc"
DEFAULT_RVC_ROOT = (
    RVC_RUNTIME_DIR
    if APP_PATHS.is_frozen
    else Path.home() / "RVC"
)
VENV_SCRIPTS_DIR = (
    APP_PATHS.runtime_root / "ai" / "Scripts"
    if APP_PATHS.is_frozen
    else SOURCE_ROOT / ".venv" / "Scripts"
)
THIRD_PARTY_DIR = APP_PATHS.runtime_root
FFMPEG_BIN_DIR = THIRD_PARTY_DIR / "ffmpeg" / "bin"
DEMUCS_RUNTIME_DIR = THIRD_PARTY_DIR / "demucs"
RVC_PYTHON_EXE = RVC_RUNTIME_DIR / "runtime" / "python.exe"
WORKSPACE_DIR = APP_PATHS.workspace_root
SONG_WORKSPACE_DIR = WORKSPACE_DIR / "library" / "songs"
RVC_WORKSPACE_DIR = WORKSPACE_DIR / "rvc_cli"
MODEL_WORKSPACE_DIR = WORKSPACE_DIR / "models"
PLAYBACK_WORKSPACE_DIR = WORKSPACE_DIR / "playback"
PREVIEW_WORKSPACE_DIR = WORKSPACE_DIR / "previews"
OUTPUT_DIR = APP_PATHS.output_root
DOWNLOAD_OUTPUT_DIR = OUTPUT_DIR / "downloads"
LOG_DIR = APP_PATHS.log_dir
LOG_FILE = LOG_DIR / "jang.log"
SETTINGS_DIR = APP_PATHS.settings_dir
SETTINGS_FILE = SETTINGS_DIR / "app_settings.json"
SONG_LIBRARY_FILE = SETTINGS_DIR / "song_library.json"
WORK_SONG_FILE = SETTINGS_DIR / "work_song.json"
SEPARATION_OUTPUT_DIR = OUTPUT_DIR / "separations"

SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg"}
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
