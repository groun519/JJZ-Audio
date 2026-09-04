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
Filename: "{app}\{#AppExecutable}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent; Check: ShouldOfferInteractiveLaunch
Filename: "{app}\{#AppExecutable}"; Flags: nowait skipifdoesntexist; Check: ShouldRelaunchAfterInternalUpdate

[Code]
const
  FileAttributeDirectory = $10;
  FileAttributeReparsePoint = $400;
  InvalidFileAttributes = $FFFFFFFF;

function GetFileAttributesW(FileName: String): Cardinal;
  external 'GetFileAttributesW@kernel32.dll stdcall';

var
  ManagedRuntimeCanBeDeleted: Boolean;
  ManagedCacheCanBeDeleted: Boolean;
  RuntimePreservationPrepared: Boolean;
  PreservedRuntimeData: Boolean;
  PreservedRuntimePath: String;
  PreservedExternalStorage: Boolean;

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
  if CheckForMutexes('{#AppMutexName}') and
     (not HasCommandLineSwitch('/JJZEROUPDATE')) then
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

function ShouldOfferInteractiveLaunch: Boolean;
begin
  Result := not HasCommandLineSwitch('/JJZEROUPDATE');
end;

function ShouldRelaunchAfterInternalUpdate: Boolean;
begin
  Result := HasCommandLineSwitch('/JJZEROUPDATE');
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

function TryLoadStorageSettings(var Content: String; var FailureReason: String): Boolean;
var
  RawContent: AnsiString;
  TrimmedContent: String;
begin
  Result := False;
  Content := '';
  FailureReason := '';
  if not LoadStringFromFile(StorageSettingsFile, RawContent) then
  begin
    FailureReason := 'Storage settings could not be read.';
    Exit;
  end;

  Content := Utf8Decode(RawContent);
  TrimmedContent := Trim(Content);
  if Length(TrimmedContent) < 2 then
  begin
    FailureReason := 'Storage settings are empty or damaged.';
    Exit;
  end;
  if (TrimmedContent[1] <> '{') or
     (TrimmedContent[Length(TrimmedContent)] <> '}') then
  begin
    FailureReason := 'Storage settings are not a valid JSON object.';
    Exit;
  end;
  Content := TrimmedContent;
  Result := True;
end;

function StorageMarkerOccursOnce(const Content, Marker: String): Boolean;
var
  MarkerPosition: Integer;
  Remaining: String;
begin
  MarkerPosition := Pos(Marker, Content);
  if MarkerPosition = 0 then
  begin
    Result := False;
    Exit;
  end;
  Remaining := Copy(Content, MarkerPosition + Length(Marker), MaxInt);
  Result := Pos(Marker, Remaining) = 0;
end;

function TryReadStoragePath(
  const Content, Key: String;
  var Value, FailureReason: String): Boolean;
var
  Tail: String;
  Marker: String;
  MarkerPosition: Integer;
  EndPosition: Integer;
