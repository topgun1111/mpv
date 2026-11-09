; Takipli Oynat - tam kurulum (gömülü Python + mpv + DirectML). Derleme: iscc /DAppVersion=x installer.iss
; Önkoşul: dist\TakipliOynat içinde python\ (scripts/build_embedded.py) ve mpv\mpv.exe (fetch_deps.ps1).
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define AppName "Takipli Oynat"

[Setup]
AppId={{6F3A2C1E-8B47-4D5A-9E21-7C0D4B8A1F55}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={autopf}\TakipliOynat
DefaultGroupName={#AppName}
OutputDir=dist\installer
OutputBaseFilename=TakipliOynat-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; DirectML için Windows 10 sürüm 1903 (18362) ve üstü
MinVersion=10.0.18362
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayName={#AppName}

[Languages]
Name: "tr"; MessagesFile: "compiler:Languages\Turkish.isl"

[Files]
Source: "dist\TakipliOynat\*"; DestDir: "{app}"; Excludes: "models\*.onnx"; Flags: recursesubdirs createallsubdirs ignoreversion

[Dirs]
; Modeller kullanıcı tarafından eklenir; kaldırmada silinmesin
Name: "{app}\models"; Flags: uninsneveruninstall

[Icons]
Name: "{group}\{#AppName} (canlı)"; Filename: "{app}\Baslat.bat"; WorkingDir: "{app}"; IconFilename: "{app}\mpv\mpv.exe"
Name: "{group}\{#AppName} (offline, video sürükle)"; Filename: "{app}\Offline.bat"; WorkingDir: "{app}"; IconFilename: "{app}\mpv\mpv.exe"
Name: "{group}\Modeller klasörü"; Filename: "{app}\models"
Name: "{group}\Üçüncü taraf lisanslar"; Filename: "notepad.exe"; Parameters: """{app}\THIRD_PARTY_NOTICES.md"""
Name: "{group}\Kaldır"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Baslat.bat"; WorkingDir: "{app}"; IconFilename: "{app}\mpv\mpv.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Masaüstü kısayolu oluştur"; Flags: unchecked

[Run]
Filename: "notepad.exe"; Parameters: """{app}\models\MODELLER.txt"""; Description: "Gerekli modeller hakkında bilgi (MODELLER.txt)"; Flags: postinstall nowait skipifsilent unchecked

[UninstallDelete]
; Çalışma sırasında oluşan .pyc önbellekleri
Type: filesandordirs; Name: "{app}\tracker\__pycache__"
Type: filesandordirs; Name: "{app}\python"
