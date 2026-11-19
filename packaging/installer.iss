; Установщик «Виртуального проводника» (Inno Setup 6).
; Собирается автоматически на GitHub:  ISCC.exe /DAppVersion=1.5.0 packaging\installer.iss
; Берёт готовую папку dist\VirtualExplorer (после PyInstaller), кладёт результат в dist\.
;
; * ставится без прав администратора - в %LOCALAPPDATA%\Programs (можно выбрать «для всех»);
; * ярлык в меню «Пуск», по желанию - на рабочем столе;
; * новая версия ставится поверх старой, теги и настройки сохраняются
;   (они лежат отдельно - в %LOCALAPPDATA%\VirtualExplorer);
; * при удалении программа спрашивает, удалить ли и библиотеку тегов тоже (по умолчанию - нет).

#ifndef AppVersion
  #define AppVersion "1.5.0"
#endif
#define AppName "Виртуальный проводник"
#define AppExe "VirtualExplorer.exe"

[Setup]
AppId={{6F3C2B1E-8A4D-4E57-9B21-5C0D7E4A9F13}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Virtual Explorer
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\Virtual Explorer
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=VirtualExplorer-{#AppVersion}-Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
MinVersion=10.0
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать значок на рабочем столе"; GroupDescription: "Дополнительно:"

[InstallDelete]
; старые файлы прошлой версии программы (не данные пользователя!) - чтобы не мешались
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\VirtualExplorer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Запустить {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent) then
  begin
    DataDir := ExpandConstant('{localappdata}\VirtualExplorer');
    if DirExists(DataDir) then
      if MsgBox('Удалить и библиотеку тоже - теги, коллекции, настройки и резервные копии?' + #13#10#13#10 +
                'Сами файлы на диске не пострадают в любом случае.' + #13#10 +
                'Если собираешься поставить программу снова - нажми «Нет».',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
