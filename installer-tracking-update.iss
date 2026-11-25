[Setup]
AppId={{6F3A2C1E-8B47-4D5A-9E21-7C0D4B8A1F55}
AppName=Takipli Oynat Takip Güncellemesi
AppVersion=1.2.0
DefaultDirName={autopf}\TakipliOynat
DisableDirPage=no
AppendDefaultDirName=no
UsePreviousAppDir=yes
Uninstallable=no
CreateUninstallRegKey=no
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist\tracking-update
OutputBaseFilename=TakipliOynat-Tracking-Update
Compression=lzma2
CloseApplications=yes
RestartApplications=no
WizardStyle=modern

[Languages]
Name: "tr"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "windows-tracking-update\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs

[CustomMessages]
tr.WrongFolder=Baslat.bat ve tracker.exe dosyalarını içeren mevcut Takipli Oynat kurulum klasörünü seçin.
en.WrongFolder=Select the existing Takipli Oynat installation folder containing Baslat.bat and tracker.exe.

[Code]
function IsTrackingApp(Dir: String): Boolean;
begin
  Result := FileExists(AddBackslash(Dir) + 'Baslat.bat') and
            FileExists(AddBackslash(Dir) + 'tracker.exe') and
            FileExists(AddBackslash(Dir) + 'mpv\mpv.exe') and
            FileExists(AddBackslash(Dir) + 'python\python.exe') and
            FileExists(AddBackslash(Dir) + 'tracker\__init__.py');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpSelectDir) and not IsTrackingApp(WizardDirValue) then begin
    SuppressibleMsgBox(CustomMessage('WrongFolder'), mbError, MB_OK, IDOK);
    Result := False;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not IsTrackingApp(WizardDirValue) then
    Result := CustomMessage('WrongFolder');
end;
