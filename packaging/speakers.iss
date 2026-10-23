; Speaker identification for both installers (phases 56, 57): an optional task downloads the
; speaker runtime into %LOCALAPPDATA%\VozAta\speakers (`vozata-engine speakers install`), and the
; uninstaller removes it, and the CUDA libraries of gpu.iss (phase 58), unless the other installer
; (VozAta / VozAta Worker) still uses them.
; The including script defines SpeakersWorkDir (where the engine reads its .env) and OtherAppId (the
; other product's AppId), and the SpeakersTask message (how to download it later differs).

[CustomMessages]
en.SpeakersStatus=Downloading speaker identification (see the console window)...
ptbr.SpeakersStatus=Baixando a identificação de participantes (veja a janela do console)...
es.SpeakersStatus=Descargando la identificación de participantes (mira la ventana de la consola)...

[Tasks]
Name: "speakers"; Description: "{cm:SpeakersTask}"; Flags: unchecked

[Run]
; in a console, which stays open on a failure so the reason can be read
Filename: "{cmd}"; Parameters: "/c """"{app}\engine\vozata-engine.exe"" speakers install || pause"""; WorkingDir: "{#SpeakersWorkDir}"; StatusMsg: "{cm:SpeakersStatus}"; Tasks: speakers; Flags: waituntilterminated

[Code]
function HasNvidiaDriver(): Boolean;
begin
  Result := FileExists(ExpandConstant('{sys}\nvidia-smi.exe'));
end;

function OtherProductInstalled(): Boolean;
begin
  Result := RegKeyExists(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#OtherAppId}_is1');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and not OtherProductInstalled() then
  begin
    DelTree(ExpandConstant('{localappdata}\VozAta\speakers'), True, True, True);
    DelTree(ExpandConstant('{localappdata}\VozAta\cuda'), True, True, True);
  end;
end;
