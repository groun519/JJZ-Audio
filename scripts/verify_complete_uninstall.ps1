param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,

    [ValidateSet(
        "All",
        "PreserveWork",
        "DeleteWork",
        "MissingGenerated",
        "ProtectedAppState",
        "OverlappingRoots",
        "BrokenSettings"
    )]
    [string]$Scenario = "All"
)

$ErrorActionPreference = "Stop"
$installer = (Resolve-Path -LiteralPath $InstallerPath).Path
$testId = [guid]::NewGuid().ToString("N").Substring(0, 8)
$tempRoot = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\')
$testRoot = [IO.Path]::GetFullPath((Join-Path $tempRoot "jjzero-complete-uninstall-$testId"))
if (-not $testRoot.StartsWith("$tempRoot\", [StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe verification root: $testRoot"
}

$credentialTarget = "JJZero Audio/Google Drive Removal Verification"
$uninstallRegistryKey = "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\{E5ED303D-5BB2-4B1E-8AA8-434C16C4D3AE}_is1"
$uninstallRegistryPsPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{E5ED303D-5BB2-4B1E-8AA8-434C16C4D3AE}_is1"
$registryBackup = Join-Path $env:TEMP "jjzero-complete-uninstall-registry-$testId.reg"
$registrationExisted = Test-Path -LiteralPath $uninstallRegistryPsPath
$dataRootExisted = Test-Path Env:JJZERO_DATA_ROOT
$previousDataRoot = $env:JJZERO_DATA_ROOT

if (-not ("JJZeroCompleteRemovalCredentialTest" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;

public static class JJZeroCompleteRemovalCredentialTest
{
    private const uint CredentialTypeGeneric = 1;
    private const uint CredentialPersistLocalMachine = 2;
    private const int ErrorNotFound = 1168;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct Credential
    {
        public uint Flags;
        public uint Type;
        public string TargetName;
        public string Comment;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
        public uint CredentialBlobSize;
        public IntPtr CredentialBlob;
        public uint Persist;
        public uint AttributeCount;
        public IntPtr Attributes;
        public string TargetAlias;
        public string UserName;
    }

    [DllImport("Advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CredWriteW(ref Credential credential, uint flags);

    [DllImport("Advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CredReadW(
        string target, uint type, uint flags, out IntPtr credential);

    [DllImport("Advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CredDeleteW(string target, uint type, uint flags);

    [DllImport("Advapi32.dll")]
    private static extern void CredFree(IntPtr buffer);

    public static void Write(string target)
    {
        byte[] secret = Encoding.UTF8.GetBytes("verification-secret");
        IntPtr blob = Marshal.AllocCoTaskMem(secret.Length);
        try
        {
            Marshal.Copy(secret, 0, blob, secret.Length);
            Credential credential = new Credential
            {
                Type = CredentialTypeGeneric,
                TargetName = target,
                CredentialBlobSize = (uint)secret.Length,
                CredentialBlob = blob,
                Persist = CredentialPersistLocalMachine,
                UserName = "JJZero"
            };
            if (!CredWriteW(ref credential, 0))
                throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        finally
        {
            Marshal.FreeCoTaskMem(blob);
        }
    }

    public static bool Exists(string target)
    {
        IntPtr credential;
        if (!CredReadW(target, CredentialTypeGeneric, 0, out credential))
        {
            int error = Marshal.GetLastWin32Error();
            if (error == ErrorNotFound)
                return false;
            throw new Win32Exception(error);
        }
        CredFree(credential);
        return true;
    }

    public static void Delete(string target)
    {
        if (CredDeleteW(target, CredentialTypeGeneric, 0))
            return;
        int error = Marshal.GetLastWin32Error();
        if (error != ErrorNotFound)
            throw new Win32Exception(error);
    }
}
"@
}

function Assert-Exists {
    param([string]$LiteralPath, [string]$Message)
    if (-not (Test-Path -LiteralPath $LiteralPath)) {
        throw "$Message`: $LiteralPath"
    }
}

function Assert-Removed {
    param([string]$LiteralPath, [string]$Message)
    if (Test-Path -LiteralPath $LiteralPath) {
        throw "$Message`: $LiteralPath"
    }
}

function Test-VerificationCredential {
    return [JJZeroCompleteRemovalCredentialTest]::Exists($credentialTarget)
}

function Set-VerificationCredential {
    [JJZeroCompleteRemovalCredentialTest]::Write($credentialTarget)
    if (-not (Test-VerificationCredential)) {
        throw "Could not create the Complete Removal verification credential."
    }
}

function Remove-VerificationCredential {
    [JJZeroCompleteRemovalCredentialTest]::Delete($credentialTarget)
}

function Invoke-CompleteUninstallScenario {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet(
            "PreserveWork",
            "DeleteWork",
            "MissingGenerated",
            "ProtectedAppState",
            "OverlappingRoots",
            "BrokenSettings"
        )]
        [string]$Name
    )

    $scenarioRoot = Join-Path $testRoot $Name.ToLowerInvariant()
    $installRoot = Join-Path $scenarioRoot "app"
    $dataRoot = Join-Path $scenarioRoot "JJZero Audio"
    $storageRoot = Join-Path $scenarioRoot "storage"
    $workspaceRoot = Join-Path $storageRoot "Data"
    $outputRoot = Join-Path $storageRoot "Output"
    $runtimeRoot = Join-Path $storageRoot "Runtime"
    $cacheRoot = Join-Path $storageRoot "Cache"
    $storageSentinel = Join-Path $storageRoot "keep-user-file.txt"
    $unsafeLayout = $Name -in @(
        "ProtectedAppState",
        "OverlappingRoots",
        "BrokenSettings"
    )

    New-Item -ItemType Directory -Path $scenarioRoot -Force | Out-Null
    $install = Start-Process `
        -FilePath $installer `
        -ArgumentList @(
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/DIR=`"$installRoot`""
        ) `
        -Wait `
        -PassThru `
        -WindowStyle Hidden
    if ($install.ExitCode -ne 0) {
        throw "$Name installer failed with exit code $($install.ExitCode)."
    }

    $fixtureDirectories = @(
        (Join-Path $dataRoot "settings"),
        (Join-Path $dataRoot "logs"),
        (Join-Path $dataRoot "migrations"),
        (Join-Path $dataRoot "preserved-runtime\old\weights"),
        $workspaceRoot,
        $outputRoot,
        (Join-Path $installRoot "runtime")
    )
    if ($Name -ne "MissingGenerated") {
        $fixtureDirectories += @(
            (Join-Path $runtimeRoot "rvc\weights"),
            (Join-Path $runtimeRoot "rvc\logs"),
            $cacheRoot
        )
    }
    New-Item -ItemType Directory -Path $fixtureDirectories -Force | Out-Null

    $dataSentinel = Join-Path $workspaceRoot "song.txt"
    $outputSentinel = Join-Path $outputRoot "mix.wav"
    Set-Content -LiteralPath $dataSentinel -Value "song"
    Set-Content -LiteralPath $outputSentinel -Value "mix"
    if ($Name -ne "MissingGenerated") {
        Set-Content -LiteralPath (Join-Path $runtimeRoot "rvc\weights\voice.pth") -Value "voice"
        Set-Content -LiteralPath (Join-Path $runtimeRoot "rvc\logs\train.log") -Value "log"
        Set-Content -LiteralPath (Join-Path $cacheRoot "package.zip") -Value "cache"
    }
    Set-Content -LiteralPath (Join-Path $installRoot "runtime\generated.bin") -Value "app-runtime"
    Set-Content -LiteralPath (Join-Path $dataRoot "logs\diagnostic.log") -Value "diagnostic"
    Set-Content -LiteralPath (Join-Path $dataRoot "migrations\state.json") -Value "migration"
    Set-Content -LiteralPath (Join-Path $dataRoot "preserved-runtime\old\weights\old.pth") -Value "old"
    Set-Content -LiteralPath (Join-Path $dataRoot "session.state") -Value "local-state"
    Set-Content -LiteralPath $storageSentinel -Value "keep"

    $savedWorkspaceRoot = if ($Name -eq "ProtectedAppState") {
        $dataRoot
    }
    else {
        $workspaceRoot
    }
    $savedRuntimeRoot = if ($Name -eq "OverlappingRoots") {
        Join-Path $workspaceRoot "Runtime"
    }
    else {
        $runtimeRoot
    }
    $layout = if ($Name -eq "BrokenSettings") {
        '{"version":3,"storage_root":'
    }
    else {
        @{
            version = 3
            mode = "linked"
            storage_root = $storageRoot
            workspace_root = $savedWorkspaceRoot
            workspace_anchor = $storageRoot
            output_root = $outputRoot
            runtime_root = $savedRuntimeRoot
            cache_root = $cacheRoot
        } | ConvertTo-Json
    }
    [IO.File]::WriteAllText(
        (Join-Path $dataRoot "settings\storage.json"),
        $layout,
        [Text.UTF8Encoding]::new($false)
    )

    Set-VerificationCredential
    $env:JJZERO_DATA_ROOT = $dataRoot
    $arguments = @(
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/JJZEROCOMPLETEREMOVAL",
        "/LOG=`"$(Join-Path $scenarioRoot 'uninstall.log')`""
    )
    if ($Name -ne "PreserveWork") {
        $arguments += "/JJZERODELETEWORK"
    }
    $uninstaller = Join-Path $installRoot "unins000.exe"
    $uninstall = Start-Process `
        -FilePath $uninstaller `
        -ArgumentList $arguments `
        -Wait `
        -PassThru `
        -WindowStyle Hidden
    if ($uninstall.ExitCode -ne 0) {
        throw "$Name uninstaller failed with exit code $($uninstall.ExitCode)."
    }

    Assert-Removed -LiteralPath (Join-Path $installRoot "JJZero Audio.exe") -Message "Application executable remained"
    Assert-Removed -LiteralPath (Join-Path $installRoot "runtime") -Message "Application Runtime remained"
    Assert-Exists -LiteralPath $storageSentinel -Message "Unowned storage-root file was removed"
    if (Test-VerificationCredential) {
        throw "Google Drive verification credential remained after Complete Removal."
    }

    if ($unsafeLayout) {
        Assert-Exists -LiteralPath $runtimeRoot -Message "Runtime was removed after storage validation failed"
        Assert-Exists -LiteralPath $cacheRoot -Message "Cache was removed after storage validation failed"
        Assert-Exists -LiteralPath $dataSentinel -Message "Data was removed after storage validation failed"
        Assert-Exists -LiteralPath $outputSentinel -Message "Output was removed after storage validation failed"
        Assert-Exists -LiteralPath (Join-Path $dataRoot "session.state") -Message "Unknown local state was removed after storage validation failed"
        Assert-Removed -LiteralPath (Join-Path $dataRoot "settings") -Message "Known settings remained after Complete Removal"
        Assert-Removed -LiteralPath (Join-Path $dataRoot "logs") -Message "Known logs remained after Complete Removal"
        Assert-Removed -LiteralPath (Join-Path $dataRoot "migrations") -Message "Known migration state remained after Complete Removal"
        Assert-Removed -LiteralPath (Join-Path $dataRoot "preserved-runtime") -Message "Preserved Runtime remained after Complete Removal"
        $uninstallLog = Get-Content -LiteralPath (Join-Path $scenarioRoot "uninstall.log") -Raw
        if ($uninstallLog -notlike "*Complete Removal could not remove configured storage:*") {
            throw "$Name did not record the refused storage layout."
        }
    }
    elseif ($Name -ne "PreserveWork") {
        Assert-Removed -LiteralPath $runtimeRoot -Message "Configured Runtime remained"
        Assert-Removed -LiteralPath $cacheRoot -Message "Configured Cache remained"
        Assert-Removed -LiteralPath $dataRoot -Message "Local application state remained"
        Assert-Removed -LiteralPath $workspaceRoot -Message "Data remained after explicit work deletion"
        Assert-Removed -LiteralPath $outputRoot -Message "Output remained after explicit work deletion"
    }
    else {
        Assert-Removed -LiteralPath $runtimeRoot -Message "Configured Runtime remained"
        Assert-Removed -LiteralPath $cacheRoot -Message "Configured Cache remained"
        Assert-Removed -LiteralPath $dataRoot -Message "Local application state remained"
        Assert-Exists -LiteralPath $dataSentinel -Message "Data was removed without explicit consent"
        Assert-Exists -LiteralPath $outputSentinel -Message "Output was removed without explicit consent"
    }

    Write-Output "Verified Complete Removal ($Name): $installer"
}

try {
    if ($registrationExisted) {
        $registryExport = Start-Process `
            -FilePath reg.exe `
            -ArgumentList @("export", $uninstallRegistryKey, $registryBackup, "/y") `
            -Wait `
            -PassThru `
            -WindowStyle Hidden
        if ($registryExport.ExitCode -ne 0) {
            throw "Could not back up the existing uninstall registration."
        }
    }
    New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
    $scenarios = if ($Scenario -eq "All") {
        @(
            "PreserveWork",
            "DeleteWork",
            "MissingGenerated",
            "ProtectedAppState",
            "OverlappingRoots",
            "BrokenSettings"
        )
    }
    else {
        @($Scenario)
    }
    foreach ($currentScenario in $scenarios) {
        Invoke-CompleteUninstallScenario -Name $currentScenario
    }
}
finally {
    Remove-VerificationCredential
    Remove-Item -LiteralPath $uninstallRegistryPsPath -Recurse -Force -ErrorAction SilentlyContinue
    if ($registrationExisted -and (Test-Path -LiteralPath $registryBackup)) {
        $registryImport = Start-Process `
            -FilePath reg.exe `
            -ArgumentList @("import", $registryBackup) `
            -Wait `
            -PassThru `
            -WindowStyle Hidden
        if ($registryImport.ExitCode -ne 0) {
            Write-Warning "Could not restore the previous uninstall registration."
        }
    }
    if ($dataRootExisted) {
        $env:JJZERO_DATA_ROOT = $previousDataRoot
    }
    else {
        Remove-Item Env:JJZERO_DATA_ROOT -ErrorAction SilentlyContinue
    }
    if ($testRoot.StartsWith("$tempRoot\", [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $registryBackup -Force -ErrorAction SilentlyContinue
}
