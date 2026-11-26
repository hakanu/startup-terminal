' Silent runner for Startup Terminal (runs with pythonw.exe, no console window)
Set objFSO = CreateObject("Scripting.FileSystemObject")
Set objShell = CreateObject("WScript.Shell")

scriptDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
mainPyPath = scriptDir & "\main.py"

userProfile = objShell.ExpandEnvironmentStrings("%LOCALAPPDATA%")
pythonw13 = userProfile & "\Programs\Python\Python313\pythonw.exe"
pythonw11 = userProfile & "\Programs\Python\Python311\pythonw.exe"

If objFSO.FileExists(pythonw13) Then
    pythonwPath = pythonw13
ElseIf objFSO.FileExists(pythonw11) Then
    pythonwPath = pythonw11
Else
    pythonwPath = "pythonw.exe"
End If

cmd = """" & pythonwPath & """ """ & mainPyPath & """ --startup"
objShell.Run cmd, 0, False
