Option Explicit

Dim shell
Dim fso
Dim appDir
Dim batPath
Dim dataDir
Dim logDir
Dim logPath
Dim command
Dim exitCode

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

appDir = fso.GetParentFolderName(WScript.ScriptFullName)
batPath = fso.BuildPath(appDir, "run_jang.bat")
dataDir = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%")
If dataDir = "%LOCALAPPDATA%" Or Len(dataDir) = 0 Then
    dataDir = appDir
Else
    dataDir = fso.BuildPath(dataDir, "JJZero Audio")
End If
If Not fso.FolderExists(dataDir) Then
    fso.CreateFolder(dataDir)
End If
logDir = fso.BuildPath(dataDir, "logs")
logPath = fso.BuildPath(logDir, "launcher.log")

If Not fso.FolderExists(logDir) Then
    fso.CreateFolder(logDir)
End If

shell.CurrentDirectory = appDir
command = "cmd.exe /d /s /c " & Quote(Quote(batPath) & " --no-pause > " & Quote(logPath) & " 2>&1")
exitCode = shell.Run(command, 0, True)

If exitCode <> 0 Then
    MsgBox "JJZero Audio failed to start." & vbCrLf & vbCrLf & "Log file:" & vbCrLf & logPath, vbExclamation, "JJZero Audio"
End If

Function Quote(value)
    Quote = Chr(34) & value & Chr(34)
End Function
