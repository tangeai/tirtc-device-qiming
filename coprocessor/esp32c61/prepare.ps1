[CmdletBinding()]
param(
    [string]$Destination = (Join-Path $PSScriptRoot ".work\slave"),
    [string]$IdfPath = $env:IDF_PATH,
    [string]$PythonPath,
    [switch]$Refresh
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-Python {
    if ($PythonPath) {
        return (Resolve-Path -LiteralPath $PythonPath).Path
    }
    if ($env:IDF_PYTHON_ENV_PATH) {
        $candidate = Join-Path $env:IDF_PYTHON_ENV_PATH "Scripts\python.exe"
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    $command = Get-Command python -ErrorAction Stop
    return $command.Source
}

function Assert-TreeHash {
    param(
        [string]$Root,
        [pscustomobject]$Expected,
        [string]$Label
    )

    foreach ($property in $Expected.PSObject.Properties) {
        $path = Join-Path $Root ($property.Name.Replace("/", "\"))
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "$Label file is missing: $($property.Name)"
        }
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne [string]$property.Value) {
            throw "$Label hash mismatch: $($property.Name), expected=$($property.Value), actual=$actual"
        }
    }
}

function Apply-ExactSourceEdits {
    param(
        [string]$Root,
        [object[]]$Edits
    )

    foreach ($edit in $Edits) {
        $path = Join-Path $Root ($edit.path.Replace("/", "\"))
        $content = Get-Content -LiteralPath $path -Raw
        $old = [string]$edit.old
        $new = [string]$edit.new
        $matches = [regex]::Matches($content, [regex]::Escape($old)).Count
        if ($matches -ne 1) {
            throw "Expected one source-edit match in $($edit.path), found $matches"
        }
        $content = $content.Replace($old, $new)
        Set-Content -LiteralPath $path -Value $content -Encoding utf8 -NoNewline
    }
}

if (-not $IdfPath) {
    throw "IDF_PATH is not set. Pass -IdfPath for ESP-IDF 5.5.4."
}
$idf = (Resolve-Path -LiteralPath $IdfPath).Path
$idfPy = Join-Path $idf "tools\idf.py"
if (-not (Test-Path -LiteralPath $idfPy -PathType Leaf)) {
    throw "idf.py was not found below: $idf"
}
$python = Resolve-Python
$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot "source-manifest.json") -Raw |
    ConvertFrom-Json
$destinationPath = [IO.Path]::GetFullPath($Destination)
$workRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".work"))
if ((Split-Path -Leaf $destinationPath) -ne "slave" -or
    -not $destinationPath.StartsWith($workRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Destination must be the slave directory below $workRoot"
}

if ($Refresh -and (Test-Path -LiteralPath $destinationPath)) {
    Remove-Item -LiteralPath $destinationPath -Recurse -Force
}

$createdSource = $false
if (-not (Test-Path -LiteralPath $destinationPath)) {
    $parent = Split-Path -Parent $destinationPath
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    Push-Location $parent
    try {
        & $python $idfPy create-project-from-example `
            "espressif/esp_hosted=$($manifest.upstream.version):$($manifest.upstream.example)"
        if ($LASTEXITCODE -ne 0) {
            throw "ESP-Hosted example download failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
    Assert-TreeHash -Root $destinationPath -Expected $manifest.upstream.sha256 -Label "Upstream"
    $createdSource = $true
}

$overlayRoot = Join-Path $PSScriptRoot "overlay"
if ($createdSource) {
    Apply-ExactSourceEdits -Root $destinationPath -Edits $manifest.source_edits
    Get-ChildItem -LiteralPath $overlayRoot -Recurse -File | ForEach-Object {
        $relative = $_.FullName.Substring($overlayRoot.Length + 1)
        $target = Join-Path $destinationPath $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $target -Force
    }
}
Assert-TreeHash -Root $destinationPath -Expected $manifest.overlay_sha256 -Label "Qiming overlay"
Assert-TreeHash -Root $destinationPath -Expected $manifest.prepared_sha256 -Label "Prepared source"

Write-Output "Prepared ESP32-C61 source: $destinationPath"
Write-Output "Upstream: $($manifest.upstream.component) $($manifest.upstream.version)"
