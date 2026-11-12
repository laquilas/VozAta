[CustomMessages]
; (first line: this file is included right after the [Code] of speakers.iss)
; Maintenance for both installers (phase 67). On a PC that already has the product, the setup
; offers Update (a newer version) or Reinstall (the same version), which replace the program
; and keep every meeting, recording and setting, and Remove, with an unticked "Also delete my
; data" option (confirmed). Installing an older version over a newer one asks first (silent:
; refused unless /ALLOWDOWNGRADE). The uninstaller asks whether to delete the data, "No" being
; the default; a silent uninstall keeps it unless /DELETEDATA is given (/KEEPDATA never asks).
; The data is deleted by `vozata-engine data erase --yes`, run where the engine reads its .env,
; so the paths the user set (DATABASE_PATH, OUTPUT_DIR) are the ones deleted.
; The including script defines ThisAppId (its AppId, single braces), ProductName,
; SpeakersWorkDir (the settings folder) and OtherAppId; SettingsHoldsOther when the settings
; folder also holds the other product's (VozAta: %APPDATA%\VozAta\worker).

en.MaintenanceTitle=Already installed
en.MaintenanceDescription=Version %1 is installed on this PC. What do you want to do?
en.MaintenanceUpdate=Update to version %1 (keeps your meetings, recordings and settings)
en.MaintenanceReinstall=Reinstall version %1 (keeps your meetings, recordings and settings)
en.MaintenanceRemove=Remove %1 from this PC
en.MaintenanceDeleteData=Also delete my data (meetings, recordings, settings, downloads)
en.MaintenanceDeleteConfirm=This permanently deletes every meeting, recording and setting of %1 on this PC. Continue?
en.MaintenanceRemoved=%1 was removed.
en.MaintenanceRemoveFailed=The uninstaller could not be started: %1
en.DowngradeQuestion=A newer version of %1 (%2) is installed. Install the older version %3 instead? Your data is kept.
en.UninstallDeleteData=Also delete your %1 data (meetings, recordings, settings and downloaded components)?%n%nChoose No to keep it for a later installation.
ptbr.MaintenanceTitle=Já instalado
ptbr.MaintenanceDescription=A versão %1 está instalada neste PC. O que você quer fazer?
ptbr.MaintenanceUpdate=Atualizar para a versão %1 (mantém suas reuniões, gravações e configurações)
ptbr.MaintenanceReinstall=Reinstalar a versão %1 (mantém suas reuniões, gravações e configurações)
ptbr.MaintenanceRemove=Remover o %1 deste PC
ptbr.MaintenanceDeleteData=Apagar também os meus dados (reuniões, gravações, configurações, downloads)
ptbr.MaintenanceDeleteConfirm=Isto apaga para sempre todas as reuniões, gravações e configurações do %1 neste PC. Continuar?
ptbr.MaintenanceRemoved=O %1 foi removido.
ptbr.MaintenanceRemoveFailed=Não foi possível iniciar o desinstalador: %1
ptbr.DowngradeQuestion=Uma versão mais nova do %1 (%2) está instalada. Instalar a versão anterior %3 mesmo assim? Seus dados são mantidos.
ptbr.UninstallDeleteData=Apagar também os seus dados do %1 (reuniões, gravações, configurações e componentes baixados)?%n%nEscolha Não para mantê-los para uma próxima instalação.
es.MaintenanceTitle=Ya instalado
es.MaintenanceDescription=La versión %1 está instalada en este PC. ¿Qué quieres hacer?
es.MaintenanceUpdate=Actualizar a la versión %1 (conserva tus reuniones, grabaciones y ajustes)
es.MaintenanceReinstall=Reinstalar la versión %1 (conserva tus reuniones, grabaciones y ajustes)
es.MaintenanceRemove=Quitar %1 de este PC
es.MaintenanceDeleteData=Borrar también mis datos (reuniones, grabaciones, ajustes, descargas)
es.MaintenanceDeleteConfirm=Esto borra para siempre todas las reuniones, grabaciones y ajustes de %1 en este PC. ¿Continuar?
es.MaintenanceRemoved=%1 se ha quitado.
es.MaintenanceRemoveFailed=No se pudo iniciar el desinstalador: %1
es.DowngradeQuestion=Hay instalada una versión más nueva de %1 (%2). ¿Instalar igualmente la versión anterior %3? Tus datos se conservan.
es.UninstallDeleteData=¿Borrar también tus datos de %1 (reuniones, grabaciones, ajustes y componentes descargados)?%n%nElige No para conservarlos para una próxima instalación.

