; Inno Setup betiği (Parça 14'te gömülü Python + DirectML ile genişletilecek)
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
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest

[Files]
Source: "dist\TakipliOynat\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\mpv\mpv.exe"; Parameters: "--player-operation-mode=pseudo-gui"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\mpv\mpv.exe"; Parameters: "--player-operation-mode=pseudo-gui"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Masaüstü kısayolu oluştur"; Flags: unchecked
