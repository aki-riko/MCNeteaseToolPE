# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
# 参数化 Nuitka standalone 构建入口。

[CmdletBinding()]
param(
    [string]$PythonPath = (Join-Path $PSScriptRoot ".venv\Scripts\python.exe"),
    [Parameter(Mandatory = $true)]
    [string]$Python27Root,
    [string]$McStubsPath = "",
    [string]$Python27SitePackages = "",
    [string]$Python27DllPath = "",
    [string]$OutputDir = (Join-Path $PSScriptRoot "build\nuitka")
)

$ErrorActionPreference = "Stop"

function Resolve-RequiredPath {
    param([string]$Path, [string]$Label)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Label 不存在: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Get-WindowsPeSubsystem {
    param([string]$ExecutablePath)

    $stream = [System.IO.File]::Open(
        $ExecutablePath, [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read
    )
    try {
        $reader = [System.IO.BinaryReader]::new($stream)
        $stream.Position = 0x3c
        $peOffset = $reader.ReadInt32()
        if ($peOffset -lt 0 -or ($peOffset + 94) -gt $stream.Length) {
            throw "PE 头偏移无效: $ExecutablePath"
        }
        $stream.Position = $peOffset
        if ($reader.ReadUInt32() -ne 0x00004550) {
            throw "PE 签名无效: $ExecutablePath"
        }
        $stream.Position = $peOffset + 24
        $magic = $reader.ReadUInt16()
        if ($magic -notin @(0x010b, 0x020b)) {
            throw "PE Optional Header 类型无效: $magic"
        }
        $stream.Position = $peOffset + 24 + 68
        return $reader.ReadUInt16()
    }
    finally {
        $stream.Dispose()
    }
}

$projectRoot = $PSScriptRoot
$python = Resolve-RequiredPath -Path $PythonPath -Label "Python 解释器"
$requirementsFile = Resolve-RequiredPath -Path (Join-Path $projectRoot "requirements.txt") -Label "运行依赖文件"
$prismRequirement = @(Get-Content -LiteralPath $requirementsFile | Where-Object { $_ -match '^prismqml==(.+)$' })
if ($prismRequirement.Count -ne 1) {
    throw "requirements.txt 必须且只能固定一个 prismqml==版本"
}
$expectedPrismVersion = $prismRequirement[0].Substring("prismqml==".Length).Trim()
$installedPrismVersion = (& $python -c "import importlib.metadata as m; print(m.version('prismqml'))").Trim()
if ($LASTEXITCODE -ne 0 -or $installedPrismVersion -ne $expectedPrismVersion) {
    throw "PrismQML 版本不匹配: 需要 $expectedPrismVersion，当前 $installedPrismVersion"
}
$enginePackage = (& $python -c "import pathlib, prismqml; print(pathlib.Path(prismqml.__file__).resolve().parent)").Trim()
if ($LASTEXITCODE -ne 0) {
    throw "无法从项目虚拟环境解析 PrismQML 包"
}
$enginePackage = Resolve-RequiredPath -Path $enginePackage -Label "PrismQML Python 包"
$engineQml = Resolve-RequiredPath -Path (Join-Path $enginePackage "PrismQML") -Label "PrismQML QML 模块"
$entryPoint = Resolve-RequiredPath -Path (Join-Path $projectRoot "main.py") -Label "应用入口"
$appIconPng = Resolve-RequiredPath -Path (Join-Path $projectRoot "assets\app_icon.png") -Label "应用 PNG 图标"
$moduleWhitelist = Resolve-RequiredPath -Path (Join-Path $projectRoot "src\netease_python_module_whitelist.txt") -Label "网易 Python 模块白名单"
$legacyWorker = Resolve-RequiredPath -Path (Join-Path $projectRoot "src\legacy_pylint_worker.py") -Label "Python 2.7 审核 worker"
$python27Root = Resolve-RequiredPath -Path $Python27Root -Label "Python 2.7 根目录"
$python27 = Resolve-RequiredPath -Path (Join-Path $python27Root "python.exe") -Label "Python 2.7 解释器"
$python27License = Resolve-RequiredPath -Path (Join-Path $python27Root "LICENSE.txt") -Label "Python 2.7 许可证"
$mcStubs = $null
if (-not [string]::IsNullOrWhiteSpace($McStubsPath)) {
    $mcStubs = Resolve-RequiredPath -Path $McStubsPath -Label "网易 Python 补全库"
}

if ([string]::IsNullOrWhiteSpace($Python27DllPath)) {
    $python27DllCandidates = @((Join-Path $python27Root "python27.dll"))
    $systemX86 = [Environment]::GetFolderPath([Environment+SpecialFolder]::SystemX86)
    if (-not [string]::IsNullOrWhiteSpace($systemX86)) {
        $python27DllCandidates += Join-Path $systemX86 "python27.dll"
    }
    $Python27DllPath = $python27DllCandidates |
        Where-Object { Test-Path -LiteralPath $_ } |
        Select-Object -First 1
}
$python27Dll = Resolve-RequiredPath -Path $Python27DllPath -Label "Python 2.7 运行库 python27.dll"

if ([string]::IsNullOrWhiteSpace($Python27SitePackages)) {
    $siteCommand = (
        "import os, sys, pylint, astroid; " +
        "p = os.path.dirname(os.path.dirname(os.path.abspath(pylint.__file__))); " +
        "a = os.path.dirname(os.path.dirname(os.path.abspath(astroid.__file__))); " +
        "sys.exit(2) if p != a else sys.stdout.write(p)"
    )
    $Python27SitePackages = (& $python27 -c $siteCommand).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($Python27SitePackages)) {
        throw "无法从 pylint/astroid 推导 Python 2.7 site-packages"
    }
}
$python27SitePackages = Resolve-RequiredPath -Path $Python27SitePackages -Label "Python 2.7 site-packages"

if (-not [System.IO.Path]::IsPathRooted($OutputDir)) {
    $OutputDir = Join-Path $projectRoot $OutputDir
}
if ((Test-Path -LiteralPath $OutputDir) -and (Get-ChildItem -LiteralPath $OutputDir -Force | Select-Object -First 1)) {
    throw "输出目录非空，为避免覆盖请指定新的 -OutputDir: $OutputDir"
}

& $python -m pip check
if ($LASTEXITCODE -ne 0) {
    throw "venv 依赖检查失败"
}

$iconOutputDir = Join-Path $OutputDir "branding"
$iconCommand = (
    "import json, sys; " +
    "from prismqml import nuitka_icon_options; " +
    "options = nuitka_icon_options(sys.argv[1], sys.argv[2]); " +
    "sys.stdout.write(json.dumps(options))"
)
$iconArgumentsJson = (& $python -c $iconCommand $appIconPng $iconOutputDir).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "应用图标构建参数生成失败"
}
$iconArguments = @($iconArgumentsJson | ConvertFrom-Json)
$arguments = @(
    "-m", "nuitka",
    "--mode=standalone",
    "--output-dir=$OutputDir",
    "--output-filename=MCNeteaseToolPE.exe",
    "--windows-console-mode=attach",
    "--assume-yes-for-downloads",
    "--enable-plugin=pyside6",
    "--include-qt-plugins=qml",
    "--include-package=prismqml",
    "--include-package=multiprocessing",
    "--include-data-file=$appIconPng=assets/app_icon.png",
    "--include-data-file=$moduleWhitelist=src/netease_python_module_whitelist.txt",
    "--include-data-file=$legacyWorker=src/legacy_pylint_worker.py",
    "--include-data-dir=$(Join-Path $projectRoot 'qml')=qml",
    "--include-data-dir=$engineQml=prismqml\PrismQML"
)
if ($null -ne $mcStubs) {
    $arguments += "--include-data-dir=$mcStubs=mc_stubs"
}
$arguments += $iconArguments
$arguments += $entryPoint
& $python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Nuitka 构建失败，退出码 $LASTEXITCODE"
}

