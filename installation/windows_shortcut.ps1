$ErrorActionPreference = 'Stop'
$root = $env:FITS_INSTALL_ROOT
if (-not $root) { throw 'FITS_INSTALL_ROOT was not provided.' }
$python = Join-Path $root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $python)) { throw "Missing FITS Python: $python" }
$shell = New-Object -ComObject WScript.Shell
$destination = Join-Path ([Environment]::GetFolderPath('Programs')) 'FITS.lnk'
if (Test-Path -LiteralPath $destination) {
    $existing = $shell.CreateShortcut($destination)
    if ($existing.TargetPath -ne $python) {
        Write-Host "Existing FITS shortcut: $($existing.WorkingDirectory)"
        Write-Host "New checkout: $root"
        $answer = Read-Host 'Point the FITS shortcut to this checkout? [y/N]'
        if ($answer -notmatch '^(y|yes)$') {
            Write-Host 'Existing shortcut kept. Open this checkout with launch.bat.'
            exit 0
        }
    }
}
$shortcut = $shell.CreateShortcut($destination)
$shortcut.TargetPath = $python
$shortcut.Arguments = '-m fits.gui.main'
$shortcut.WorkingDirectory = $root
$shortcut.Description = 'Fluorescent Image Tracking Software'
$shortcut.Save()
Write-Host "Installed $destination. Search for FITS in the Start menu."
