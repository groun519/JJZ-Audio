function Find-WindowsSdkTool {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    $candidates = @()
    if ($command) {
        $candidates += $command.Source
    }

    $kitRoot = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
    if (Test-Path -LiteralPath $kitRoot -PathType Container) {
        $escapedName = [Regex]::Escape($Name)
        $candidates += Get-ChildItem -LiteralPath $kitRoot -Filter $Name -File -Recurse |
            Where-Object { $_.FullName -match "\\x64\\$escapedName$" } |
            Sort-Object FullName -Descending |
            Select-Object -ExpandProperty FullName
    }

    $resolved = $candidates |
        Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } |
        Select-Object -First 1
    if (-not $resolved) {
        throw "Windows SDK tool was not found: $Name"
    }
    return $resolved
}
