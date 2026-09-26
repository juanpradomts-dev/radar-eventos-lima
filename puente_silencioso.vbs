' Corre PUENTE_EVENTBRITE.bat sin ventana (lo llama la tarea programada).
Set sh = CreateObject("WScript.Shell")
d = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.Run "cmd /c """ & d & "\PUENTE_EVENTBRITE.bat"" > """ & d & "\puente.log"" 2>&1", 0, False
