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
  CredentialTypeGeneric = 1;
  ErrorNotFound = 1168;
  GoogleCredentialTarget = 'JJZero Audio/Google Drive';
#ifdef VerificationBuild
  VerificationGoogleCredentialTarget = 'JJZero Audio/Google Drive Removal Verification';
#endif

function GetFileAttributesW(FileName: String): Cardinal;
  external 'GetFileAttributesW@kernel32.dll stdcall';

function CredDeleteW(TargetName: String; CredentialType, Flags: Cardinal): Boolean;
  external 'CredDeleteW@advapi32.dll stdcall';

var
  ManagedRuntimeCanBeDeleted: Boolean;
  ManagedCacheCanBeDeleted: Boolean;
  RuntimePreservationPrepared: Boolean;
  PreservedRuntimeData: Boolean;
  PreservedRuntimePath: String;
  PreservedExternalStorage: Boolean;
  CompleteRemovalRequested: Boolean;
  DeleteUserWorkRequested: Boolean;
  CompleteRemovalPrepared: Boolean;
  CompleteRemovalSucceeded: Boolean;
  CompleteRemovalFailureDetails: String;
  RemovalOptionsForm: TSetupForm;
  NormalRemovalRadio: TNewRadioButton;
  CompleteRemovalRadio: TNewRadioButton;
  DeleteUserWorkCheckBox: TNewCheckBox;
  RemovalOptionsPathsLabel: TNewStaticText;
  RemovalOptionsFailureLabel: TNewStaticText;
  RemovalOptionsLayoutReady: Boolean;
  RemovalOptionsWorkspaceRoot: String;
  RemovalOptionsOutputRoot: String;
  RemovalOptionsFailureReason: String;

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

procedure SetCompleteRemovalOptions(
  const Requested, DeleteUserWork: Boolean);
begin
  CompleteRemovalRequested := Requested;
  DeleteUserWorkRequested := Requested and DeleteUserWork;
end;

procedure InitializeCompleteRemovalOptions;
begin
  SetCompleteRemovalOptions(False, False);
#ifdef VerificationBuild
  SetCompleteRemovalOptions(
    HasCommandLineSwitch('/JJZEROCOMPLETEREMOVAL'),
    HasCommandLineSwitch('/JJZERODELETEWORK'));
#endif
end;

function CompleteRemovalCredentialTarget: String;
begin
#ifdef VerificationBuild
  Result := VerificationGoogleCredentialTarget;
#else
  Result := GoogleCredentialTarget;
#endif
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

function ExistingAncestorPath(const Candidate: String): String;
var
  CurrentPath: String;
  ParentPath: String;
begin
  Result := '';
  CurrentPath := NormalizePath(Candidate);
  while CurrentPath <> '' do
  begin
    if DirExists(CurrentPath) then
    begin
      Result := CurrentPath;
      Exit;
    end;
    ParentPath := ExtractFileDir(CurrentPath);
    if (ParentPath = '') or SamePath(ParentPath, CurrentPath) then
      Exit;
    CurrentPath := ParentPath;
  end;
end;

function ValidateSavedStoragePath(
  const Candidate, Description: String;
  const RequireExisting: Boolean;
  var FailureReason: String): Boolean;
var
  NormalizedCandidate: String;
  DriveRoot: String;
  ExistingAncestor: String;
