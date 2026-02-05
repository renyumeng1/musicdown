; Inno Setup script for musicdown (Nuitka standalone folder -> installer)
;
; Compile (PowerShell):
;   iscc /DMyAppVersion=2026.02.05 /DMyAppSourceDir="build\musicdown" packaging\windows\musicdown.iss
;
; If your executable name is not "main.exe", also pass:
;   /DMyAppExeName="musicdown.exe"

#define MyAppName "musicdown"
#define MyAppPublisher "musicdown"

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#ifndef MyAppSourceDir
  #define MyAppSourceDir "..\..\build\musicdown"
#endif

#ifndef MyAppExeName
  #define MyAppExeName "main.exe"
#endif

[Setup]
AppId={{B2C9D18E-1E0D-4A37-9AC1-1A3B0D3A0D5C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
WizardStyle=modern
OutputDir=..\..\upload
OutputBaseFilename={#MyAppName}-{#MyAppVersion}-setup
SetupIconFile=..\..\ui\icon.ico
Compression=lzma2
SolidCompression=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "{#MyAppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

