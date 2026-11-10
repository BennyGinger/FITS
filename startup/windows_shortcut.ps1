$ErrorActionPreference = 'Stop'
$root = $env:FISCH_INSTALL_ROOT
if (-not $root) { throw 'FISCH_INSTALL_ROOT was not provided.' }
$python = Join-Path $root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $python)) { throw "Missing FIScH Python: $python" }
$icon = Join-Path $root 'assets\fisch_icon.ico'
if (-not (Test-Path -LiteralPath $icon)) { throw "Missing FIScH icon: $icon" }
$shell = New-Object -ComObject WScript.Shell
$launcher = Join-Path $root 'startup\launch_win.vbs'
$wscript = Join-Path ([Environment]::GetFolderPath('System')) 'wscript.exe'
$refreshOnly = $env:FISCH_REFRESH_SHORTCUTS -eq '1'
$folders = @(
    [Environment]::GetFolderPath('Programs')
    [Environment]::GetFolderPath('DesktopDirectory')
)
foreach ($folder in $folders) {
    if (-not $folder) { throw 'Windows did not provide a shortcut folder for this user.' }
    $destination = Join-Path $folder 'FIScH.lnk'
    if ($refreshOnly -and -not (Test-Path -LiteralPath $destination)) { continue }
    if (Test-Path -LiteralPath $destination) {
        $existing = $shell.CreateShortcut($destination)
        if ($existing.WorkingDirectory.TrimEnd('\') -ne $root.TrimEnd('\')) {
            if ($refreshOnly) { continue }
            Write-Host "Existing FIScH shortcut: $destination"
            Write-Host "Current checkout: $($existing.WorkingDirectory)"
            Write-Host "New checkout: $root"
            $answer = Read-Host 'Point this FIScH shortcut to this checkout? [y/N]'
            if ($answer -notmatch '^(y|yes)$') {
                Write-Host 'Existing shortcut kept. Open this checkout with startup\launch_win.bat.'
                continue
            }
        }
    }
    New-Item -ItemType Directory -Path $folder -Force | Out-Null
    $shortcut = $shell.CreateShortcut($destination)
    $shortcut.TargetPath = $wscript
    $shortcut.Arguments = '"' + $launcher + '"'
    $shortcut.WorkingDirectory = $root
    $shortcut.Description = 'Fluorescent Imaging and Single-cell Histories'
    $shortcut.IconLocation = "$icon,0"
    $shortcut.Save()
    Write-Host "Installed $destination."
}
Write-Host 'Open FIScH from the Start menu or your desktop.'
