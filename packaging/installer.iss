; VozAta installer (Inno Setup 6 or 7), the meeting app for every PC. Built by packaging/build.ps1:
;   iscc /DAppVersion=1.0.0 /DBuildDir=<repo>\build packaging\installer.iss
; Per-user install (no administrator rights). The uninstaller removes the program files and keeps
; %APPDATA%\VozAta\.env (settings) and Documents\VozAta (recordings). Speaker identification is
; downloaded on this PC (phase 56). VozAta Worker, for the GPU PC, has its own installer
; (installer-worker.iss, phase 57).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef BuildDir
  #define BuildDir "..\build"
#endif
#define SpeakersWorkDir "{userappdata}\VozAta"
; installer-worker.iss
#define OtherAppId "{2BA26749-AC77-48E5-8189-E8B4F542489D}"

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

[CustomMessages]
en.SpeakersTask=Download speaker identification now (about 3 GB; also later by running this setup again)
ptbr.SpeakersTask=Baixar a identificação de participantes agora (cerca de 3 GB; também depois, rodando este instalador de novo)
es.SpeakersTask=Descargar la identificación de participantes ahora (unos 3 GB; también después, ejecutando este instalador otra vez)

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

#include "gpu.iss"
#include "speakers.iss"

[InstallDelete]
; up to 0.1.0 this installer also carried VozAta Worker (phase 57 split it out)
Type: files; Name: "{app}\VozAta.Worker.exe"
Type: files; Name: "{app}\VozAta.Worker.pdb"
Type: files; Name: "{app}\worker.settings.json"
Type: files; Name: "{userprograms}\VozAta Worker.lnk"

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
