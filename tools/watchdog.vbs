' ============================================================
'  A-share Hot List - watchdog (NO console window at all)
'  Runs from a scheduled task every 10 minutes (action = wscript.exe).
'  Checks http://127.0.0.1:5000 ; if the app is not serving, silently
'  restarts it through run_hidden.vbs (window style 0 = hidden).
'  NOTE: keep this file ASCII-only (WSH reads .vbs as ANSI).
' ============================================================
Option Explicit

Dim fso, sh, Q, scriptDir, root, exe, vbs

Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")
Q = Chr(34)

scriptDir = fso.GetParentFolderName(fso.GetAbsolutePathName(WScript.ScriptFullName))
root = fso.GetParentFolderName(scriptDir)
vbs  = scriptDir & "\run_hidden.vbs"
exe  = FindExe(fso.BuildPath(root, "dist"))

If exe = "" Then WScript.Quit 0
If ServerUp() Then WScript.Quit 0

' not serving -> restart silently (wscript = no console, exe launched hidden)
sh.CurrentDirectory = fso.GetParentFolderName(exe)
sh.Run "wscript.exe " & Q & vbs & Q & " " & Q & exe & Q, 0, False
WScript.Quit 0

Function ServerUp()
    Dim http
    ServerUp = False
    On Error Resume Next
    Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
    http.setTimeouts 1500, 1500, 1500, 2500
    http.open "GET", "http://127.0.0.1:5000/api/market-score", False
    http.send
    If Err.Number = 0 Then
        If http.status = 200 Then ServerUp = True
    End If
    Err.Clear
    On Error GoTo 0
End Function

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
