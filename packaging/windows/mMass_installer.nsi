; NSIS installer for mMass Windows release bundle.

Unicode true
RequestExecutionLevel admin

; NSIS defaults to zlib, which leaves roughly a third of the download on the
; table for a bundle this size. /SOLID lets LZMA find matches across files --
; it matters here because the payload is dominated by a few very large DLLs
; (llvmlite's LLVM build alone is ~115 MB, and compresses to ~26 MB this way
; against ~39 MB with deflate). Costs build time, not install time.
SetCompressor /SOLID lzma

!include "MUI2.nsh"
!include "LogicLib.nsh"

!ifndef APP_VERSION
  !error "APP_VERSION define is required"
!endif

!ifndef SOURCE_DIR
  !error "SOURCE_DIR define is required"
!endif

!ifndef OUTPUT_NAME
  !error "OUTPUT_NAME define is required"
!endif

!define APP_NAME "mMass"
!define COMPANY_NAME "mMass Project"

!define APP_EXE "$INSTDIR\mMass.exe"

; File associations. Each ProgID names a kind of file and carries the icon
; (the one embedded in mMass.exe) and the command that opens it. Both go under
; HKLM\Software\Classes in the 64-bit registry view, which is where Explorer
; looks for them (the installer itself is a 32-bit program).
!macro RegisterProgId PROGID DESC
  WriteRegStr HKLM "Software\Classes\${PROGID}" "" "${DESC}"
  WriteRegStr HKLM "Software\Classes\${PROGID}\DefaultIcon" "" "${APP_EXE},0"
  WriteRegStr HKLM "Software\Classes\${PROGID}\shell\open" "FriendlyAppName" "${APP_NAME}"
  WriteRegStr HKLM "Software\Classes\${PROGID}\shell\open\command" "" '"${APP_EXE}" "%1"'
!macroend

; mMass's own formats: mMass is their default program, also when an older
; install (or another program) registered them under a different ProgID.
!macro ClaimExt EXT PROGID
  WriteRegStr HKLM "Software\Classes\${EXT}\OpenWithProgids" "${PROGID}" ""
  WriteRegStr HKLM "Software\Classes\${EXT}" "" "${PROGID}"
!macroend

; Formats shared with other programs: mMass is always offered under "Open
; with", but becomes the default only when no other program has claimed the
; extension, so installing mMass never takes mzML, mzXML, mzData or MGF files
; away from another viewer.
!macro RegisterExt EXT PROGID
  WriteRegStr HKLM "Software\Classes\${EXT}\OpenWithProgids" "${PROGID}" ""
  ReadRegStr $1 HKLM "Software\Classes\${EXT}" ""
  ${If} $1 == ""
    WriteRegStr HKLM "Software\Classes\${EXT}" "" "${PROGID}"
  ${EndIf}
!macroend

!macro UnregisterExt EXT PROGID
  DeleteRegValue HKLM "Software\Classes\${EXT}\OpenWithProgids" "${PROGID}"
  ReadRegStr $1 HKLM "Software\Classes\${EXT}" ""
  ${If} $1 == "${PROGID}"
    DeleteRegValue HKLM "Software\Classes\${EXT}" ""
  ${EndIf}
  DeleteRegKey /ifempty HKLM "Software\Classes\${EXT}\OpenWithProgids"
  DeleteRegKey /ifempty HKLM "Software\Classes\${EXT}"
!macroend

Name "${APP_NAME} ${APP_VERSION}"
OutFile "${OUTPUT_NAME}"
InstallDir "$PROGRAMFILES64\${APP_NAME}"
InstallDirRegKey HKLM "Software\${APP_NAME}" "InstallDir"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES

; Offer to start mMass straight from the finish page. Ticking the box and
; clicking Finish closes the installer and launches the app.
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Open mMass"
!define MUI_FINISHPAGE_RUN_FUNCTION LaunchApp
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_COMPONENTS
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

!insertmacro MUI_LANGUAGE "English"

Var RemoveUserConfigs

