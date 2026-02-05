# Packaging (Windows installer / macOS .app)

This repo already uses **Nuitka** in GitHub Actions (`.github/workflows/build.yml`) to build a standalone GUI app.

## Option A: Use GitHub Actions (recommended)

1. Push to `main`/`dev` (or run `build musicdown` via `workflow_dispatch`).
2. Download the build artifacts:
   - Windows: a zip containing the standalone folder
   - Linux/macOS: a zip containing the standalone folder / app bundle (after CI update)

## Option B: Build locally with `uv` + Nuitka

### Prerequisites

- Python: `>=3.11,<3.13`
- `uv` installed
- Windows: MSVC Build Tools or MinGW64 (Nuitka needs a C compiler)
- macOS: Xcode Command Line Tools (`xcode-select --install`)

### 1) Install dependencies

```bash
uv sync --frozen
```

### 2) Build a standalone GUI app

Windows (standalone folder):

```powershell
uv run python -m nuitka --mode=standalone --enable-plugin=pyqt6 --windows-console-mode=disable --windows-icon-from-ico=ui/icon.ico --include-data-dir=ui=ui --output-dir=build main.py
```

macOS (`.app` bundle):

```bash
uv run python -m nuitka \
  --mode=app \
  --enable-plugin=pyqt6 \
  --include-data-dir=ui=ui \
  --output-dir=build \
  main.py
```

Notes:
- You can't build a Windows `.exe` from Linux/WSL. Use GitHub Actions or run the Windows build on Windows.
- For macOS app icon, Nuitka supports `--macos-app-icon=icon.png` / `icon.icns` (PNG/ICNS).
- `--include-data-dir=ui=ui` is required to ship `ui/theme.qss` and `ui/icons/*.svg`.

## Windows: create an installer (`.exe`) with Inno Setup

This repo includes an Inno Setup template: `packaging/windows/musicdown.iss`.

1. Install Inno Setup on Windows.
2. Build the standalone folder with Nuitka (above), so you get `build/main.dist/`.
3. Compile the installer:

```powershell
iscc /DMyAppVersion=2026.02.05 /DMyAppSourceDir="build\main.dist" packaging\windows\musicdown.iss
```

The installer will be generated under `upload/` (configurable in the `.iss` file).

## macOS: distribution notes

- For local use, zipping the `.app` is enough.
- For distribution outside your machine, you will need code signing + notarization.
