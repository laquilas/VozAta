; VozAta Worker installer (Inno Setup 6 or 7, phase 57): only the worker app and the engine, for
; the GPU PC that transcribes, identifies speakers and translates for the other PCs of the
; network. Built by packaging/build.ps1:
;   iscc /DAppVersion=1.0.0 /DBuildDir=<repo>\build packaging\installer-worker.iss
; Per-user install (no administrator rights). The uninstaller keeps %APPDATA%\VozAta\worker (the
; worker's .env: token, id, HF_TOKEN).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef BuildDir
  #define BuildDir "..\build"
#endif
#define SpeakersWorkDir "{userappdata}\VozAta\worker"
; installer.iss
#define OtherAppId "{6E0B9F4A-2C5D-4E8B-9A1F-3D7C5B2E8A61}"

[Setup]
AppId={{2BA26749-AC77-48E5-8189-E8B4F542489D}
AppName=VozAta Worker
AppVersion={#AppVersion}
AppVerName=VozAta Worker {#AppVersion}
AppPublisher=VozAta
AppPublisherURL=https://github.com/laquilas/VozAta
DefaultDirName={localappdata}\Programs\VozAta Worker
DefaultGroupName=VozAta
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#BuildDir}\installer
OutputBaseFilename=VozAta-Worker-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\desktop\windows\vozata.ico
UninstallDisplayIcon={app}\VozAta.Worker.exe
CloseApplications=yes

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[CustomMessages]
en.SpeakersTask=Download speaker identification now (about 3 GB; also later in VozAta Worker)
ptbr.SpeakersTask=Baixar a identificação de participantes agora (cerca de 3 GB; também depois, no VozAta Worker)
es.SpeakersTask=Descargar la identificación de participantes ahora (unos 3 GB; también después, en VozAta Worker)

#include "speakers.iss"

[Files]
Source: "{#BuildDir}\worker-ui\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#BuildDir}\dist\vozata-engine\*"; DestDir: "{app}\engine"; Flags: recursesubdirs createallsubdirs ignoreversion

[Dirs]
Name: "{userappdata}\VozAta\worker"; Flags: uninsneveruninstall

[Icons]
Name: "{userprograms}\VozAta Worker"; Filename: "{app}\VozAta.Worker.exe"; WorkingDir: "{app}"; IconFilename: "{app}\VozAta.Worker.exe"

[Registry]
; "Start with Windows" of VozAta Worker writes this value; uninstalling removes it
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "VozAta Worker"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\VozAta.Worker.exe"; Description: "{cm:LaunchProgram,VozAta Worker}"; Flags: nowait postinstall skipifsilent