begin
  Result := False;
  if not IsCanonicalAbsolutePath(Candidate) then
  begin
    FailureReason := Description + ' is not a canonical absolute path.';
    Exit;
  end;
  if IsDangerousDeletionRoot(Candidate) then
  begin
    FailureReason := Description + ' points to a protected Windows or user folder.';
    Exit;
  end;

  NormalizedCandidate := NormalizePath(Candidate);
  DriveRoot := AddBackslash(ExtractFileDrive(NormalizedCandidate));
  if (DriveRoot = '') or (not DirExists(DriveRoot)) then
  begin
    FailureReason := Description + ' is on an unavailable drive or share.';
    Exit;
  end;
  if RequireExisting and (not DirExists(NormalizedCandidate)) then
  begin
    FailureReason := Description + ' is unavailable or does not exist.';
    Exit;
  end;

  ExistingAncestor := ExistingAncestorPath(NormalizedCandidate);
  if (ExistingAncestor = '') or PathHasReparsePoint(ExistingAncestor) then
  begin
    FailureReason := Description + ' has an unavailable or linked parent path.';
    Exit;
  end;
  if DirExists(NormalizedCandidate) and TreeHasReparsePoint(NormalizedCandidate) then
  begin
    FailureReason := Description + ' contains a junction or symbolic link.';
    Exit;
  end;
  Result := True;
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

  if not ValidateSavedStoragePath(
    StorageRoot, 'Storage root', True, FailureReason) then
    Exit;
  if not ValidateSavedStoragePath(
    WorkspaceRoot, 'Data folder', False, FailureReason) then
    Exit;
  if not ValidateSavedStoragePath(
    OutputRoot, 'Output folder', False, FailureReason) then
    Exit;
  if not ValidateSavedStoragePath(
    RuntimeRoot, 'Runtime folder', False, FailureReason) then
    Exit;
  if not ValidateSavedStoragePath(
    CacheRoot, 'Cache folder', False, FailureReason) then
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

procedure AppendCompleteRemovalFailure(
  const Description, FailureReason: String);
var
  Detail: String;
begin
  CompleteRemovalSucceeded := False;
  Detail := Description;
  if FailureReason <> '' then
    Detail := Detail + ': ' + FailureReason;
  if CompleteRemovalFailureDetails = '' then
    CompleteRemovalFailureDetails := Detail
  else
    CompleteRemovalFailureDetails :=
      CompleteRemovalFailureDetails + Chr(13) + Chr(10) + Detail;
  Log('Complete Removal could not remove ' + Detail);
end;

function DeleteVerifiedTree(
  const Candidate, ExpectedRoot, Description: String): Boolean;
var
  FailureReason: String;
begin
  Result := True;
  if not DirExists(Candidate) then
    Exit;
  if not ValidateConfiguredDeletionRoot(
    Candidate, ExpectedRoot, Description, FailureReason) then
  begin
    AppendCompleteRemovalFailure(Description, FailureReason);
    Result := False;
    Exit;
  end;
  Result := DelTree(Candidate, True, True, True);
  if not Result then
    AppendCompleteRemovalFailure(Description, 'Files are locked or inaccessible.');
end;

function IsAllowedRuntimeDataRoot(const Candidate: String): Boolean;
var
  ExpectedRoot: String;
begin
  Result := False;
#ifdef VerificationBuild
  ExpectedRoot := RuntimeDataRoot;
#else
  ExpectedRoot := ExpandConstant('{localappdata}\JJZero Audio');
#endif
  if not IsCanonicalAbsolutePath(Candidate) or
     (not SamePath(Candidate, ExpectedRoot)) or
     IsDriveOrShareRoot(Candidate) or IsInsideSystemTree(Candidate) or
     PathHasReparsePoint(Candidate) or TreeHasReparsePoint(Candidate) then
    Exit;
  Result := True;
end;

procedure DeleteKnownLocalState;
var
  DataRoot: String;
begin
  DataRoot := NormalizePath(RuntimeDataRoot);
  if DataRoot = '' then
  begin
    AppendCompleteRemovalFailure(
      'local application state', 'The application data path is invalid.');
    Exit;
  end;
  DeleteVerifiedTree(
    AddBackslash(DataRoot) + 'cache',
    AddBackslash(DataRoot) + 'cache',
    'local cache');
  DeleteVerifiedTree(
    AddBackslash(DataRoot) + 'logs',
    AddBackslash(DataRoot) + 'logs',
    'diagnostic logs');
  DeleteVerifiedTree(
    AddBackslash(DataRoot) + 'migrations',
    AddBackslash(DataRoot) + 'migrations',
    'migration state');
  DeleteVerifiedTree(
    AddBackslash(DataRoot) + 'preserved-runtime',
    AddBackslash(DataRoot) + 'preserved-runtime',
    'preserved RVC runtime');
  DeleteVerifiedTree(
    AddBackslash(DataRoot) + 'settings',
    AddBackslash(DataRoot) + 'settings',
    'application settings');
