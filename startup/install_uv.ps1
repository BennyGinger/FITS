# Bootstrap uv as an independent user tool; never update an existing installation.
$ErrorActionPreference = 'Stop'
$installer = Join-Path ([IO.Path]::GetTempPath()) ('fits-uv-' + [Guid]::NewGuid() + '.ps1')
try {
    Write-Host 'Downloading uv from its official installer...'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri 'https://astral.sh/uv/install.ps1' -OutFile $installer
    $env:UV_INSTALL_DIR = Join-Path $env:USERPROFILE '.local\bin'
    $env:UV_NO_MODIFY_PATH = '1'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer
    if ($LASTEXITCODE -ne 0) {
        throw "Official uv installer exited with code $LASTEXITCODE."
    }
    if (-not (Test-Path (Join-Path $env:UV_INSTALL_DIR 'uv.exe'))) {
        throw 'uv installation did not produce an executable.'
    }
} catch {
    Write-Error "uv installation failed: $_" -ErrorAction Continue
    exit 1
} finally {
    Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
}