$distDir = Resolve-RequiredPath -Path (Join-Path $OutputDir "main.dist") -Label "standalone 目录"
$legacyRuntimeDir = Join-Path $distDir "runtime\python27"
$legacyLibraryDir = Join-Path $legacyRuntimeDir "Lib"
New-Item -ItemType Directory -Force -Path $legacyRuntimeDir | Out-Null
Copy-Item -LiteralPath (Join-Path $python27Root "python.exe") -Destination $legacyRuntimeDir -Force
$pythonw = Join-Path $python27Root "pythonw.exe"
if (Test-Path -LiteralPath $pythonw) {
    Copy-Item -LiteralPath $pythonw -Destination $legacyRuntimeDir -Force
}
Copy-Item -LiteralPath $python27Dll -Destination $legacyRuntimeDir -Force
Copy-Item -LiteralPath $python27License -Destination (Join-Path $legacyRuntimeDir "LICENSE.txt") -Force
Copy-Item -LiteralPath (Join-Path $python27Root "Lib") -Destination $legacyRuntimeDir -Recurse -Force
if (Test-Path -LiteralPath (Join-Path $python27Root "DLLs")) {
    Copy-Item -LiteralPath (Join-Path $python27Root "DLLs") -Destination $legacyRuntimeDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path (Join-Path $legacyLibraryDir "site-packages") | Out-Null
$legacyPackages = @(
    "pylint", "astroid", "mccabe.py", "colorama", "isort", "singledispatch",
    "backports", "configparser.py", "enum", "concurrent", "six.py",
    "wrapt", "lazy_object_proxy"
)
$legacyTargetSitePackages = Join-Path $legacyLibraryDir "site-packages"
foreach ($package in $legacyPackages) {
    $source = Join-Path $python27SitePackages $package
    Resolve-RequiredPath -Path $source -Label "Python 2.7 运行时包 $package" | Out-Null
    Copy-Item -LiteralPath $source -Destination $legacyTargetSitePackages -Recurse -Force
}
foreach ($metadataPattern in @("pylint-*.dist-info", "astroid-*.dist-info")) {
    Get-ChildItem -LiteralPath $python27SitePackages -Filter $metadataPattern -Force |
        Copy-Item -Destination $legacyTargetSitePackages -Recurse -Force
}

$executable = Resolve-RequiredPath -Path (Join-Path $distDir "MCNeteaseToolPE.exe") -Label "应用可执行文件"
$windowsGuiSubsystem = 2
$actualSubsystem = Get-WindowsPeSubsystem -ExecutablePath $executable
if ($actualSubsystem -ne $windowsGuiSubsystem) {
    throw "应用 PE 子系统不是 Windows GUI: 期望 $windowsGuiSubsystem，实际 $actualSubsystem"
}
Write-Output "Windows PE 子系统验证通过: GUI ($actualSubsystem)"
$appIconIco = Resolve-RequiredPath -Path (Join-Path $iconOutputDir "app_icon.ico") -Label "生成的应用 ICO 图标"
Copy-Item -LiteralPath $appIconIco -Destination (Join-Path $distDir "app.ico") -Force
Write-Output "Nuitka standalone 构建完成: $executable"
