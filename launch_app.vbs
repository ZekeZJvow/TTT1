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
    http.open "GET", "http://127.0.0.1:5000/api/trading-days?n=1", False
    http.send
    If Err.Number = 0 Then
        If http.status = 200 Then ServerUp = True
    End If
    Err.Clear
    On Error GoTo 0
End Function

' Launch the packaged exe through run_hidden.vbs (it locates *.exe under tools\..\dist).
' This keeps both scheduled tasks on the SAME program and the SAME database,
' and avoids serving half-edited source files from source mode.
If Not ServerUp() Then
    sh.CurrentDirectory = base
    sh.Run "wscript.exe """ & base & "\tools\run_hidden.vbs""", 0, False
    For i = 1 To 90
        WScript.Sleep 1000
        If ServerUp() Then Exit For
    Next
End If

Dim browsers, b
browsers = Array( _
    "C:\Program Files\Google\Chrome\Application\chrome.exe", _
    "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe", _
    "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", _
    "C:\Program Files\Microsoft\Edge\Application\msedge.exe")

For Each b In browsers
    If fso.FileExists(b) Then
        sh.Run """" & b & """ --app=http://localhost:5000 --window-size=1500,980", 1, False
        WScript.Quit 0
    End If
Next

sh.Run "http://localhost:5000", 1, False
