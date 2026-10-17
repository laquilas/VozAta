; VozAta installer (Inno Setup 6). Built by packaging/build.ps1:
;   iscc /DAppVersion=1.0.0 /DBuildDir=<repo>\build packaging\installer.iss
; Per-user install (no administrator rights). The uninstaller removes the program files and keeps
; %APPDATA%\VozAta\.env (settings) and Documents\VozAta (recordings).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef BuildDir
  #define BuildDir "..\build"
#endif

[Setup]
AppId={{6E0B9F4A-2C5D-4E8B-9A1F-3D7C5B2E8A61}
AppName=VozAta
AppVersion={#AppVersion}
AppVerName=VozAta {#AppVersion}
AppPublisher=VozAta
AppPublisherURL=https://github.com/laquilas/VozAta
DefaultDirName={localappdata}\Programs\VozAta
DefaultGroupName=VozAta
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#BuildDir}\installer
OutputBaseFilename=VozAta-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; relative to this script's folder, so it resolves the same locally and in CI
SetupIconFile=..\assets\desktop\windows\vozata.ico
UninstallDisplayIcon={app}\VozAta.Desktop.exe
CloseApplications=yes

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#BuildDir}\ui\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#BuildDir}\dist\vozata-engine\*"; DestDir: "{app}\engine"; Flags: recursesubdirs createallsubdirs ignoreversion
; first run only: the engine's settings live with the user and survive upgrades and uninstalls
Source: "{#BuildDir}\installed.env"; DestDir: "{userappdata}\VozAta"; DestName: ".env"; Flags: onlyifdoesntexist uninsneveruninstall

[Dirs]
Name: "{userappdata}\VozAta"; Flags: uninsneveruninstall
Name: "{userdocs}\VozAta"; Flags: uninsneveruninstall

[Icons]
Name: "{userprograms}\VozAta"; Filename: "{app}\VozAta.Desktop.exe"; WorkingDir: "{app}"; IconFilename: "{app}\VozAta.Desktop.exe"
Name: "{userdesktop}\VozAta"; Filename: "{app}\VozAta.Desktop.exe"; WorkingDir: "{app}"; IconFilename: "{app}\VozAta.Desktop.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\VozAta.Desktop.exe"; Description: "{cm:LaunchProgram,VozAta}"; Flags: nowait postinstall skipifsilent