end;

procedure DeleteLocalApplicationState(
  const LayoutReady, DeleteUserWork: Boolean;
  const WorkspaceRoot, OutputRoot: String);
var
  DataRoot: String;
  PreservedWorkInsideDataRoot: Boolean;
begin
  DataRoot := NormalizePath(RuntimeDataRoot);
  PreservedWorkInsideDataRoot :=
    LayoutReady and (not DeleteUserWork) and
    (PathContains(DataRoot, WorkspaceRoot) or PathContains(DataRoot, OutputRoot));

  if LayoutReady and (not PreservedWorkInsideDataRoot) then
  begin
    if not IsAllowedRuntimeDataRoot(DataRoot) then
    begin
      AppendCompleteRemovalFailure(
        'local application state',
        'The application data root failed its ownership or link check.');
      Exit;
    end;
    if DirExists(DataRoot) and (not DelTree(DataRoot, True, True, True)) then
      AppendCompleteRemovalFailure(
        'local application state', 'Files are locked or inaccessible.');
    Exit;
  end;

  DeleteKnownLocalState;
end;

function DeleteGoogleCredential: Boolean;
var
  TargetName: String;
  ErrorCode: LongInt;
begin
  TargetName := CompleteRemovalCredentialTarget;
  Result := CredDeleteW(TargetName, CredentialTypeGeneric, 0);
  if Result then
    Exit;
  ErrorCode := DLLGetLastError;
  Result := ErrorCode = ErrorNotFound;
  if not Result then
    AppendCompleteRemovalFailure(
      'Google Drive credential', 'Windows error ' + IntToStr(ErrorCode));
end;

procedure PrepareCompleteRemoval;
var
  AppRuntimeRoot: String;
  WorkspaceRoot: String;
  OutputRoot: String;
  RuntimeRoot: String;
  CacheRoot: String;
  FailureReason: String;
  LayoutReady: Boolean;
begin
  if CompleteRemovalPrepared then
    Exit;
  CompleteRemovalPrepared := True;
  CompleteRemovalSucceeded := True;
  CompleteRemovalFailureDetails := '';

  LayoutReady := TryLoadSafeStorageLayout(
    WorkspaceRoot, OutputRoot, RuntimeRoot, CacheRoot, FailureReason);
  if not LayoutReady then
    AppendCompleteRemovalFailure('configured storage', FailureReason);

  AppRuntimeRoot := ExpandConstant('{app}\runtime');
  DeleteVerifiedTree(
    AppRuntimeRoot, AppRuntimeRoot, 'application-owned Runtime');

  if LayoutReady then
  begin
    if not SamePath(RuntimeRoot, AppRuntimeRoot) then
      DeleteVerifiedTree(RuntimeRoot, RuntimeRoot, 'configured Runtime');
    DeleteVerifiedTree(CacheRoot, CacheRoot, 'configured Cache');
    if DeleteUserWorkRequested then
    begin
      DeleteVerifiedTree(WorkspaceRoot, WorkspaceRoot, 'Data');
      DeleteVerifiedTree(OutputRoot, OutputRoot, 'Output');
    end;
  end;

  DeleteGoogleCredential;
  DeleteLocalApplicationState(
    LayoutReady, DeleteUserWorkRequested, WorkspaceRoot, OutputRoot);
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

procedure UpdateRemovalOptionsState;
var
  WorkDeletionAvailable: Boolean;
begin
  WorkDeletionAvailable :=
    CompleteRemovalRadio.Checked and RemovalOptionsLayoutReady;
  DeleteUserWorkCheckBox.Enabled := WorkDeletionAvailable;
  RemovalOptionsPathsLabel.Enabled := CompleteRemovalRadio.Checked;
  RemovalOptionsFailureLabel.Visible :=
    CompleteRemovalRadio.Checked and (not RemovalOptionsLayoutReady);
  if not WorkDeletionAvailable then
    DeleteUserWorkCheckBox.Checked := False;
end;

procedure RemovalModeOnClick(Sender: TObject);
begin
  UpdateRemovalOptionsState;
end;

