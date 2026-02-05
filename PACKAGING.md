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
uv run python -m nuitka --mode=standalone --enable-plugin=pyside6 --windows-console-mode=disable --windows-icon-from-ico=ui/icon.ico --include-data-dir=ui=ui --output-dir=build main.py
```

macOS (`.app` bundle):

```bash
uv run python -m nuitka \
  --mode=app \
  --enable-plugin=pyside6 \
  --macos-app-name=musicdown \
  --output-filename=musicdown \
  --include-data-dir=ui=ui \
  --output-dir=build \
  main.py
```

Notes:
- You can't build a Windows `.exe` from Linux/WSL. Use GitHub Actions or run the Windows build on Windows.
- For macOS app icon, Nuitka supports `--macos-app-icon=icon.png` / `icon.icns` (PNG/ICNS).
- If you use a PNG icon on macOS, Nuitka may require `imageio` to convert it; using an `.icns` avoids that.
- `--include-data-dir=ui=ui` is required to ship `ui/theme.qss` and `ui/icons/*.svg`.
- Compiled app logs are written to `~/.musicdown/logs/` by default.
- If the packaged GUI looks “unstyled”, check the logs for `Theme file not found` and verify the `ui/` directory is included in your build output.

## Option C: Build with PyInstaller (experimental)

If you prefer PyInstaller, you must also ship the `ui/` assets:

- macOS/Linux:
  ```bash
  pyinstaller --noconsole --add-data "ui:ui" main.py
  ```
- Windows (note the `;` separator):
  ```powershell
  pyinstaller --noconsole --add-data "ui;ui" main.py
  ```

## Windows: create an installer (`.exe`) with Inno Setup

This repo includes an Inno Setup template: `packaging/windows/musicdown.iss`.

1. Install Inno Setup on Windows.
2. Build the standalone folder with Nuitka (above), so you get `build/main.dist/`.
3. Compile the installer:

```powershell
iscc /DMyAppVersion=2026.02.05 packaging\windows\musicdown.iss
```

The installer will be generated under `upload/` (configurable in the `.iss` file).

## macOS: distribution notes

- CI builds **two** macOS artifacts:
  - `...-macos-amd64.zip` → Intel Macs (x86_64)
  - `...-macos-arm64.zip` → Apple Silicon (arm64)
- If the `.app` won’t open after downloading/unzipping, it’s usually Gatekeeper quarantine. For local testing:
  - Right click the app → **Open**
  - Or remove quarantine in Terminal:
    ```bash
    xattr -dr com.apple.quarantine /path/to/musicdown.app
    ```
- To inspect what’s wrong (useful when reporting an issue):
  ```bash
  spctl -a -vv /path/to/musicdown.app || true
  codesign -dv --verbose=4 /path/to/musicdown.app 2>&1 | head -n 50
  file /path/to/musicdown.app/Contents/MacOS/*
  ```
- For proper distribution to other machines, you will need **Developer ID** code signing + notarization.
