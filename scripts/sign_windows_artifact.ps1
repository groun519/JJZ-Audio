param(
    [Parameter(Mandatory = $true)]
    [string[]]$ArtifactPath,
    [string]$CertificateThumbprint = $env:JJZERO_SIGN_CERT_THUMBPRINT,
    [string]$CertificatePath = $env:JJZERO_SIGN_CERT_PATH,
    [string]$CertificatePassword = $env:JJZERO_SIGN_CERT_PASSWORD,
    [string]$TimestampUrl = "https://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "windows_sdk_tools.ps1")
$signTool = Find-WindowsSdkTool "signtool.exe"

$identityArguments = @()
if ($CertificateThumbprint) {
    $identityArguments = @("/sha1", $CertificateThumbprint.Replace(" ", ""))
}
elseif ($CertificatePath) {
    $resolvedCertificate = (Resolve-Path -LiteralPath $CertificatePath).Path
    $identityArguments = @("/f", $resolvedCertificate)
    if ($CertificatePassword) {
        $identityArguments += @("/p", $CertificatePassword)
    }
}
else {
    throw "Set JJZERO_SIGN_CERT_THUMBPRINT or JJZERO_SIGN_CERT_PATH before signing."
}

foreach ($path in $ArtifactPath) {
    $artifact = (Resolve-Path -LiteralPath $path).Path
    & $signTool sign /fd SHA256 /td SHA256 /tr $TimestampUrl @identityArguments $artifact
    if ($LASTEXITCODE -ne 0) {
        throw "Authenticode signing failed with exit code $LASTEXITCODE`: $artifact"
    }
    & $signTool verify /pa /all $artifact
    if ($LASTEXITCODE -ne 0) {
        throw "Authenticode verification failed with exit code $LASTEXITCODE`: $artifact"
    }
}
