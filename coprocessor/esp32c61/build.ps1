[CmdletBinding()]
param(
    [string]$IdfPath = $env:IDF_PATH,
    [string]$PythonPath,
    [switch]$RefreshSource
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $IdfPath) {
    throw "IDF_PATH is not set. Pass -IdfPath for ESP-IDF 5.5.4."
}
$idf = (Resolve-Path -LiteralPath $IdfPath).Path
$exportScript = Join-Path $idf "export.ps1"
if (-not (Test-Path -LiteralPath $exportScript -PathType Leaf)) {
    throw "ESP-IDF export.ps1 was not found below: $idf"
}
. $exportScript

$prepareArgs = @{
    IdfPath = $IdfPath
}
if ($PythonPath) {
    $prepareArgs.PythonPath = $PythonPath
}
if ($RefreshSource) {
    $prepareArgs.Refresh = $true
}
& (Join-Path $PSScriptRoot "prepare.ps1") @prepareArgs

$project = Join-Path $PSScriptRoot ".work\slave"
$build = Join-Path $PSScriptRoot ".work\b"
if ($PythonPath) {
    $python = (Resolve-Path -LiteralPath $PythonPath).Path
} elseif ($env:IDF_PYTHON_ENV_PATH -and
          (Test-Path -LiteralPath (Join-Path $env:IDF_PYTHON_ENV_PATH "Scripts\python.exe"))) {
    $python = (Resolve-Path -LiteralPath (Join-Path $env:IDF_PYTHON_ENV_PATH "Scripts\python.exe")).Path
} else {
    $python = (Get-Command python -ErrorAction Stop).Source
}
$idfPy = Join-Path $idf "tools\idf.py"

Push-Location $project
try {
    if (-not (Test-Path -LiteralPath "sdkconfig")) {
        & $python $idfPy -B $build set-target esp32c61
        if ($LASTEXITCODE -ne 0) {
            throw "ESP32-C61 set-target failed with exit code $LASTEXITCODE"
        }
    }
    & $python $idfPy -B $build build
    if ($LASTEXITCODE -ne 0) {
        throw "ESP32-C61 build failed with exit code $LASTEXITCODE"
    }

    $fullImage = Join-Path $build "qiming-c61-network-adapter-full.bin"
    & $python -m esptool --chip esp32c61 merge_bin --flash_mode dio --flash_freq 80m `
        --flash_size 4MB --fill-flash-size 4MB -o $fullImage `
        0x0 (Join-Path $build "bootloader\bootloader.bin") `
        0x8000 (Join-Path $build "partition_table\partition-table.bin") `
        0xd000 (Join-Path $build "ota_data_initial.bin") `
        0x10000 (Join-Path $build "network_adapter.bin")
    if ($LASTEXITCODE -ne 0) {
        throw "ESP32-C61 full-image merge failed with exit code $LASTEXITCODE"
    }

    foreach ($artifact in @((Join-Path $build "network_adapter.bin"), $fullImage)) {
        $item = Get-Item -LiteralPath $artifact
        $hash = (Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash
        Write-Output "$($item.Name) size=$($item.Length) sha256=$hash path=$($item.FullName)"
    }
} finally {
    Pop-Location
}
