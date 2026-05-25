; NSIS installer for mMass Windows release bundle.

Unicode true
RequestExecutionLevel admin

!include "MUI2.nsh"

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

Name "${APP_NAME} ${APP_VERSION}"
OutFile "${OUTPUT_NAME}"
InstallDir "$PROGRAMFILES64\\${APP_NAME}"
InstallDirRegKey HKLM "Software\\${APP_NAME}" "InstallDir"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_COMPONENTS
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

!insertmacro MUI_LANGUAGE "English"

Var RemoveUserConfigs

Section "Install"
  InitPluginsDir
  CreateDirectory "$PLUGINSDIR\\mmass_user_configs"

  ; Preserve user-customized XML files across reinstalls/upgrades.
  IfFileExists "$INSTDIR\\gui\\configs\\*.xml" 0 +2
  CopyFiles /SILENT "$INSTDIR\\gui\\configs\\*.xml" "$PLUGINSDIR\\mmass_user_configs"

  SetOutPath "$INSTDIR"
  File /r "${SOURCE_DIR}\\*.*"

  ; Restore preserved XML files so installer defaults do not overwrite user edits.
  IfFileExists "$PLUGINSDIR\\mmass_user_configs\\*.xml" 0 +2
  CopyFiles /SILENT "$PLUGINSDIR\\mmass_user_configs\\*.xml" "$INSTDIR\\gui\\configs"

  WriteRegStr HKLM "Software\\${APP_NAME}" "InstallDir" "$INSTDIR"

  WriteRegStr HKLM "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\${APP_NAME}" "DisplayName" "${APP_NAME} ${APP_VERSION}"
  WriteRegStr HKLM "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\${APP_NAME}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKLM "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\${APP_NAME}" "Publisher" "${COMPANY_NAME}"
  WriteRegStr HKLM "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\${APP_NAME}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\${APP_NAME}" "UninstallString" '"$INSTDIR\\Uninstall.exe"'
  WriteRegDWORD HKLM "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\${APP_NAME}" "NoModify" 1
  WriteRegDWORD HKLM "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\${APP_NAME}" "NoRepair" 1

  CreateDirectory "$SMPROGRAMS\\${APP_NAME}"
  CreateShortcut "$SMPROGRAMS\\${APP_NAME}\\mMass.lnk" "$INSTDIR\\mMass.exe"
  CreateShortcut "$SMPROGRAMS\\${APP_NAME}\\Uninstall mMass.lnk" "$INSTDIR\\Uninstall.exe"
  CreateShortcut "$DESKTOP\\mMass.lnk" "$INSTDIR\\mMass.exe"

  WriteUninstaller "$INSTDIR\\Uninstall.exe"
SectionEnd

Section /o "Remove user XML configuration (%APPDATA%\\mMass\\*.xml)" un.RemoveUserConfig
  StrCpy $RemoveUserConfigs "1"
SectionEnd

Section "Uninstall"
  SectionIn RO

  StrCpy $0 "$APPDATA\\mMass"

  Delete "$DESKTOP\\mMass.lnk"
  Delete "$SMPROGRAMS\\${APP_NAME}\\mMass.lnk"
  Delete "$SMPROGRAMS\\${APP_NAME}\\Uninstall mMass.lnk"
  RMDir "$SMPROGRAMS\\${APP_NAME}"

  ; Keep legacy install-local XML files by moving them to user AppData.
  StrCmp $RemoveUserConfigs "1" skip_legacy_config_migrate
  CreateDirectory "$0"
  IfFileExists "$INSTDIR\\gui\\configs\\*.xml" 0 skip_legacy_config_migrate
  CopyFiles /SILENT "$INSTDIR\\gui\\configs\\*.xml" "$0"

skip_legacy_config_migrate:

  Delete "$INSTDIR\\Uninstall.exe"
  RMDir /r "$INSTDIR"

  StrCmp $RemoveUserConfigs "1" remove_user_config_done
  Goto skip_user_config_delete

remove_user_config_done:
  Delete "$0\\*.xml"
  RMDir "$0"

skip_user_config_delete:

  DeleteRegKey HKLM "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\${APP_NAME}"
  DeleteRegKey HKLM "Software\\${APP_NAME}"
SectionEnd