Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

shell.CurrentDirectory = fso.GetParentFolderName(WScript.ScriptFullName)
shell.Run Chr(34) & fso.BuildPath(shell.CurrentDirectory, ".venv\Scripts\pythonw.exe") & Chr(34) & " -m fits.gui.main", 0, False