Section "Install"
  InitPluginsDir
  CreateDirectory "$PLUGINSDIR\mmass_user_configs"

  ; Preserve user-customized config files across reinstalls/upgrades.
  ; Both formats: libraries are JSON since 7.0, but an install that has not
  ; been launched since the upgrade still holds the pre-7.0 XML.
  IfFileExists "$INSTDIR\gui\configs\*.json" 0 +2
  CopyFiles /SILENT "$INSTDIR\gui\configs\*.json" "$PLUGINSDIR\mmass_user_configs"
  IfFileExists "$INSTDIR\gui\configs\*.xml" 0 +2
  CopyFiles /SILENT "$INSTDIR\gui\configs\*.xml" "$PLUGINSDIR\mmass_user_configs"

  ; Wipe any existing install so files left behind by an older version
  ; (eg. version-named metadata folders) cannot shadow the new bundle and
  ; cause stale info, such as the version number shown in the About panel.
  RMDir /r "$INSTDIR"

  SetOutPath "$INSTDIR"
  File /r "${SOURCE_DIR}\*.*"

  ; Restore preserved files so installer defaults do not overwrite user edits.
  IfFileExists "$PLUGINSDIR\mmass_user_configs\*.json" 0 +2
  CopyFiles /SILENT "$PLUGINSDIR\mmass_user_configs\*.json" "$INSTDIR\gui\configs"
  IfFileExists "$PLUGINSDIR\mmass_user_configs\*.xml" 0 +2
  CopyFiles /SILENT "$PLUGINSDIR\mmass_user_configs\*.xml" "$INSTDIR\gui\configs"

  WriteRegStr HKLM "Software\${APP_NAME}" "InstallDir" "$INSTDIR"

  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayName" "${APP_NAME} ${APP_VERSION}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "Publisher" "${COMPANY_NAME}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "NoModify" 1
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "NoRepair" 1

  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\mMass.lnk" "$INSTDIR\mMass.exe" "" "$INSTDIR\mMass.exe" 0
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\Uninstall mMass.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortcut "$DESKTOP\mMass.lnk" "$INSTDIR\mMass.exe" "" "$INSTDIR\mMass.exe" 0

  ; File associations: documents and sessions are mMass's own (ClaimExt), the
  ; open data formats are shared with other programs (RegisterExt).
  SetRegView 64
  !insertmacro RegisterProgId "mMass.Document" "mMass spectrum document"
  !insertmacro RegisterProgId "mMass.Session" "mMass session"
  !insertmacro RegisterProgId "mMass.Data" "Mass spectrometry data"
  !insertmacro ClaimExt ".msd" "mMass.Document"
  !insertmacro ClaimExt ".mses" "mMass.Session"
  !insertmacro RegisterExt ".mzML" "mMass.Data"
  !insertmacro RegisterExt ".mzXML" "mMass.Data"
  !insertmacro RegisterExt ".mzData" "mMass.Data"
  !insertmacro RegisterExt ".mgf" "mMass.Data"
  SetRegView default
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'

  WriteUninstaller "$INSTDIR\Uninstall.exe"
SectionEnd

; Launch the freshly installed app from the finish page.
;
; The installer runs elevated (RequestExecutionLevel admin), so a plain Exec
; would hand that administrator token to mMass: it would write its XML config
; into the administrator's %APPDATA% instead of the user's, and Explorer would
; refuse to drag documents onto it. Handing the path to the already-running
; (unelevated) shell instead starts mMass under the user's own token. This is
; the plugin-free way of doing that -- ShellExecAsUser and the UAC plugin are
; not part of a stock NSIS install, which is all the CI runner has.
Function LaunchApp
  Exec '"$WINDIR\explorer.exe" "$INSTDIR\mMass.exe"'
FunctionEnd

Section /o "Remove user configuration (%APPDATA%\mMass)" un.RemoveUserConfig
  StrCpy $RemoveUserConfigs "1"
SectionEnd

Section "Uninstall"
  SectionIn RO

  StrCpy $0 "$APPDATA\mMass"

  Delete "$DESKTOP\mMass.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\mMass.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\Uninstall mMass.lnk"
  RMDir "$SMPROGRAMS\${APP_NAME}"

  ; Keep legacy install-local config files by moving them to user AppData.
  StrCmp $RemoveUserConfigs "1" skip_legacy_config_migrate
  CreateDirectory "$0"
  IfFileExists "$INSTDIR\gui\configs\*.json" 0 +2
  CopyFiles /SILENT "$INSTDIR\gui\configs\*.json" "$0"
  IfFileExists "$INSTDIR\gui\configs\*.xml" 0 skip_legacy_config_migrate
  CopyFiles /SILENT "$INSTDIR\gui\configs\*.xml" "$0"

skip_legacy_config_migrate:

  Delete "$INSTDIR\Uninstall.exe"
  RMDir /r "$INSTDIR"

  StrCmp $RemoveUserConfigs "1" remove_user_config_done
  Goto skip_user_config_delete

remove_user_config_done:
  Delete "$0\*.json"
  Delete "$0\*.xml"
  Delete "$0\*.migrated"
  Delete "$0\*.corrupt"
  RMDir "$0"

skip_user_config_delete:

  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
  DeleteRegKey HKLM "Software\${APP_NAME}"

  SetRegView 64
  !insertmacro UnregisterExt ".msd" "mMass.Document"
  !insertmacro UnregisterExt ".mses" "mMass.Session"
  !insertmacro UnregisterExt ".mzML" "mMass.Data"
  !insertmacro UnregisterExt ".mzXML" "mMass.Data"
  !insertmacro UnregisterExt ".mzData" "mMass.Data"
  !insertmacro UnregisterExt ".mgf" "mMass.Data"
  DeleteRegKey HKLM "Software\Classes\mMass.Document"
  DeleteRegKey HKLM "Software\Classes\mMass.Session"
  DeleteRegKey HKLM "Software\Classes\mMass.Data"
  SetRegView default
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
SectionEnd
