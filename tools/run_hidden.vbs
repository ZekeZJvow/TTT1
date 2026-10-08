' ============================================================
'  A-share Hot List  -  hidden launcher (no console window)
'  Usage:  wscript.exe run_hidden.vbs ["<path-to-exe>"]
' ============================================================
Option Explicit

Dim fso, sh, exe, base, workDir, Q

Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")
Q = Chr(34)

base = fso.GetParentFolderName(WScript.ScriptFullName)

If WScript.Arguments.Count > 0 Then
    exe = WScript.Arguments(0)
Else
    exe = FindExe(base)
End If
If exe = "" Then exe = FindExe(fso.BuildPath(base, "..\dist"))
If exe = "" Then exe = FindExe(fso.BuildPath(base, "dist"))
If exe = "" Then WScript.Quit 2
If Not fso.FileExists(exe) Then WScript.Quit 2

workDir = fso.GetParentFolderName(exe)
sh.CurrentDirectory = workDir

' window style 0 = hidden; False = do not wait
sh.Run Q & exe & Q & " --no-browser", 0, False
WScript.Quit 0

Function FindExe(dir)
    Dim folder, file
    FindExe = ""
    If Not fso.FolderExists(dir) Then Exit Function
    Set folder = fso.GetFolder(dir)
    For Each file In folder.Files
        If LCase(fso.GetExtensionName(file.Name)) = "exe" Then
            FindExe = file.Path
            Exit Function
        End If
    Next
End Function
