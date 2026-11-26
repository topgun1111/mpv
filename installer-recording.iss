; Takipli Oynat Kayit - kurulum (gomulu Python + mpv + ffmpeg). Model/ONNX YOK. Ana installer.iss'ten bagimsiz.
; Derleme: iscc /DAppVersion=x installer-recording.iss
; Onkosul: dist\TakipliOynatKayit icinde python\ (scripts/build_embedded.py --requirements requirements-recording.txt),
; mpv\mpv.exe (fetch_deps.ps1), ffmpeg\ffmpeg.exe (fetch_ffmpeg.ps1). Kurulumdan sonra elle bir sey gerekmez.
; Ana uygulamayla yan yana kurulabilir: farkli AppId, farkli klasor, farkli mpv IPC borusu (mpv-kayit).
; Guncelleme: yeni setup.exe'yi calistirmak yeter (AppId ayni -> ustune kurulur).
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define AppName "Takipli Oynat Kayit"

[Setup]
AppId={{B7E2D4A9-3C51-4F86-A0D7-5E19C8F6B2A3}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={autopf}\TakipliOynatKayit
DefaultGroupName={#AppName}
OutputDir=dist\installer-recording
OutputBaseFilename=TakipliOynatKayit-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; DirectML gerekmiyor: Windows 10 yeterli (python 3.11 + opencv tekerlekleri)
MinVersion=10.0
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayName={#AppName}
UsePreviousAppDir=yes
UsePreviousGroup=yes
UsePreviousPrivileges=yes
DisableDirPage=auto
DisableProgramGroupPage=auto
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "tr"; MessagesFile: "compiler:Languages\Turkish.isl"

[Files]
Source: "dist\TakipliOynatKayit\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[InstallDelete]
; Guncellemede eski surumden artakalan dosyalar calismayi bozmasin (mpv\portable_config\watch_later korunur)
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\recorder"
Type: filesandordirs; Name: "{app}\ffmpeg"
Type: filesandordirs; Name: "{app}\mpv\portable_config\scripts"
Type: filesandordirs; Name: "{app}\mpv\portable_config\script-modules"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\mpv\mpv.exe"; Parameters: "--player-operation-mode=pseudo-gui"; WorkingDir: "{app}"
Name: "{group}\Kaydi videoya aktar (video surukle)"; Filename: "{app}\Disa-Aktar.bat"; WorkingDir: "{app}"; IconFilename: "{app}\mpv\mpv.exe"
Name: "{group}\Ucuncu taraf lisanslar"; Filename: "notepad.exe"; Parameters: """{app}\THIRD_PARTY_NOTICES.md"""
Name: "{group}\Kaldir"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\mpv\mpv.exe"; Parameters: "--player-operation-mode=pseudo-gui"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Masaustu kisayolu olustur"

[Run]
Filename: "{app}\mpv\mpv.exe"; Parameters: "--player-operation-mode=pseudo-gui"; WorkingDir: "{app}"; Description: "Takipli Oynat Kayit'i simdi baslat"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\recorder\__pycache__"
Type: filesandordirs; Name: "{app}\python"