[Code]
var
  MaintenancePage: TWizardPage;
  UpdateButton: TNewRadioButton;
  RemoveButton: TNewRadioButton;
  DeleteDataBox: TNewCheckBox;
  InstalledVersion: String;
  Removed: Boolean;
  UninstallDeleteData: Boolean;

function MaintenanceKey(): String;
begin
  Result := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#ThisAppId}_is1';
end;

function HasSwitch(Name: String): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), Name) = 0 then
    begin
      Result := True;
      Exit;
    end;
end;

{ < 0 when A is older than B, 0 when equal, > 0 when newer }
function CompareVersions(A, B: String): Integer;
var
  PackedA, PackedB: Int64;
begin
  if StrToVersion(A, PackedA) and StrToVersion(B, PackedB) then
    Result := ComparePackedVersion(PackedA, PackedB)
  else
    Result := CompareText(A, B);
end;

function IsReinstall(): Boolean;
begin
  Result := (InstalledVersion <> '') and (CompareVersions(InstalledVersion, '{#AppVersion}') = 0);
end;

<event('InitializeSetup')>
function MaintenanceInitializeSetup(): Boolean;
begin
  Result := True;
  InstalledVersion := '';
  RegQueryStringValue(HKCU, MaintenanceKey(), 'DisplayVersion', InstalledVersion);
  if (InstalledVersion <> '') and (CompareVersions(InstalledVersion, '{#AppVersion}') > 0)
    and not HasSwitch('/ALLOWDOWNGRADE') then
    Result := SuppressibleMsgBox(
      FmtMessage(CustomMessage('DowngradeQuestion'), ['{#ProductName}', InstalledVersion, '{#AppVersion}']),
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES;
end;

procedure MaintenanceChoiceChanged(Sender: TObject);
begin
  DeleteDataBox.Enabled := RemoveButton.Checked;
  if not RemoveButton.Checked then
    DeleteDataBox.Checked := False;
end;

<event('InitializeWizard')>
procedure MaintenanceInitializeWizard();
begin
  if InstalledVersion = '' then
    Exit;
  MaintenancePage := CreateCustomPage(wpWelcome, CustomMessage('MaintenanceTitle'),
    FmtMessage(CustomMessage('MaintenanceDescription'), [InstalledVersion]));

  UpdateButton := TNewRadioButton.Create(MaintenancePage);
  UpdateButton.Parent := MaintenancePage.Surface;
  UpdateButton.Top := 0;
  UpdateButton.Width := MaintenancePage.SurfaceWidth;
  UpdateButton.Height := ScaleY(20);
  if IsReinstall() then
    UpdateButton.Caption := FmtMessage(CustomMessage('MaintenanceReinstall'), ['{#AppVersion}'])
  else
    UpdateButton.Caption := FmtMessage(CustomMessage('MaintenanceUpdate'), ['{#AppVersion}']);
  UpdateButton.Checked := True;
  UpdateButton.OnClick := @MaintenanceChoiceChanged;

  RemoveButton := TNewRadioButton.Create(MaintenancePage);
  RemoveButton.Parent := MaintenancePage.Surface;
  RemoveButton.Top := UpdateButton.Top + ScaleY(32);
  RemoveButton.Width := MaintenancePage.SurfaceWidth;
  RemoveButton.Height := ScaleY(20);
  RemoveButton.Caption := FmtMessage(CustomMessage('MaintenanceRemove'), ['{#ProductName}']);
  RemoveButton.OnClick := @MaintenanceChoiceChanged;

  DeleteDataBox := TNewCheckBox.Create(MaintenancePage);
  DeleteDataBox.Parent := MaintenancePage.Surface;
  DeleteDataBox.Top := RemoveButton.Top + ScaleY(28);
  DeleteDataBox.Left := ScaleX(20);
  DeleteDataBox.Width := MaintenancePage.SurfaceWidth - ScaleX(20);
  DeleteDataBox.Height := ScaleY(20);
  DeleteDataBox.Caption := CustomMessage('MaintenanceDeleteData');
  DeleteDataBox.Checked := False;
  DeleteDataBox.Enabled := False;
end;

function RunUninstaller(DeleteData: Boolean): Boolean;
var
  Uninstaller, Params: String;
  Code, Waited: Integer;
begin
  Result := False;
  Uninstaller := '';
  RegQueryStringValue(HKCU, MaintenanceKey(), 'UninstallString', Uninstaller);
  Uninstaller := RemoveQuotes(Uninstaller);
  if DeleteData then
    Params := '/SILENT /NORESTART /DELETEDATA'
  else
    Params := '/SILENT /NORESTART /KEEPDATA';
  if not Exec(Uninstaller, Params, '', SW_SHOW, ewWaitUntilTerminated, Code) then
  begin
    MsgBox(FmtMessage(CustomMessage('MaintenanceRemoveFailed'), [SysErrorMessage(Code)]), mbError, MB_OK);
    Exit;
  end;
  { the uninstaller goes on in a copy of itself: wait until it has unregistered the product }
  Waited := 0;
  while RegKeyExists(HKCU, MaintenanceKey()) and (Waited < 600) do
  begin
    Sleep(500);
    Waited := Waited + 1;
  end;
  Result := True;
end;

<event('NextButtonClick')>
function MaintenanceNextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (MaintenancePage = nil) or (CurPageID <> MaintenancePage.ID) or not RemoveButton.Checked then
    Exit;
  Result := False;
  if DeleteDataBox.Checked and (MsgBox(
      FmtMessage(CustomMessage('MaintenanceDeleteConfirm'), ['{#ProductName}']),
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2) <> IDYES) then
    Exit;
  if not RunUninstaller(DeleteDataBox.Checked) then
    Exit;
  MsgBox(FmtMessage(CustomMessage('MaintenanceRemoved'), ['{#ProductName}']), mbInformation, MB_OK);
  Removed := True;
  WizardForm.Close;
end;

<event('CancelButtonClick')>
procedure MaintenanceCancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
begin
  if Removed then
    Confirm := False;
end;

<event('CurStepChanged')>
procedure MaintenanceCurStepChanged(CurStep: TSetupStep);
begin
  { an update or a reinstall starts from clean program folders: no file of an older build stays }
  if (CurStep = ssInstall) and (InstalledVersion <> '') then
  begin
    DelTree(ExpandConstant('{app}\engine'), True, True, True);
    DelTree(ExpandConstant('{app}\recorder'), True, True, True);
  end;
end;

<event('CurUninstallStepChanged')>
procedure MaintenanceUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Params: String;
  Code: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    if HasSwitch('/DELETEDATA') then
      UninstallDeleteData := True
    else if HasSwitch('/KEEPDATA') or UninstallSilent then
      UninstallDeleteData := False
    else
      UninstallDeleteData := MsgBox(
        FmtMessage(CustomMessage('UninstallDeleteData'), ['{#ProductName}']),
        mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
    if UninstallDeleteData then
    begin
      { the recorder holds the live recordings open: stop it (it refuses while recording) }
      Exec(ExpandConstant('{app}\recorder\vozata-recorder.exe'), '--stop', '', SW_HIDE,
        ewWaitUntilTerminated, Code);
      Params := 'data erase --yes';
      if OtherProductInstalled() then
        Params := Params + ' --keep-runtimes';
      Exec(ExpandConstant('{app}\engine\vozata-engine.exe'), Params,
        ExpandConstant('{#SpeakersWorkDir}'), SW_HIDE, ewWaitUntilTerminated, Code);
    end;
  end;
  if (CurUninstallStep = usPostUninstall) and UninstallDeleteData then
  begin
#ifdef SettingsHoldsOther
    if OtherProductInstalled() then
      DelTree(ExpandConstant('{#SpeakersWorkDir}\*'), False, True, False)
    else
#endif
      DelTree(ExpandConstant('{#SpeakersWorkDir}'), True, True, True);
  end;
end;