function ConfirmRemovalWorkDeletion: Boolean;
var
  ConfirmationText: String;
begin
  Result := True;
  if not (CompleteRemovalRadio.Checked and DeleteUserWorkCheckBox.Checked) then
    Exit;
  ConfirmationText :=
    '다음 작업물을 영구 삭제하시겠습니까?' + Chr(13) + Chr(10) +
    Chr(13) + Chr(10) +
    'Data: ' + RemovalOptionsWorkspaceRoot + Chr(13) + Chr(10) +
    'Output: ' + RemovalOptionsOutputRoot + Chr(13) + Chr(10) +
    Chr(13) + Chr(10) +
    '곡, 모델, 프로젝트 및 출력 파일이 삭제되며 되돌릴 수 없습니다.';
  Result := MsgBox(
    ConfirmationText,
    mbConfirmation,
    MB_YESNO or MB_DEFBUTTON2) = idYes;
end;

function ShowRemovalOptionsDialog: Boolean;
var
  HeadingLabel: TNewStaticText;
  IntroLabel: TNewStaticText;
  NormalDescriptionLabel: TNewStaticText;
  CompleteDescriptionLabel: TNewStaticText;
  WorkHeadingLabel: TNewStaticText;
  WorkDescriptionLabel: TNewStaticText;
  ContinueButton: TNewButton;
  CancelButton: TNewButton;
  RuntimeRoot: String;
  CacheRoot: String;
  DialogAccepted: Boolean;
