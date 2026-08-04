#ifndef AppVersion
  #error AppVersion must be provided by scripts\build_installer.ps1
#endif

#define AppName "JJZero Audio"
#define AppExecutable "JJZero Audio.exe"
#define DistributionDir SourcePath + "..\dist\JJZero Audio"

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
OutputBaseFilename=JJZero-Audio-{#AppVersion}-Setup
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
