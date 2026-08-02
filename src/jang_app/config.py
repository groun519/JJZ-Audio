from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = Path(__file__).resolve().parent
APP_NAME = "JJZero Audio"
ASSETS_DIR = PACKAGE_ROOT / "assets"
APP_ICON_PATH = ASSETS_DIR / "jjzero_logo.svg"
DEFAULT_RVC_ROOT = Path(r"C:\Users\groun\Desktop\111\RVC0813Nvidia\RVC0813Nvidia")
VENV_SCRIPTS_DIR = PROJECT_ROOT / ".venv" / "Scripts"
THIRD_PARTY_DIR = PROJECT_ROOT / "third_party"
FFMPEG_BIN_DIR = THIRD_PARTY_DIR / "ffmpeg" / "bin"
WORKSPACE_DIR = PROJECT_ROOT / "workspace"
SONG_WORKSPACE_DIR = WORKSPACE_DIR / "library" / "songs"
RVC_WORKSPACE_DIR = WORKSPACE_DIR / "rvc_cli"
MODEL_WORKSPACE_DIR = WORKSPACE_DIR / "models"
PLAYBACK_WORKSPACE_DIR = WORKSPACE_DIR / "playback"
PREVIEW_WORKSPACE_DIR = WORKSPACE_DIR / "previews"
OUTPUT_DIR = PROJECT_ROOT / "output"
DOWNLOAD_OUTPUT_DIR = OUTPUT_DIR / "downloads"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "jang.log"
SETTINGS_DIR = PROJECT_ROOT / "settings"
SETTINGS_FILE = SETTINGS_DIR / "app_settings.json"
SONG_LIBRARY_FILE = SETTINGS_DIR / "song_library.json"
SEPARATION_OUTPUT_DIR = OUTPUT_DIR / "separations"

SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg"}
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