begin
  RemovalOptionsLayoutReady := TryLoadSafeStorageLayout(
    RemovalOptionsWorkspaceRoot,
    RemovalOptionsOutputRoot,
    RuntimeRoot,
    CacheRoot,
    RemovalOptionsFailureReason);

  RemovalOptionsForm := CreateCustomForm(ScaleX(640), ScaleY(560), False, True);
  try
    RemovalOptionsForm.Caption := 'JJZero Audio 제거';

    HeadingLabel := TNewStaticText.Create(RemovalOptionsForm);
    HeadingLabel.Parent := RemovalOptionsForm;
    HeadingLabel.Left := ScaleX(24);
    HeadingLabel.Top := ScaleY(20);
    HeadingLabel.Width := ScaleX(592);
    HeadingLabel.Height := ScaleY(28);
    HeadingLabel.AutoSize := False;
    HeadingLabel.Caption := '제거 방법을 선택하세요';
    HeadingLabel.Font.Size := 14;
    HeadingLabel.Font.Style := [fsBold];

    IntroLabel := TNewStaticText.Create(RemovalOptionsForm);
    IntroLabel.Parent := RemovalOptionsForm;
    IntroLabel.Left := ScaleX(24);
    IntroLabel.Top := ScaleY(54);
    IntroLabel.Width := ScaleX(592);
    IntroLabel.Height := ScaleY(34);
    IntroLabel.AutoSize := False;
    IntroLabel.WordWrap := True;
    IntroLabel.Caption :=
      '일반 제거는 작업물을 보존합니다. 이 PC의 JJZero 상태까지 지우려면 완전 제거를 선택하세요.';

    NormalRemovalRadio := TNewRadioButton.Create(RemovalOptionsForm);
    NormalRemovalRadio.Parent := RemovalOptionsForm;
    NormalRemovalRadio.Left := ScaleX(24);
    NormalRemovalRadio.Top := ScaleY(98);
    NormalRemovalRadio.Width := ScaleX(592);
    NormalRemovalRadio.Height := ScaleY(24);
    NormalRemovalRadio.Caption := '일반 제거 (권장)';
    NormalRemovalRadio.Checked := True;
    NormalRemovalRadio.Font.Style := [fsBold];
    NormalRemovalRadio.OnClick := @RemovalModeOnClick;

    NormalDescriptionLabel := TNewStaticText.Create(RemovalOptionsForm);
    NormalDescriptionLabel.Parent := RemovalOptionsForm;
    NormalDescriptionLabel.Left := ScaleX(48);
    NormalDescriptionLabel.Top := ScaleY(124);
    NormalDescriptionLabel.Width := ScaleX(568);
    NormalDescriptionLabel.Height := ScaleY(38);
    NormalDescriptionLabel.AutoSize := False;
    NormalDescriptionLabel.WordWrap := True;
    NormalDescriptionLabel.Caption :=
      '앱과 재생성 가능한 오디오 엔진 및 기본 캐시를 제거합니다. 곡, 모델, 프로젝트와 출력 파일은 유지합니다.';

    CompleteRemovalRadio := TNewRadioButton.Create(RemovalOptionsForm);
    CompleteRemovalRadio.Parent := RemovalOptionsForm;
    CompleteRemovalRadio.Left := ScaleX(24);
    CompleteRemovalRadio.Top := ScaleY(174);
    CompleteRemovalRadio.Width := ScaleX(592);
    CompleteRemovalRadio.Height := ScaleY(24);
    CompleteRemovalRadio.Caption := '완전 제거';
    CompleteRemovalRadio.Font.Style := [fsBold];
    CompleteRemovalRadio.OnClick := @RemovalModeOnClick;

    CompleteDescriptionLabel := TNewStaticText.Create(RemovalOptionsForm);
    CompleteDescriptionLabel.Parent := RemovalOptionsForm;
    CompleteDescriptionLabel.Left := ScaleX(48);
    CompleteDescriptionLabel.Top := ScaleY(200);
    CompleteDescriptionLabel.Width := ScaleX(568);
    CompleteDescriptionLabel.Height := ScaleY(54);
    CompleteDescriptionLabel.AutoSize := False;
    CompleteDescriptionLabel.WordWrap := True;
    CompleteDescriptionLabel.Caption :=
      'Runtime, Cache, 설정, 로그, 보존된 RVC 런타임과 Google Drive 로그인 정보를 제거합니다. 작업물은 아래에서 별도로 선택하기 전까지 유지합니다.';

    WorkHeadingLabel := TNewStaticText.Create(RemovalOptionsForm);
    WorkHeadingLabel.Parent := RemovalOptionsForm;
    WorkHeadingLabel.Left := ScaleX(24);
    WorkHeadingLabel.Top := ScaleY(274);
    WorkHeadingLabel.Width := ScaleX(592);
    WorkHeadingLabel.Height := ScaleY(24);
    WorkHeadingLabel.AutoSize := False;
    WorkHeadingLabel.Caption := '작업물';
    WorkHeadingLabel.Font.Style := [fsBold];

    DeleteUserWorkCheckBox := TNewCheckBox.Create(RemovalOptionsForm);
    DeleteUserWorkCheckBox.Parent := RemovalOptionsForm;
    DeleteUserWorkCheckBox.Left := ScaleX(24);
    DeleteUserWorkCheckBox.Top := ScaleY(304);
    DeleteUserWorkCheckBox.Width := ScaleX(592);
    DeleteUserWorkCheckBox.Height := ScaleY(24);
    DeleteUserWorkCheckBox.Caption := '저장된 작업물도 함께 삭제';
    DeleteUserWorkCheckBox.Checked := False;

    WorkDescriptionLabel := TNewStaticText.Create(RemovalOptionsForm);
    WorkDescriptionLabel.Parent := RemovalOptionsForm;
    WorkDescriptionLabel.Left := ScaleX(48);
    WorkDescriptionLabel.Top := ScaleY(332);
    WorkDescriptionLabel.Width := ScaleX(568);
    WorkDescriptionLabel.Height := ScaleY(36);
    WorkDescriptionLabel.AutoSize := False;
    WorkDescriptionLabel.WordWrap := True;
    WorkDescriptionLabel.Caption :=
      '선택하면 곡, 모델, 프로젝트 및 출력 파일을 영구 삭제합니다. 이 작업은 되돌릴 수 없습니다.';

    RemovalOptionsPathsLabel := TNewStaticText.Create(RemovalOptionsForm);
    RemovalOptionsPathsLabel.Parent := RemovalOptionsForm;
    RemovalOptionsPathsLabel.Left := ScaleX(48);
    RemovalOptionsPathsLabel.Top := ScaleY(376);
    RemovalOptionsPathsLabel.Width := ScaleX(568);
    RemovalOptionsPathsLabel.Height := ScaleY(54);
    RemovalOptionsPathsLabel.AutoSize := False;
    RemovalOptionsPathsLabel.WordWrap := True;
    if RemovalOptionsLayoutReady then
      RemovalOptionsPathsLabel.Caption :=
        'Data: ' + RemovalOptionsWorkspaceRoot + Chr(13) + Chr(10) +
        'Output: ' + RemovalOptionsOutputRoot
    else
      RemovalOptionsPathsLabel.Caption := 'Data/Output 경로를 확인할 수 없습니다.';

    RemovalOptionsFailureLabel := TNewStaticText.Create(RemovalOptionsForm);
    RemovalOptionsFailureLabel.Parent := RemovalOptionsForm;
    RemovalOptionsFailureLabel.Left := ScaleX(48);
    RemovalOptionsFailureLabel.Top := ScaleY(438);
    RemovalOptionsFailureLabel.Width := ScaleX(568);
    RemovalOptionsFailureLabel.Height := ScaleY(44);
    RemovalOptionsFailureLabel.AutoSize := False;
    RemovalOptionsFailureLabel.WordWrap := True;
    RemovalOptionsFailureLabel.Caption :=
      '작업물 삭제를 사용할 수 없습니다: ' + RemovalOptionsFailureReason;
    RemovalOptionsFailureLabel.Font.Style := [fsBold];

    ContinueButton := TNewButton.Create(RemovalOptionsForm);
    ContinueButton.Parent := RemovalOptionsForm;
    ContinueButton.Left := ScaleX(408);
    ContinueButton.Top := ScaleY(510);
    ContinueButton.Width := ScaleX(100);
    ContinueButton.Height := ScaleY(30);
    ContinueButton.Caption := '계속';
    ContinueButton.Default := True;
    ContinueButton.ModalResult := mrOk;

    CancelButton := TNewButton.Create(RemovalOptionsForm);
    CancelButton.Parent := RemovalOptionsForm;
    CancelButton.Left := ScaleX(516);
    CancelButton.Top := ScaleY(510);
    CancelButton.Width := ScaleX(100);
    CancelButton.Height := ScaleY(30);
    CancelButton.Caption := '취소';
    CancelButton.Cancel := True;
    CancelButton.ModalResult := mrCancel;

    UpdateRemovalOptionsState;
    RemovalOptionsForm.ActiveControl := NormalRemovalRadio;
    repeat
      DialogAccepted := RemovalOptionsForm.ShowModal = mrOk;
      Result := DialogAccepted;
      if DialogAccepted then
        Result := ConfirmRemovalWorkDeletion;
    until Result or (not DialogAccepted);
    if Result then
      SetCompleteRemovalOptions(
        CompleteRemovalRadio.Checked,
        DeleteUserWorkCheckBox.Checked);
  finally
    RemovalOptionsForm.Free;
  end;
end;

function InitializeUninstall: Boolean;
begin
  InitializeCompleteRemovalOptions;
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
  CompleteRemovalPrepared := False;
  CompleteRemovalSucceeded := True;
  CompleteRemovalFailureDetails := '';
  if Result and (not UninstallSilent) and (not CompleteRemovalRequested) then
    Result := ShowRemovalOptionsDialog;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    if CompleteRemovalRequested then
      PrepareCompleteRemoval
    else
      PrepareRuntimeRemoval;
  end
  else if CurUninstallStep = usPostUninstall then
  begin
    if CompleteRemovalRequested and (not CompleteRemovalSucceeded) and
       (not UninstallSilent) then
      MsgBox(
        'JJZero Audio was removed, but Complete Removal could not remove every requested item:' +
        Chr(13) + Chr(10) + Chr(13) + Chr(10) + CompleteRemovalFailureDetails,
        mbError,
        MB_OK)
    else if CompleteRemovalRequested and (not UninstallSilent) then
      MsgBox(
        'JJZero Audio and the selected local state were completely removed.',
        mbInformation,
        MB_OK)
    else if ((not ManagedRuntimeCanBeDeleted) or (not ManagedCacheCanBeDeleted)) and
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
