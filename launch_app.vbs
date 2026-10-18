Option Explicit
Dim fso, sh, base, i

Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")

base = fso.GetParentFolderName(WScript.ScriptFullName)

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

' Silent start only: no browser window is opened.
If Not ServerUp() Then
    sh.CurrentDirectory = base
    sh.Run "wscript.exe """ & base & "\tools\run_hidden.vbs""", 0, False
    For i = 1 To 90
        WScript.Sleep 1000
        If ServerUp() Then Exit For
    Next
End If
WScript.Quit 0
