; ============================================================
;  GestionFacturas Windows 安装包（Inno Setup 6）
;  前置：先运行 platforms\windows\build_windows.ps1 生成 dist\GestionFacturas
;  编译：ISCC.exe platforms\windows\installer.iss
;  产物：dist\installer\GestionFacturas-Setup.exe
; ============================================================
#define MyAppName "GestionFacturas"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "GestionFacturas"
#define MyAppExeName "GestionFacturas.exe"
#define SourceDir "..\..\dist\GestionFacturas"

[Setup]
AppId={{B7F2C1D4-9A3E-4E58-8C21-6D0A5F7E1B33}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=
OutputDir=..\..\dist\installer
OutputBaseFilename=GestionFacturas-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayName={#MyAppName}

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Flags: unchecked

; 数据库与设置写在安装目录下，需要让普通用户可写（否则无法保存数据）
[Dirs]
Name: "{app}"; Permissions: users-modify

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\数据目录"; Filename: "{app}\data"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行 {#MyAppName}"; \
    Flags: nowait postinstall skipifsilent
