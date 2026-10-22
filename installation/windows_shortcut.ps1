$ErrorActionPreference = 'Stop'
$root = $env:FITS_INSTALL_ROOT
if (-not $root) { throw 'FITS_INSTALL_ROOT was not provided.' }
$python = Join-Path $root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $python)) { throw "Missing FITS Python: $python" }
$shell = New-Object -ComObject WScript.Shell
$folders = @(
    [Environment]::GetFolderPath('Programs')
    [Environment]::GetFolderPath('DesktopDirectory')
)
foreach ($folder in $folders) {
    if (-not $folder) { throw 'Windows did not provide a shortcut folder for this user.' }
    $destination = Join-Path $folder 'FITS.lnk'
    if (Test-Path -LiteralPath $destination) {
        $existing = $shell.CreateShortcut($destination)
        if ($existing.TargetPath -ne $python) {
            Write-Host "Existing FITS shortcut: $destination"
            Write-Host "Current checkout: $($existing.WorkingDirectory)"
            Write-Host "New checkout: $root"
            $answer = Read-Host 'Point this FITS shortcut to this checkout? [y/N]'
            if ($answer -notmatch '^(y|yes)$') {
                Write-Host 'Existing shortcut kept. Open this checkout with launch.bat.'
                continue
            }
        }
    }
    New-Item -ItemType Directory -Path $folder -Force | Out-Null
    $shortcut = $shell.CreateShortcut($destination)
    $shortcut.TargetPath = $python
    $shortcut.Arguments = '-m fits.gui.main'
    $shortcut.WorkingDirectory = $root
    $shortcut.Description = 'Fluorescent Image Tracking Software'
    $shortcut.Save()
    Write-Host "Installed $destination."
}
Write-Host 'Open FITS from the Start menu or your desktop.'
