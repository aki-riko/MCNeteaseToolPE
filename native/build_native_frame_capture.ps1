param(
    [string]$Compiler = $env:MCNETEASE_NATIVE_CXX
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$source = Join-Path $PSScriptRoot "native_frame_capture.cpp"
$outputDirectory = Join-Path $projectRoot "native_bin"
$output = Join-Path $outputDirectory "native_frame_capture.dll"

if (-not $Compiler) {
    $command = Get-Command "x86_64-w64-mingw32-g++.exe" -ErrorAction Stop
    $Compiler = $command.Source
}

New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
& $Compiler `
    -std=c++17 `
    -O2 `
    -Wall `
    -Wextra `
    -Werror `
    -shared `
    -static `
    -o $output `
    $source `
    -ladvapi32
if ($LASTEXITCODE -ne 0) {
    throw "原生帧采集 DLL 构建失败，退出码 $LASTEXITCODE"
}

Write-Output $output
