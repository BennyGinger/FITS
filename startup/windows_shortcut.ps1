$ErrorActionPreference = 'Stop'
$root = $env:FITS_INSTALL_ROOT
if (-not $root) { throw 'FITS_INSTALL_ROOT was not provided.' }
$python = Join-Path $root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $python)) { throw "Missing FITS Python: $python" }
$shell = New-Object -ComObject WScript.Shell
$launcher = Join-Path $root 'startup\launch_win.vbs'
$wscript = Join-Path ([Environment]::GetFolderPath('System')) 'wscript.exe'
$refreshOnly = $env:FITS_REFRESH_SHORTCUTS -eq '1'
$folders = @(
    [Environment]::GetFolderPath('Programs')
    [Environment]::GetFolderPath('DesktopDirectory')
)
foreach ($folder in $folders) {
    if (-not $folder) { throw 'Windows did not provide a shortcut folder for this user.' }
    $destination = Join-Path $folder 'FITS.lnk'
    if ($refreshOnly -and -not (Test-Path -LiteralPath $destination)) { continue }
    if (Test-Path -LiteralPath $destination) {
        $existing = $shell.CreateShortcut($destination)
        if ($existing.WorkingDirectory.TrimEnd('\') -ne $root.TrimEnd('\')) {
            if ($refreshOnly) { continue }
            Write-Host "Existing FITS shortcut: $destination"
            Write-Host "Current checkout: $($existing.WorkingDirectory)"
            Write-Host "New checkout: $root"
            $answer = Read-Host 'Point this FITS shortcut to this checkout? [y/N]'
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
    $shortcut.Description = 'Fluorescent Image Tracking Software'
    $shortcut.Save()
    Write-Host "Installed $destination."
}
Write-Host 'Open FITS from the Start menu or your desktop.'
