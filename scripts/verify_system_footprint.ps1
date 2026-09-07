param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,

    [Parameter(Mandatory = $true)]
    [string]$PreviousInstallerPath,

    [string]$RuntimePackageIndex = "",
    [string]$EvidencePath = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$installer = (Resolve-Path -LiteralPath $InstallerPath).Path
$previousInstaller = (Resolve-Path -LiteralPath $PreviousInstallerPath).Path
$installationGate = Join-Path $PSScriptRoot "verify_release_installation.ps1"

function Get-Sha256Hex([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha256.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha256.Dispose()
        $stream.Dispose()
    }
}

function Get-EnvironmentSnapshot([EnvironmentVariableTarget]$Target) {
    $entries = @()
    $variables = [Environment]::GetEnvironmentVariables($Target)
    foreach ($name in @($variables.Keys | ForEach-Object { [string]$_ } | Sort-Object)) {
        $entries += [PSCustomObject]@{
            name = $name
            value = [string]$variables[$name]
        }
    }
    return @($entries)
}

function Convert-RegistryValue($Value) {
    if ($null -eq $Value) {
        return $null
    }
    if ($Value -is [byte[]]) {
        return [Convert]::ToBase64String($Value)
    }
    if ($Value -is [array]) {
        return @($Value | ForEach-Object { [string]$_ })
    }
    return [string]$Value
}

function Get-RegistrySnapshot([string[]]$Roots) {
    $entries = @()
    foreach ($root in $Roots) {
        if (-not (Test-Path -LiteralPath $root)) {
            continue
        }
        $keys = @((Get-Item -LiteralPath $root))
        $keys += @(Get-ChildItem -LiteralPath $root -Recurse -ErrorAction SilentlyContinue)
        foreach ($key in @($keys | Sort-Object Name)) {
            $properties = Get-ItemProperty -LiteralPath $key.PSPath
            $values = @()
            foreach ($property in @(
                $properties.PSObject.Properties |
                    Where-Object { $_.Name -notlike "PS*" } |
                    Sort-Object Name
            )) {
                $values += [PSCustomObject]@{
                    name = $property.Name
                    value = Convert-RegistryValue $property.Value
                }
            }
            $entries += [PSCustomObject]@{
                key = [string]$key.Name
                values = @($values)
            }
        }
    }
    return @($entries | Sort-Object key)
}

function Get-PythonCommands {
    $commands = @()
    foreach ($name in @("python.exe", "python3.exe", "py.exe")) {
        foreach ($command in @(Get-Command $name -All -CommandType Application -ErrorAction SilentlyContinue)) {
            $commands += [string]$command.Source
        }
    }
    return @($commands | Sort-Object -Unique)
}

function Get-GpuDrivers {
    $adapters = @()
    foreach ($adapter in @(Get-CimInstance Win32_VideoController -ErrorAction Stop)) {
        $driverDate = if ($adapter.DriverDate) {
            ([DateTime]$adapter.DriverDate).ToUniversalTime().ToString("o")
        } else {
            ""
        }
        $adapters += [PSCustomObject]@{
            name = [string]$adapter.Name
            pnp_device_id = [string]$adapter.PNPDeviceID
            driver_version = [string]$adapter.DriverVersion
            driver_date = $driverDate
        }
    }
    return @($adapters | Sort-Object pnp_device_id, name)
}

function Get-ServiceDefinitions {
    $services = @()
    foreach ($service in @(Get-CimInstance Win32_Service -ErrorAction Stop)) {
        $services += [PSCustomObject]@{
            name = [string]$service.Name
            start_mode = [string]$service.StartMode
            path_name = [string]$service.PathName
            service_type = [string]$service.ServiceType
        }
    }
    return @($services | Sort-Object name)
}

function Get-SystemSnapshot {
    $pythonRegistryRoots = @(
        "HKCU:\Software\Python",
        "HKLM:\Software\Python",
        "HKLM:\Software\WOW6432Node\Python"
    )
    $startupRegistryRoots = @(
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run",
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce",
        "HKLM:\Software\Microsoft\Windows\CurrentVersion\Run",
        "HKLM:\Software\Microsoft\Windows\CurrentVersion\RunOnce",
        "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run",
        "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\RunOnce"
    )
    $associationRoots = @(
        "HKCU:\Software\Classes\Applications\JJZero Audio.exe",
        "HKLM:\Software\Classes\Applications\JJZero Audio.exe"
    )
    return [PSCustomObject]@{
        user_environment = @(Get-EnvironmentSnapshot ([EnvironmentVariableTarget]::User))
        machine_environment = @(Get-EnvironmentSnapshot ([EnvironmentVariableTarget]::Machine))
        python_commands = @(Get-PythonCommands)
        python_registry = @(Get-RegistrySnapshot $pythonRegistryRoots)
        gpu_drivers = @(Get-GpuDrivers)
        services = @(Get-ServiceDefinitions)
        startup_entries = @(Get-RegistrySnapshot $startupRegistryRoots)
        jjzero_file_associations = @(Get-RegistrySnapshot $associationRoots)
    }
}

function Get-ChangedSections($Before, $After) {
    $changed = @()
    foreach ($name in @(
        "user_environment",
        "machine_environment",
        "python_commands",
        "python_registry",
        "gpu_drivers",
        "services",
        "startup_entries",
        "jjzero_file_associations"
    )) {
        $beforeJson = $Before.$name | ConvertTo-Json -Depth 20 -Compress
        $afterJson = $After.$name | ConvertTo-Json -Depth 20 -Compress
        if ($beforeJson -cne $afterJson) {
            $changed += $name
        }
    }
    return @($changed)
}

function Write-Evidence($Evidence) {
    if (-not $EvidencePath) {
        return
    }
    $resolvedEvidence = [IO.Path]::GetFullPath($EvidencePath)
    $parent = Split-Path -Parent $resolvedEvidence
    if ($parent) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $encoding = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText(
        $resolvedEvidence,
        ($Evidence | ConvertTo-Json -Depth 30),
        $encoding
    )
}

$before = Get-SystemSnapshot
$gateArguments = @{
    InstallerPath = $installer
    PreviousInstallerPath = $previousInstaller
}
if ($RuntimePackageIndex) {
    $gateArguments.RuntimePackageIndex = (Resolve-Path -LiteralPath $RuntimePackageIndex).Path
}

& $installationGate @gateArguments
if ($LASTEXITCODE -ne 0) {
    throw "Release installation gate failed with exit code $LASTEXITCODE."
}

$after = Get-SystemSnapshot
$changedSections = @(Get-ChangedSections $before $after)
$evidence = [PSCustomObject]@{
    schema_version = 1
    captured_at = [DateTime]::UtcNow.ToString("o")
    installer = [PSCustomObject]@{
        path = $installer
        sha256 = Get-Sha256Hex $installer
    }
    previous_installer = [PSCustomObject]@{
        path = $previousInstaller
        sha256 = Get-Sha256Hex $previousInstaller
    }
    passed = $changedSections.Count -eq 0
    changed_sections = $changedSections
    before = $before
    after = $after
}
Write-Evidence $evidence

if ($changedSections.Count -ne 0) {
    throw "Installer changed protected system state: $($changedSections -join ', ')"
}

Write-Output "Protected Windows system state was unchanged after install, update, and removal."
