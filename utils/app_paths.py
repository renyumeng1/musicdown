import os
import sys
from pathlib import Path


APP_NAME = "musicdown"


def is_compiled() -> bool:
    try:
        __compiled__  # type: ignore[name-defined]
        return True
    except NameError:
        return bool(getattr(sys, "frozen", False))


def _find_repo_root(start_dir: Path) -> Path | None:
    for candidate in (start_dir, *start_dir.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return None


def get_app_dir() -> Path:
    try:
        return Path(__compiled__.containing_dir)  # type: ignore[name-defined]
    except NameError:
        argv_path = Path(sys.argv[0]).resolve()
        argv_dir = argv_path.parent

        repo_root = _find_repo_root(argv_dir)
        if repo_root is not None:
            return repo_root

        module_root = _find_repo_root(Path(__file__).resolve().parent)
        if module_root is not None:
            return module_root

        return argv_dir


def get_user_data_dir() -> Path:
    override = os.getenv("MUSICDOWN_HOME") or os.getenv("MUSICDOWN_CONFIG_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / f".{APP_NAME}"


def _portable_requested() -> bool:
    return os.getenv("MUSICDOWN_PORTABLE", "").strip().lower() in {"1", "true", "yes"}


def get_app_data_dir() -> Path:
    if _portable_requested():
        return get_app_dir()

    # Compiled distributions should always write to a user-writable location by default.
    if is_compiled():
        return get_user_data_dir()

    # During development, keep configs next to the project if possible.
    app_dir = get_app_dir()
    try:
        test_file = app_dir / ".write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
        return app_dir
    except Exception:
        return get_user_data_dir()


def get_config_dir() -> Path:
    return get_app_data_dir() / "config"


def get_config_file_path() -> Path:
    return get_config_dir() / "config.json"


def get_credential_file_path() -> Path:
    return get_config_dir() / "credential.json"


def get_gui_config_file_path() -> Path:
    return get_app_data_dir() / "config.json"


def get_resource_path(*parts: str) -> Path:
    app_dir = get_app_dir()
    candidates: list[Path] = []

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass))

    if sys.platform == "darwin":
        macos_resources_dir = app_dir.parent / "Resources"
        if macos_resources_dir.is_dir():
            candidates.append(macos_resources_dir)

    candidates.append(app_dir)

    nuitka_onefile_dir = os.getenv("NUITKA_ONEFILE_DIRECTORY")
    if nuitka_onefile_dir:
        candidates.append(Path(nuitka_onefile_dir))

    try:
        argv_dir = Path(sys.argv[0]).resolve().parent
        candidates.append(argv_dir)
    except Exception:
        pass

    for base_dir in candidates:
        candidate_path = base_dir.joinpath(*parts)
        if candidate_path.exists():
            return candidate_path

    return candidates[0].joinpath(*parts)