begin
  Result := False;
  Value := '';
  Marker := '"' + Key + '"';
  if not StorageMarkerOccursOnce(Content, Marker) then
  begin
    FailureReason := 'Storage setting "' + Key + '" is missing or duplicated.';
    Exit;
  end;

  MarkerPosition := Pos(Marker, String(Content));
  Tail := Trim(Copy(Content, MarkerPosition + Length(Marker), MaxInt));
  if (Length(Tail) < 3) or (Tail[1] <> ':') then
  begin
    FailureReason := 'Storage setting "' + Key + '" is malformed.';
    Exit;
  end;
  Tail := Trim(Copy(Tail, 2, MaxInt));
  if (Tail = '') or (Tail[1] <> '"') then
  begin
    FailureReason := 'Storage setting "' + Key + '" must be a path string.';
    Exit;
  end;
  Tail := Copy(Tail, 2, MaxInt);
  EndPosition := Pos('"', Tail);
  if EndPosition = 0 then
  begin
    FailureReason := 'Storage setting "' + Key + '" has no closing quote.';
    Exit;
  end;
  Value := Copy(Tail, 1, EndPosition - 1);
  StringChangeEx(Value, '\\', '\', True);
  Value := RemoveBackslashUnlessRoot(Value);
  if Value = '' then
  begin
    FailureReason := 'Storage setting "' + Key + '" is empty.';
    Exit;
  end;
  Result := True;
end;

function TryReadStorageVersion(
  const Content: String;
  var Version: Integer;
  var FailureReason: String): Boolean;
var
  Tail: String;
  Marker: String;
  MarkerPosition: Integer;
  EndPosition: Integer;
  BracePosition: Integer;
  VersionText: String;
begin
  Result := False;
  Version := -1;
  Marker := '"version"';
  if not StorageMarkerOccursOnce(Content, Marker) then
  begin
    FailureReason := 'Storage setting "version" is missing or duplicated.';
    Exit;
  end;

  MarkerPosition := Pos(Marker, Content);
  Tail := Trim(Copy(Content, MarkerPosition + Length(Marker), MaxInt));
  if (Length(Tail) < 2) or (Tail[1] <> ':') then
  begin
    FailureReason := 'Storage setting "version" is malformed.';
    Exit;
  end;
  Tail := Trim(Copy(Tail, 2, MaxInt));
  EndPosition := Pos(',', Tail);
  BracePosition := Pos('}', Tail);
  if (EndPosition = 0) or
     ((BracePosition > 0) and (BracePosition < EndPosition)) then
    EndPosition := BracePosition;
  if EndPosition = 0 then
  begin
    FailureReason := 'Storage setting "version" has no terminator.';
    Exit;
  end;
  VersionText := Trim(Copy(Tail, 1, EndPosition - 1));
  Version := StrToIntDef(VersionText, -1);
  if (Version <> 2) and (Version <> 3) then
  begin
    FailureReason := 'Storage layout version is not supported for removal.';
    Exit;
  end;
  Result := True;
end;

function ReadStoragePath(const Key: String): String;
var
  Content: String;
  FailureReason: String;
  Value: String;
begin
  Result := '';
  if not TryLoadStorageSettings(Content, FailureReason) then
    Exit;
  if TryReadStoragePath(Content, Key, Value, FailureReason) then
    Result := Value;
end;

function NormalizePath(const Value: String): String;
begin
  Result := '';
  if (Trim(Value) = '') or (Length(Value) > 1024) then
    Exit;
  Result := RemoveBackslashUnlessRoot(ExpandFileName(Trim(Value)));
end;

function SamePath(const Left, Right: String): Boolean;
var
  NormalizedLeft: String;
  NormalizedRight: String;
begin
  NormalizedLeft := NormalizePath(Left);
  NormalizedRight := NormalizePath(Right);
  Result := (NormalizedLeft <> '') and (NormalizedRight <> '') and
    (CompareText(NormalizedLeft, NormalizedRight) = 0);
end;

function PathContains(const ParentPath, ChildPath: String): Boolean;
var
  ParentWithSlash: String;
  ChildWithSlash: String;
begin
  ParentWithSlash := NormalizePath(ParentPath);
  ChildWithSlash := NormalizePath(ChildPath);
  if (ParentWithSlash = '') or (ChildWithSlash = '') then
  begin
    Result := False;
    Exit;
  end;
  ParentWithSlash := Lowercase(AddBackslash(ParentWithSlash));
  ChildWithSlash := Lowercase(AddBackslash(ChildWithSlash));
  Result := Pos(ParentWithSlash, ChildWithSlash) = 1;
end;

function PathsOverlap(const Left, Right: String): Boolean;
begin
  Result := PathContains(Left, Right) or PathContains(Right, Left);
end;

function IsCanonicalAbsolutePath(const Value: String): Boolean;
var
  RawPath: String;
  CanonicalPath: String;
  DrivePath: String;
begin
  Result := False;
  RawPath := RemoveBackslashUnlessRoot(Trim(Value));
  if (Copy(RawPath, 1, 4) = '\\?\') or
     (Copy(RawPath, 1, 4) = '\\.\') or
     PathHasInvalidCharacters(RawPath, True) or
     (Pos('~', RawPath) > 0) then
    Exit;
  CanonicalPath := NormalizePath(Value);
  if (RawPath = '') or (CanonicalPath = '') or
     (CompareText(RawPath, CanonicalPath) <> 0) then
    Exit;
  DrivePath := ExtractFileDrive(CanonicalPath);
  if (DrivePath = '') or (Length(CanonicalPath) <= Length(DrivePath)) then
    Exit;
  Result := Copy(CanonicalPath, Length(DrivePath) + 1, 1) = '\';
end;

function IsDriveOrShareRoot(const Candidate: String): Boolean;
var
  DrivePath: String;
begin
  DrivePath := ExtractFileDrive(NormalizePath(Candidate));
  Result := (DrivePath <> '') and
    (SamePath(Candidate, AddBackslash(DrivePath)) or (Pos('$', DrivePath) > 0));
end;

function PathHasReparsePoint(const Candidate: String): Boolean;
var
  CurrentPath: String;
  ParentPath: String;
  Attributes: Cardinal;
begin
  Result := True;
  CurrentPath := NormalizePath(Candidate);
  if CurrentPath = '' then
    Exit;
  while not IsDriveOrShareRoot(CurrentPath) do
  begin
    Attributes := GetFileAttributesW(CurrentPath);
    if Attributes = InvalidFileAttributes then
      Exit;
    if (Attributes and FileAttributeReparsePoint) <> 0 then
      Exit;
    ParentPath := ExtractFileDir(CurrentPath);
    if (ParentPath = '') or SamePath(ParentPath, CurrentPath) then
      Exit;
    CurrentPath := ParentPath;
  end;
  Result := False;
end;

function TreeHasReparsePoint(const Root: String): Boolean;
var
  Entry: TFindRec;
  ChildPath: String;
begin
  Result := False;
  if FindFirst(AddBackslash(Root) + '*', Entry) then
  begin
    try
      repeat
        if (Entry.Name <> '.') and (Entry.Name <> '..') then
        begin
          if (Entry.Attributes and FileAttributeReparsePoint) <> 0 then
          begin
            Result := True;
            Exit;
          end;
          if (Entry.Attributes and FileAttributeDirectory) <> 0 then
          begin
            ChildPath := AddBackslash(Root) + Entry.Name;
            if TreeHasReparsePoint(ChildPath) then
            begin
              Result := True;
              Exit;
            end;
          end;
        end;
      until not FindNext(Entry);
    finally
      FindClose(Entry);
    end;
  end;
end;

function CandidateThreatensRoot(const Candidate, ProtectedRoot: String): Boolean;
begin
  Result := (ProtectedRoot <> '') and PathContains(Candidate, ProtectedRoot);
end;

function IsInsideSystemTree(const Candidate: String): Boolean;
begin
  Result :=
    PathsOverlap(Candidate, ExpandConstant('{win}')) or
    PathsOverlap(Candidate, ExpandConstant('{commonpf}')) or
    PathsOverlap(Candidate, ExpandConstant('{commonpf32}')) or
    PathsOverlap(Candidate, ExpandConstant('{commonpf64}'));
end;

function IsDangerousDeletionRoot(const Candidate: String): Boolean;
var
  UserProfile: String;
  DownloadsRoot: String;
begin
  Result := True;
  if not IsCanonicalAbsolutePath(Candidate) then
    Exit;
  if IsDriveOrShareRoot(Candidate) or IsInsideSystemTree(Candidate) then
    Exit;

  UserProfile := GetEnv('USERPROFILE');
  DownloadsRoot := '';
  if UserProfile <> '' then
    DownloadsRoot := AddBackslash(UserProfile) + 'Downloads';
  if CandidateThreatensRoot(Candidate, UserProfile) or
     CandidateThreatensRoot(Candidate, ExpandConstant('{userdocs}')) or
     CandidateThreatensRoot(Candidate, ExpandConstant('{userdesktop}')) or
     CandidateThreatensRoot(Candidate, DownloadsRoot) or
     CandidateThreatensRoot(Candidate, ExpandConstant('{localappdata}')) or
     CandidateThreatensRoot(Candidate, ExpandConstant('{userappdata}')) or
     CandidateThreatensRoot(Candidate, ExpandConstant('{userpf}')) or
     CandidateThreatensRoot(Candidate, ExpandConstant('{app}')) or
     CandidateThreatensRoot(Candidate, RuntimeDataRoot) then
    Exit;
  Result := False;
end;

function ValidateConfiguredDeletionRoot(
  const Candidate, ExpectedRoot, Description: String;
  var FailureReason: String): Boolean;
var
  NormalizedCandidate: String;
begin
  Result := False;
  if not IsCanonicalAbsolutePath(Candidate) then
  begin
    FailureReason := Description + ' is not a canonical absolute path.';
    Exit;
  end;
  if not SamePath(Candidate, ExpectedRoot) then
  begin
    FailureReason := Description + ' does not match the saved storage setting.';
    Exit;
  end;
  if IsDangerousDeletionRoot(Candidate) then
  begin
    FailureReason := Description + ' points to a protected Windows or user folder.';
    Exit;
  end;
  if PathHasReparsePoint(Candidate) or TreeHasReparsePoint(Candidate) then
  begin
    FailureReason := Description + ' contains a junction or symbolic link.';
    Exit;
  end;
  NormalizedCandidate := NormalizePath(Candidate);
  if not DirExists(NormalizedCandidate) then
  begin
    FailureReason := Description + ' is unavailable or does not exist.';
    Exit;
  end;
  Result := True;
end;

function TryLoadSafeStorageLayout(
  var WorkspaceRoot, OutputRoot, RuntimeRoot, CacheRoot, FailureReason: String): Boolean;
var
  Content: String;
  StorageRoot: String;
  Version: Integer;
begin
  Result := False;
  WorkspaceRoot := '';
  OutputRoot := '';
  RuntimeRoot := '';
  CacheRoot := '';
  FailureReason := '';
  if not TryLoadStorageSettings(Content, FailureReason) then
    Exit;
  if not TryReadStorageVersion(Content, Version, FailureReason) then
    Exit;
  if not TryReadStoragePath(Content, 'storage_root', StorageRoot, FailureReason) then
    Exit;
  if not TryReadStoragePath(Content, 'workspace_root', WorkspaceRoot, FailureReason) then
    Exit;
  if not TryReadStoragePath(Content, 'output_root', OutputRoot, FailureReason) then
    Exit;
  if not TryReadStoragePath(Content, 'runtime_root', RuntimeRoot, FailureReason) then
    Exit;
  if not TryReadStoragePath(Content, 'cache_root', CacheRoot, FailureReason) then
    Exit;

  if not IsCanonicalAbsolutePath(StorageRoot) or
     (not DirExists(NormalizePath(StorageRoot))) then
  begin
    FailureReason := 'The saved storage root is unavailable or invalid.';
    Exit;
  end;
  if not ValidateConfiguredDeletionRoot(
    WorkspaceRoot, WorkspaceRoot, 'Data folder', FailureReason) then
    Exit;
  if not ValidateConfiguredDeletionRoot(
    OutputRoot, OutputRoot, 'Output folder', FailureReason) then
    Exit;
  if not ValidateConfiguredDeletionRoot(
    RuntimeRoot, RuntimeRoot, 'Runtime folder', FailureReason) then
    Exit;
  if not ValidateConfiguredDeletionRoot(
    CacheRoot, CacheRoot, 'Cache folder', FailureReason) then
    Exit;

  if PathsOverlap(WorkspaceRoot, OutputRoot) or
     PathsOverlap(WorkspaceRoot, RuntimeRoot) or
     PathsOverlap(WorkspaceRoot, CacheRoot) or
     PathsOverlap(OutputRoot, RuntimeRoot) or
     PathsOverlap(OutputRoot, CacheRoot) or
     PathsOverlap(RuntimeRoot, CacheRoot) then
  begin
    FailureReason := 'Saved storage folders overlap; removal was refused.';
    Exit;
  end;
  Result := True;
end;

function IsSafeGeneratedRoot(const Candidate: String): Boolean;
var
  WorkspaceRoot: String;
  OutputRoot: String;
begin
  Result := False;
  if IsDangerousDeletionRoot(Candidate) or PathHasReparsePoint(Candidate) or
     TreeHasReparsePoint(Candidate) then
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
  if not DirExists(RuntimeRoot) then
    Exit;
  if not IsSafeGeneratedRoot(RuntimeRoot) then
  begin
    ManagedRuntimeCanBeDeleted := False;
    Exit;
  end;
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
  DefaultCacheRoot: String;
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
  RemoveRuntimeRoot(AppRuntimeRoot);
  if not SamePath(AppRuntimeRoot, ConfiguredRuntimeRoot) then
    PreservedExternalStorage := True;

  ConfiguredCacheRoot := ReadStoragePath('cache_root');
  DefaultCacheRoot := AddBackslash(RuntimeDataRoot) + 'cache';
  if ConfiguredCacheRoot = '' then
    ConfiguredCacheRoot := DefaultCacheRoot;
  if SamePath(ConfiguredCacheRoot, DefaultCacheRoot) then
  begin
    if DirExists(ConfiguredCacheRoot) then
    begin
      if IsSafeGeneratedRoot(ConfiguredCacheRoot) then
        ManagedCacheCanBeDeleted := DelTree(ConfiguredCacheRoot, True, True, True)
      else
        ManagedCacheCanBeDeleted := False;
    end;
  end
  else
    PreservedExternalStorage := True;
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
  PreservedExternalStorage := False;
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
    else if PreservedExternalStorage and (not UninstallSilent) then
      MsgBox(
        'JJZero Audio was removed. Custom Audio Engine and Cache folders were kept to protect files outside the application.',
        mbInformation,
        MB_OK)
    else if PreservedRuntimeData and (not UninstallSilent) then
      MsgBox(
        'JJZero Audio was removed. Existing RVC weights and logs were preserved at:' +
        Chr(13) + Chr(10) + Chr(13) + Chr(10) + PreservedRuntimePath,
        mbInformation,
        MB_OK);
  end;
end;
