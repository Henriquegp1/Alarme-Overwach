$ErrorActionPreference = "Stop"

$version = (Get-Content "version.py" -Raw).Trim() -replace '^VERSAO\s*=\s*["'']([^"'']+)["'']\s*$', '$1'
if ($version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Versao invalida em version.py: $version"
}

& ".\venv\Scripts\python.exe" -m PyInstaller --clean GameSentinel.spec
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$iscc = (Get-Command "ISCC.exe" -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    $defaultIsccPaths = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )
    $iscc = $defaultIsccPaths | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $iscc) {
    throw "Inno Setup nao encontrado. Instale-o ou adicione ISCC.exe ao PATH."
}

& $iscc "/dMyAppVersion=$version" "installer\GameSentinel.iss"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Release $version gerado em releases\"
