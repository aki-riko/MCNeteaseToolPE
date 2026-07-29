; SPDX-License-Identifier: GPL-3.0-or-later
; ============================================================================
; MCNeteaseToolPE Inno Setup 打包脚本
; 用途:将 Nuitka standalone 的 main.dist 目录打包为静默可安装的 Setup 安装包,
;       供 PrismQML AutoUpdater 门面下载后静默安装。
;
; 与自动更新的契约(务必对齐,勿改):
;   1. 输出文件名必须包含关键词 "Setup"(见 src/config.py UPDATE_ASSET_KEYWORD),
;      Updater 依据该关键词从 GitHub release assets 中挑选安装包。
;   2. 需支持静默参数 /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS
;      /RESTARTAPPLICATIONS(见 src/config.py INSTALLER_SILENT_ARGS)。InnoSetup 原生支持。
;   3. AppId 固定(勿随版本变化),使新版覆盖安装到同一位置。
;
; 用法:
;   iscc /DMyAppVersion=0.1.0.4 /DBuildDir="..\build\nuitka-release\main.dist" installer\MCNeteaseToolPE.iss
;   (未传 MyAppVersion / BuildDir 时用下方默认值)
; ============================================================================

#ifndef MyAppVersion
  #define MyAppVersion "0.1.0.4"
#endif
#ifndef BuildDir
  #define BuildDir "..\build\nuitka\main.dist"
#endif
#ifndef ChineseMessagesFile
  #define ChineseMessagesFile "compiler:Languages\ChineseSimplified.isl"
#endif

#define MyAppName "MCNeteaseToolPE"
#define MyAppExeName "MCNeteaseToolPE.exe"
#define MyAppUserModelID "PrismQML." + MyAppName
#define MyAppPublisher "aki-riko"
#define MyAppURL "https://github.com/aki-riko/MCNeteaseToolPE"

[Setup]
; AppId 固定 GUID,确保各版本安装到同一位置(升级覆盖,而非并存)。
AppId={{7B3F2E1A-9C4D-4A6B-8E2F-1D5C6A7B8E90}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; 输出:关键词 Setup 必须出现在文件名中,供 Updater 资源匹配。
OutputBaseFilename={#MyAppName}-{#MyAppVersion}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; 64 位应用:仅在 x64 安装,并使用 64 位安装模式。
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 允许静默安装时无需管理员交互(写入 Program Files 仍需提权,由 InnoSetup 处理)。
PrivilegesRequired=admin
; 图标可选:仅当 build 目录存在 app.ico 时设置,避免 iscc 因缺文件报错。
#if FileExists(BuildDir + "\app.ico")
SetupIconFile={#BuildDir}\app.ico
#endif

[Languages]
Name: "chinesesimplified"; MessagesFile: "{#ChineseMessagesFile}"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; 打包 Nuitka standalone 的完整 main.dist 目录。
; 排除调试符号与临时日志，其他运行时文件全部保留。
Source: "{#BuildDir}\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#BuildDir}\*"; DestDir: "{app}"; Excludes: "*.pdb,*.log"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; 与 PrismQML 运行时派生的 AUMID 保持一致，避免 Shell 将任务栏项回退为通用图标。
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; AppUserModelID: "{#MyAppUserModelID}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; AppUserModelID: "{#MyAppUserModelID}"; Tasks: desktopicon

[Run]
; 安装完成后启动(静默升级场景配合 /AUTORESTARTAPP 由 InnoSetup 处理)。
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
