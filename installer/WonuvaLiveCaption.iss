; Inno Setup script for Wonuva Live Caption (https://jrsoftware.org/isinfo.php, version 6.3+).
; Built by build_exe.bat, which passes /DAppVersion=... and, when signing is configured,
; /DSIGN plus the "wonuva" sign tool (see sign.bat).
;
; Installs the PyInstaller build from dist\WonuvaLiveCaption for the current user (no admin
; prompt). The speech models are NOT in the installer: the app downloads them on first run into
; %LOCALAPPDATA%\Wonuva Live Caption\models.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Wonuva Live Caption"
#define AppExe "WonuvaLiveCaption.exe"
#define AppPublisher "Wonuva"
#define AppURL "https://wonuva.com"
#define BuildDir "..\dist\WonuvaLiveCaption"

[Setup]
; Never change AppId: it's how Windows recognizes upgrades of the same app.
AppId={{12FB9CE4-CD8B-4046-AF88-FA87D002B108}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoCompany={#AppPublisher}
; Per-user install into %LOCALAPPDATA%\Programs (no UAC prompt); the user may pick all-users.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
; 64-bit Windows 10 version 2004 or later (needed for hiding from screen share).
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
OutputDir=..\dist\installer
OutputBaseFilename=WonuvaLiveCaptionSetup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
; The app holds this mutex while running (single_instance.py), so Setup asks to close it first.
AppMutex=WonuvaLiveCaption.SingleInstance
CloseApplications=yes
#ifdef SIGN
SignTool=wonuva
SignedUninstaller=yes
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Everything PyInstaller produced, minus anything user- or machine-specific.
Source: "{#BuildDir}\*"; DestDir: "{app}"; Excludes: "models\*,settings.json,openai_api_key.txt,livecaption.log"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
// Settings, the log and the downloaded models live in %LOCALAPPDATA%\Wonuva Live Caption, not in
// {app}. Offer to remove them too (default: keep, so a reinstall doesn't re-download 4.4 GB).
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\Wonuva Live Caption');
    if DirExists(DataDir) and not UninstallSilent then
      if MsgBox('Also delete your settings (including the saved OpenAI key and resume) and the ' +
                'downloaded speech models (about 4.4 GB)?' + #13#10#13#10 + DataDir,
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
