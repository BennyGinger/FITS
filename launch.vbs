Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

shell.CurrentDirectory = fso.GetParentFolderName(WScript.ScriptFullName)
shell.Run "uv run fits-gui", 0, False