#ifndef AppVersion
  #define AppVersion "0.5.2"
#endif
#define AppExe "BiliRemote-Desktop.exe"
#ifndef AppSourcePath
  #define AppSourcePath "..\dist"
#endif
#ifndef AppIdentity
  #define AppIdentity "BiliGestureRemote"
#endif
#ifndef AppIdentifier
  #define AppIdentifier "{{36D44CC8-86ED-4E16-92B9-C3F073F4EE78}"
#endif
#ifndef AppLabel
  #define AppLabel "哔哩哔哩手势遥控"
#endif
#ifndef UserDataPath
  #define UserDataPath "{localappdata}\BiliGestureRemote"
#endif
#ifndef OutputPath
  #define OutputPath "..\dist"
#endif

[Setup]
AppId={#AppIdentifier}
AppName={#AppLabel}
AppVersion={#AppVersion}
AppPublisher=BiliGestureRemote
DefaultDirName={localappdata}\Programs\{#AppIdentity}
UsePreviousAppDir=yes
UsePreviousTasks=no
DisableDirPage=auto
DefaultGroupName={#AppLabel}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#OutputPath}
OutputBaseFilename=BiliRemote-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\desktop\assets\bili-remote.ico
UninstallDisplayIcon={app}\{#AppExe}
DisableProgramGroupPage=yes
CloseApplications=no
RestartApplications=no
; The app is closed by PrepareToInstall. AppMutex would block before that hook.
SetupMutex={#AppIdentity}-Installer

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "autostart"; Description: "登录 Windows 后自动启动（可在软件设置中修改）"; Flags: unchecked
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: unchecked

[Files]
Source: "{#AppSourcePath}\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\*"; DestDir: "{app}\docs"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "firewall-cleanup.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userprograms}\{#AppLabel}"; Filename: "{app}\{#AppExe}"
Name: "{userdesktop}\{#AppLabel}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "打开电脑端"; Flags: nowait postinstall skipifsilent; Check: ShouldOfferLaunch

[UninstallDelete]
Type: files; Name: "{#UserDataPath}\trust.json"
Type: files; Name: "{#UserDataPath}\trust.tmp"
Type: files; Name: "{#UserDataPath}\settings.json"
Type: files; Name: "{#UserDataPath}\settings.tmp"
Type: files; Name: "{#UserDataPath}\remote.log"
Type: files; Name: "{#UserDataPath}\remote.log.1"
Type: files; Name: "{#UserDataPath}\remote.log.2"
Type: filesandordirs; Name: "{#UserDataPath}\browser-profile"
Type: dirifempty; Name: "{#UserDataPath}"

[Code]
const
  InstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#AppIdentifier}_is1';
  StartupKey = 'Software\Microsoft\Windows\CurrentVersion\Run';
  ApprovalKey = 'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run';

var
  PreviousDirectory: String;
  IsUpgrade, InitialAutostart, InitialDesktopIcon, CompanionWasRunning, StopAttempted: Boolean;
  TaskSelectionExplicit, TaskDefaultsApplied, CompanionLaunchRequested: Boolean;

function VersionIsNewer(Existing, Candidate: String): Boolean;
var
  Part, ExistingNumber, CandidateNumber, Dot: Integer;
begin
  Result := False;
  for Part := 1 to 4 do begin
    Dot := Pos('.', Existing);
    if Dot = 0 then Dot := Length(Existing) + 1;
    ExistingNumber := StrToIntDef(Copy(Existing, 1, Dot - 1), 0);
    Delete(Existing, 1, Dot);
    Dot := Pos('.', Candidate);
    if Dot = 0 then Dot := Length(Candidate) + 1;
    CandidateNumber := StrToIntDef(Copy(Candidate, 1, Dot - 1), 0);
    Delete(Candidate, 1, Dot);
    if ExistingNumber <> CandidateNumber then begin
      Result := ExistingNumber > CandidateNumber;
      exit;
    end;
  end;
end;

function InitializeSetup: Boolean;
var
  ExistingVersion: String;
begin
  Result := True;
  IsUpgrade := RegQueryStringValue(HKCU, ExpandConstant(InstallKey), 'InstallLocation', PreviousDirectory);
  if IsUpgrade and RegQueryStringValue(HKCU, ExpandConstant(InstallKey), 'DisplayVersion', ExistingVersion) then
    if VersionIsNewer(ExistingVersion, '{#AppVersion}') then begin
      SuppressibleMsgBox('已安装更新的版本 ' + ExistingVersion + '，不能用此安装包降级。请安装相同或更高版本。', mbError, MB_OK, IDOK);
      Result := False;
    end;
end;

function CurrentAutostart: Boolean;
var
  Command: String;
  Approval: AnsiString;
begin
  Result := RegQueryStringValue(HKCU, StartupKey, '{#AppIdentity}', Command) and (Command <> '');
  if RegQueryBinaryValue(HKCU, ApprovalKey, '{#AppIdentity}', Approval) and (Length(Approval) > 0) then
    if (Ord(Approval[1]) = 3) or (Ord(Approval[1]) = 7) then Result := False;
end;

procedure InitializeWizard;
var
  Index: Integer;
begin
  InitialAutostart := CurrentAutostart;
  InitialDesktopIcon := FileExists(ExpandConstant('{userdesktop}\{#AppLabel}.lnk'));
  if IsUpgrade then begin
    { Keep the registered directory even if a different /DIR was supplied. }
    WizardForm.DirEdit.Text := PreviousDirectory;
    for Index := 1 to ParamCount do
      if (Pos('/TASKS=', Uppercase(ParamStr(Index))) = 1) or
         (Pos('/MERGETASKS=', Uppercase(ParamStr(Index))) = 1) then TaskSelectionExplicit := True;
  end;
end;

procedure InitializeUpgradeTasks;
var
  Tasks: String;
begin
  if (not IsUpgrade) or TaskDefaultsApplied then exit;
  TaskDefaultsApplied := True;
  if TaskSelectionExplicit then exit;
  Tasks := '';
  if InitialAutostart then Tasks := 'autostart';
  if InitialDesktopIcon then begin
    if Tasks <> '' then Tasks := Tasks + ',';
    Tasks := Tasks + 'desktopicon';
  end;
  WizardSelectTasks(Tasks);
  Log('Restored current upgrade task settings: ' + WizardSelectedTasks(False));
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  { Inno populates task defaults after InitializeWizard. }
  if (CurPageID = wpSelectTasks) or (CurPageID = wpReady) or (CurPageID = wpPreparing) then
    InitializeUpgradeTasks;
end;

function ShouldOfferLaunch: Boolean;
begin
  Result := not CompanionWasRunning;
end;

function OpenExclusiveFile(FileName: String; Access, Sharing, Security, Creation, Flags, Template: LongWord): LongInt;
  external 'CreateFileW@kernel32.dll stdcall';
function CloseNativeHandle(Handle: LongInt): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';

function WaitForExecutableRelease: Boolean;
var
  Attempt, Handle: Integer;
  FileName: String;
begin
  Result := True;
  FileName := ExpandConstant('{app}\{#AppExe}');
  if not FileExists(FileName) then exit;
  for Attempt := 1 to 100 do begin
    Handle := OpenExclusiveFile(FileName, $80000000, 0, 0, 3, 0, 0);
    if Handle <> -1 then begin
      CloseNativeHandle(Handle);
      exit;
    end;
    Sleep(100);
  end;
  Result := False;
end;

function StopCompanion: Boolean;
var
  ExitCode, Attempt: Integer;
begin
  Result := True;
  if CheckForMutexes('{#AppIdentity}') then begin
    if FileExists(ExpandConstant('{app}\{#AppExe}')) then
      Exec(ExpandConstant('{app}\{#AppExe}'), '--quit', '', SW_HIDE, ewWaitUntilTerminated, ExitCode);
    for Attempt := 1 to 100 do begin
      if not CheckForMutexes('{#AppIdentity}') then begin
        Result := WaitForExecutableRelease;
        exit;
      end;
      Sleep(100);
    end;
    Result := False;
  end else Result := WaitForExecutableRelease;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  InitializeUpgradeTasks;
  if IsUpgrade then WizardForm.DirEdit.Text := PreviousDirectory;
  if not StopAttempted then begin
    CompanionWasRunning := CheckForMutexes('{#AppIdentity}');
    StopAttempted := True;
  end;
  if StopCompanion then Result := ''
  else Result := '电脑端仍在运行，请先从托盘退出软件后重试。';
end;

procedure RestoreCompanion;
var
  ExitCode: Integer;
begin
  if StopAttempted and CompanionWasRunning and not CompanionLaunchRequested then
    if not CheckForMutexes('{#AppIdentity}') and FileExists(ExpandConstant('{app}\{#AppExe}')) then
      CompanionLaunchRequested := Exec(ExpandConstant('{app}\{#AppExe}'), '--background', '', SW_HIDE, ewNoWait, ExitCode);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  SelectedAutostart: Boolean;
begin
  if CurStep = ssPostInstall then begin
    SelectedAutostart := WizardIsTaskSelected('autostart');
    { Preserve the actual app/Task Manager setting, not the previous installer task. }
    if (not IsUpgrade) or TaskSelectionExplicit or (SelectedAutostart <> InitialAutostart) then begin
      if SelectedAutostart then
        RegWriteStringValue(HKCU, StartupKey, '{#AppIdentity}', '"' + ExpandConstant('{app}\{#AppExe}') + '" --background')
      else RegDeleteValue(HKCU, StartupKey, '{#AppIdentity}');
      RegDeleteValue(HKCU, ApprovalKey, '{#AppIdentity}');
      RegDeleteValue(HKCU, ApprovalKey + '32', '{#AppIdentity}');
    end;
    if not WizardIsTaskSelected('desktopicon') then
      DeleteFile(ExpandConstant('{userdesktop}\{#AppLabel}.lnk'));
  end;
  if CurStep = ssDone then RestoreCompanion;
end;

procedure DeinitializeSetup;
begin
  { Also restore the stopped instance if installation was cancelled or failed. }
  RestoreCompanion;
end;

function InitializeUninstall: Boolean;
begin
  Result := StopCompanion;
  if not Result then SuppressibleMsgBox('请先从托盘退出电脑端，然后重新卸载。', mbError, MB_OK, IDOK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Shell, Script, Parameters: String;
  ExitCode, Attempt: Integer;
begin
  if CurUninstallStep = usUninstall then begin
    { Remove only files shipped by the previous extension-based version. }
    DeleteFile(ExpandConstant('{app}\browser-extension\background.js'));
    DeleteFile(ExpandConstant('{app}\browser-extension\content.js'));
    DeleteFile(ExpandConstant('{app}\browser-extension\manifest.json'));
    DeleteFile(ExpandConstant('{app}\browser-extension\player.js'));
    DeleteFile(ExpandConstant('{app}\browser-extension\popup.html'));
    DeleteFile(ExpandConstant('{app}\browser-extension\popup.js'));
    RemoveDir(ExpandConstant('{app}\browser-extension'));
    { This also removes a startup entry enabled later through the app UI. }
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#AppIdentity}');
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run', '{#AppIdentity}');
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run32', '{#AppIdentity}');
    Shell := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
    Script := ExpandConstant('{app}\firewall-cleanup.ps1');
    Parameters := '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + Script + '" -Program "' + ExpandConstant('{app}\{#AppExe}') + '"';
    if Exec(Shell, Parameters + ' -Query', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) and (ExitCode = 10) then begin
      { Administrator permission is required only when this app has firewall rules. }
      if UninstallSilent then begin
        { Silent uninstall never hangs waiting for an interactive UAC prompt. }
        if not Exec(Shell, Parameters, '', SW_HIDE, ewWaitUntilTerminated, ExitCode) or (ExitCode <> 0) then
          Log('程序防火墙规则清理未完成，需要管理员权限。');
      end else begin
        if not ShellExec('runas', Shell, Parameters, '', SW_HIDE, ewWaitUntilTerminated, ExitCode) or (ExitCode <> 0) then
          SuppressibleMsgBox('程序和本机数据将被移除，但防火墙规则清理未完成。可在 Windows 防火墙中删除指向该程序的规则。', mbInformation, MB_OK, IDOK);
      end;
    end;
  end;
  if CurUninstallStep = usPostUninstall then begin
    { The one-file runtime's launcher can release its image after the app mutex. }
    for Attempt := 1 to 100 do begin
      if not FileExists(ExpandConstant('{app}\{#AppExe}')) then break;
      if DeleteFile(ExpandConstant('{app}\{#AppExe}')) then break;
      Sleep(100);
    end;
    RemoveDir(ExpandConstant('{app}'));
    if FileExists(ExpandConstant('{app}\{#AppExe}')) then
      SuppressibleMsgBox('程序仍被其他进程占用，部分文件尚未删除。退出占用程序后可删除剩余文件。', mbInformation, MB_OK, IDOK);
  end;
end;
