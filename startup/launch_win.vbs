Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

shell.CurrentDirectory = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
receipt = fso.BuildPath(shell.CurrentDirectory, "startup\logs\bootstrap-python.txt")
If Not fso.FileExists(receipt) Then
    MsgBox "Run install_win.bat once to prepare the independent FITS launcher.", vbExclamation, "FITS"
    WScript.Quit 1
End If
Set file = fso.OpenTextFile(receipt, 1, False, -1)
python = Trim(file.ReadAll)
file.Close
If Not fso.FileExists(python) Then
    MsgBox "Managed Python could not be found. Run install_win.bat again.", vbExclamation, "FITS"
    WScript.Quit 1
End If
pythonw = fso.BuildPath(fso.GetParentFolderName(python), "pythonw.exe")
If fso.FileExists(pythonw) Then python = pythonw
shell.Run Chr(34) & python & Chr(34) & " " & Chr(34) & fso.BuildPath(shell.CurrentDirectory, "startup\launcher.py") & Chr(34), 0, False
