#ifndef AppVersion
  #error AppVersion must be provided by scripts\build_installer.ps1
#endif

#define AppName "JJZero Audio"
#define AppExecutable "JJZero Audio.exe"
#define DistributionDir SourcePath + "..\dist\JJZero Audio"
#ifndef AppMutexName
  #define AppMutexName "JJZeroAudio.E5ED303D5BB24B1E8AA8434C16C4D3AE"
#endif

[Setup]
AppId={{E5ED303D-5BB2-4B1E-8AA8-434C16C4D3AE}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=JJZero
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExecutable}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
PrivilegesRequired=lowest
OutputDir={#SourcePath}..\release
#ifdef VerificationBuild
OutputBaseFilename=JJZero-Audio-{#AppVersion}-Verification-Setup
#else
OutputBaseFilename=JJZero-Audio-{#AppVersion}-Setup
#endif
SetupIconFile={#SourcePath}jjzero.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
DiskSpanning=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[InstallDelete]
Type: files; Name: "{app}\{#AppExecutable}"
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#DistributionDir}\*"; DestDir: "{app}"; Excludes: "runtime\*"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExecutable}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExecutable}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExecutable}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
const
  FileAttributeDirectory = $10;

var
  ManagedRuntimeCanBeDeleted: Boolean;
  ManagedCacheCanBeDeleted: Boolean;
  RuntimePreservationPrepared: Boolean;
  PreservedRuntimeData: Boolean;
  PreservedRuntimePath: String;

function HasCommandLineSwitch(const SwitchName: String): Boolean;
var
  Index: Integer;
begin
  Result := False;
  for Index := 1 to ParamCount do
  begin
    if CompareText(ParamStr(Index), SwitchName) = 0 then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if CheckForMutexes('{#AppMutexName}') and (not HasCommandLineSwitch('/RUN')) then
  begin
    if not WizardSilent then
      MsgBox(
        '{#AppName} is running. Close the application before installing.',
        mbError,
        MB_OK
      );
    Result := False;
  end;
end;

function RuntimeDataRoot: String;
begin
  Result := GetEnv('JJZERO_DATA_ROOT');
  if Result = '' then
    Result := ExpandConstant('{localappdata}\JJZero Audio');
end;

function StorageSettingsFile: String;
begin
  Result := AddBackslash(RuntimeDataRoot) + 'settings\storage.json';
end;

function ReadStoragePath(const Key: String): String;
var
  Content: AnsiString;
  Tail: String;
  Marker: String;
  MarkerPosition: Integer;
  ColonPosition: Integer;
  QuotePosition: Integer;
  EndPosition: Integer;
begin
  Result := '';
  if not LoadStringFromFile(StorageSettingsFile, Content) then
    Exit;
  Marker := '"' + Key + '"';
  MarkerPosition := Pos(Marker, String(Content));
  if MarkerPosition = 0 then
    Exit;
  Tail := Copy(String(Content), MarkerPosition + Length(Marker), MaxInt);
  ColonPosition := Pos(':', Tail);
  if ColonPosition = 0 then
    Exit;
  Tail := Copy(Tail, ColonPosition + 1, MaxInt);
  QuotePosition := Pos('"', Tail);
  if QuotePosition = 0 then
    Exit;
  Tail := Copy(Tail, QuotePosition + 1, MaxInt);
  EndPosition := Pos('"', Tail);
  if EndPosition = 0 then
    Exit;
  Result := Copy(Tail, 1, EndPosition - 1);
  StringChangeEx(Result, '\\', '\', True);
  Result := RemoveBackslashUnlessRoot(Result);
end;

function SamePath(const Left, Right: String): Boolean;
begin
  Result := CompareText(
    RemoveBackslashUnlessRoot(Left),
    RemoveBackslashUnlessRoot(Right)) = 0;
end;

function PathContains(const ParentPath, ChildPath: String): Boolean;
var
  ParentWithSlash: String;
  ChildWithSlash: String;
begin
  ParentWithSlash := Lowercase(AddBackslash(RemoveBackslashUnlessRoot(ParentPath)));
  ChildWithSlash := Lowercase(AddBackslash(RemoveBackslashUnlessRoot(ChildPath)));
  Result := Pos(ParentWithSlash, ChildWithSlash) = 1;
end;

function IsSafeGeneratedRoot(const Candidate: String): Boolean;
var
  WorkspaceRoot: String;
  OutputRoot: String;
begin
  Result := False;
  if Candidate = '' then
    Exit;
  if SamePath(Candidate, ExtractFileDrive(Candidate) + '\') then
    Exit;
  WorkspaceRoot := ReadStoragePath('workspace_root');
  OutputRoot := ReadStoragePath('output_root');
  if (WorkspaceRoot <> '') and PathContains(Candidate, WorkspaceRoot) then
    Exit;
  if (OutputRoot <> '') and PathContains(Candidate, OutputRoot) then
    Exit;
  if PathContains(Candidate, RuntimeDataRoot) then
    Exit;
  Result := True;
end;

function DirectoryHasContents(const Directory: String): Boolean;
var
  Entry: TFindRec;
begin
  Result := False;
  if FindFirst(AddBackslash(Directory) + '*', Entry) then
  begin
    try
      repeat
        if (Entry.Name <> '.') and (Entry.Name <> '..') then
        begin
          Result := True;
          Exit;
        end;
      until not FindNext(Entry);
    finally
      FindClose(Entry);
    end;
  end;
end;

function CopyDirectoryTree(const Source, Destination: String): Boolean;
var
  Entry: TFindRec;
  SourcePath: String;
  DestinationPath: String;
begin
  Result := ForceDirectories(Destination);
  if not Result then
    Exit;

  if FindFirst(AddBackslash(Source) + '*', Entry) then
  begin
    try
      repeat
        if (Entry.Name <> '.') and (Entry.Name <> '..') then
        begin
          SourcePath := AddBackslash(Source) + Entry.Name;
          DestinationPath := AddBackslash(Destination) + Entry.Name;
          if (Entry.Attributes and FileAttributeDirectory) <> 0 then
            Result := CopyDirectoryTree(SourcePath, DestinationPath)
          else
            Result := CopyFile(SourcePath, DestinationPath, False);
          if not Result then
            Exit;
        end;
      until not FindNext(Entry);
    finally
      FindClose(Entry);
    end;
  end;
end;

function UniquePreservationRoot: String;
var
  Base: String;
  Candidate: String;
  Suffix: Integer;
begin
  Base :=
    AddBackslash(RuntimeDataRoot) + 'preserved-runtime\' +
    GetDateTimeString('yyyymmdd-hhnnss', '-', ':');
  Candidate := Base;
  Suffix := 1;
  while DirExists(Candidate) do
  begin
    Candidate := Base + '-' + IntToStr(Suffix);
    Suffix := Suffix + 1;
  end;
  Result := Candidate;
end;

function PreserveDirectory(const Source, Destination: String): Boolean;
begin
  if not DirectoryHasContents(Source) then
  begin
    Result := True;
    Exit;
  end;

  if not ForceDirectories(ExtractFileDir(Destination)) then
  begin
    Result := False;
    Exit;
  end;

  Result := RenameFile(Source, Destination);
  if Result then
    Exit;

  Result := CopyDirectoryTree(Source, Destination);
  if Result then
    Result := DelTree(Source, True, True, True);
end;

procedure RemoveRuntimeRoot(const RuntimeRoot: String);
var
  RvcRoot: String;
  WeightsRoot: String;
  LogsRoot: String;
  BackupRoot: String;
  HasPreservableData: Boolean;
begin
  if (not DirExists(RuntimeRoot)) or (not IsSafeGeneratedRoot(RuntimeRoot)) then
    Exit;
  RvcRoot := AddBackslash(RuntimeRoot) + 'rvc';
  WeightsRoot := AddBackslash(RvcRoot) + 'weights';
  LogsRoot := AddBackslash(RvcRoot) + 'logs';
  HasPreservableData :=
    DirectoryHasContents(WeightsRoot) or DirectoryHasContents(LogsRoot);
  if HasPreservableData then
  begin
    BackupRoot := UniquePreservationRoot;
    if not PreserveDirectory(WeightsRoot, AddBackslash(BackupRoot) + 'weights') then
      ManagedRuntimeCanBeDeleted := False;
    if not PreserveDirectory(LogsRoot, AddBackslash(BackupRoot) + 'logs') then
      ManagedRuntimeCanBeDeleted := False;
  end;

  if ManagedRuntimeCanBeDeleted then
  begin
    ManagedRuntimeCanBeDeleted :=
      (not DirExists(RuntimeRoot)) or DelTree(RuntimeRoot, True, True, True);
    if ManagedRuntimeCanBeDeleted and HasPreservableData then
    begin
      PreservedRuntimeData := True;
      if PreservedRuntimePath = '' then
        PreservedRuntimePath := BackupRoot
      else
        PreservedRuntimePath := PreservedRuntimePath + Chr(13) + Chr(10) + BackupRoot;
    end;
  end;
end;

procedure PrepareRuntimeRemoval;
var
  AppRuntimeRoot: String;
  ConfiguredRuntimeRoot: String;
  ConfiguredCacheRoot: String;
begin
  if RuntimePreservationPrepared then
    Exit;
  RuntimePreservationPrepared := True;
  ManagedRuntimeCanBeDeleted := True;
  ManagedCacheCanBeDeleted := True;

  AppRuntimeRoot := ExpandConstant('{app}\runtime');
  ConfiguredRuntimeRoot := ReadStoragePath('runtime_root');
  if ConfiguredRuntimeRoot = '' then
    ConfiguredRuntimeRoot := AppRuntimeRoot;
  RemoveRuntimeRoot(ConfiguredRuntimeRoot);
  if not SamePath(AppRuntimeRoot, ConfiguredRuntimeRoot) then
    RemoveRuntimeRoot(AppRuntimeRoot);

  ConfiguredCacheRoot := ReadStoragePath('cache_root');
  if ConfiguredCacheRoot = '' then
    ConfiguredCacheRoot := AddBackslash(RuntimeDataRoot) + 'cache';
  if DirExists(ConfiguredCacheRoot) and IsSafeGeneratedRoot(ConfiguredCacheRoot) then
    ManagedCacheCanBeDeleted := DelTree(ConfiguredCacheRoot, True, True, True);
end;

function InitializeUninstall: Boolean;
begin
  Result := not CheckForMutexes('{#AppMutexName}');
  if not Result then
  begin
    if not UninstallSilent then
      MsgBox(
        '{#AppName} is running. Close the application before uninstalling.',
        mbError,
        MB_OK
      );
    Exit;
  end;
  ManagedRuntimeCanBeDeleted := True;
  ManagedCacheCanBeDeleted := True;
  RuntimePreservationPrepared := False;
  PreservedRuntimeData := False;
  PreservedRuntimePath := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    PrepareRuntimeRemoval
  else if CurUninstallStep = usPostUninstall then
  begin
    if ((not ManagedRuntimeCanBeDeleted) or (not ManagedCacheCanBeDeleted)) and
       (not UninstallSilent) then
      MsgBox(
        'Some generated audio engine or cache files could not be removed. No song, model, or exported data was deleted.',
        mbError,
        MB_OK)
    else if PreservedRuntimeData and (not UninstallSilent) then
      MsgBox(
        'JJZero Audio was removed. Existing RVC weights and logs were preserved at:' +
        Chr(13) + Chr(10) + Chr(13) + Chr(10) + PreservedRuntimePath,
        mbInformation,
        MB_OK);
  end;
end;
