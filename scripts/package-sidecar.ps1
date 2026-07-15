#Requires -Version 5.1
<#
.SYNOPSIS
  Build the Windows directory sidecar: embeddable CPython 3.12 + locked deps + app sources.

.DESCRIPTION
  Downloads the official Windows embeddable CPython (x64), enables site-packages,
  installs project dependencies from uv.lock via `uv export` + `uv pip install`,
  and copies src/, frontend/, agents/, and skills/ into sidecar/ so packaged Deep Agent
  can run:

    .\sidecar\python.exe -m uvicorn deep_agent.api.app:app --host 127.0.0.1 --port 8010

  with PYTHONPATH pointing at sidecar\src (also set by the Tauri shell).

  Re-run anytime after dependency or app source changes:

    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/package-sidecar.ps1
    # or: pnpm package:sidecar

  Output is gitignored (except sidecar/README.md). Safe to delete generated
  contents under sidecar/ and regenerate.

.PARAMETER PythonVersion
  Embeddable CPython version (3.12.x to match .python-version). Default 3.12.10.

.PARAMETER Force
  Wipe existing generated sidecar contents (except README) before rebuilding.
#>
[CmdletBinding()]
param(
    [string]$PythonVersion = "3.12.10",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$OutDir = Join-Path $RepoRoot "sidecar"
$CacheDir = Join-Path $RepoRoot ".cache\python-embed"
$EmbedName = "python-$PythonVersion-embed-amd64"
$ZipPath = Join-Path $CacheDir "$EmbedName.zip"
$EmbedUrl = "https://www.python.org/ftp/python/$PythonVersion/$EmbedName.zip"
$GetPipUrl = "https://bootstrap.pypa.io/get-pip.py"

function Write-Step([string]$Message) {
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Assert-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found on PATH: $Name"
    }
}

function Copy-Tree([string]$Src, [string]$Dest) {
    if (-not (Test-Path $Src)) {
        throw "Missing source path: $Src"
    }
    if (Test-Path $Dest) {
        Remove-Item -Recurse -Force $Dest
    }
    $parent = Split-Path $Dest -Parent
    if ($parent -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    Copy-Item -Path $Src -Destination $Dest -Recurse -Force
}

Assert-Command "uv"

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$ReadmePath = Join-Path $OutDir "README.md"

if ($Force) {
    Write-Step "Cleaning sidecar/ (preserving README.md)"
    Get-ChildItem -Path $OutDir -Force | Where-Object { $_.Name -ne "README.md" } | Remove-Item -Recurse -Force
}

if (-not (Test-Path $ReadmePath)) {
    @(
        "# Sidecar runtime (generated)"
        ""
        "This directory holds the Windows embeddable CPython runtime plus installed"
        "dependencies and a copy of src/, frontend/, agents/, skills/ for packaged"
        "Deep Agent builds."
        ""
        "Regenerate with:"
        ""
        "    pnpm package:sidecar"
        "    # or: powershell -File scripts/package-sidecar.ps1"
        ""
        "Do not commit the generated binaries or Lib/ tree -- see .gitignore."
    ) | Set-Content -Path $ReadmePath -Encoding ASCII
}

$PythonExe = Join-Path $OutDir "python.exe"
if (-not (Test-Path $PythonExe)) {
    New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
    if (-not (Test-Path $ZipPath)) {
        Write-Step "Downloading $EmbedUrl"
        $tmp = "$ZipPath.partial"
        Invoke-WebRequest -Uri $EmbedUrl -OutFile $tmp -UseBasicParsing
        Move-Item -Force $tmp $ZipPath
    } else {
        Write-Step "Using cached $ZipPath"
    }

    Write-Step "Extracting embeddable CPython into sidecar/"
    Expand-Archive -Path $ZipPath -DestinationPath $OutDir -Force
}

if (-not (Test-Path $PythonExe)) {
    throw "python.exe missing after extract; check $EmbedUrl"
}

# Enable site-packages + bundled src on sys.path
$Pth = Get-ChildItem -Path $OutDir -Filter "python*._pth" | Select-Object -First 1
if (-not $Pth) {
    throw "python*._pth not found under sidecar/"
}
Write-Step "Configuring $($Pth.Name) for site-packages + src"
$Existing = @(Get-Content -Path $Pth.FullName | ForEach-Object { $_.TrimEnd() })
$ZipLine = ($Existing | Where-Object { $_ -match '\.zip$' } | Select-Object -First 1)
if (-not $ZipLine) {
    $mm = ($PythonVersion -split '\.')[0..1] -join ''
    $ZipLine = "python$mm.zip"
}
@(
    $ZipLine
    "."
    "Lib\site-packages"
    "src"
    "import site"
) | Set-Content -Path $Pth.FullName -Encoding ASCII

$SitePackages = Join-Path $OutDir "Lib\site-packages"
New-Item -ItemType Directory -Force -Path $SitePackages | Out-Null

$GetPipPath = Join-Path $CacheDir "get-pip.py"
if (-not (Test-Path $GetPipPath)) {
    New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
    Write-Step "Downloading get-pip.py"
    Invoke-WebRequest -Uri $GetPipUrl -OutFile $GetPipPath -UseBasicParsing
}
if (-not (Test-Path (Join-Path $SitePackages "pip"))) {
    Write-Step "Bootstrapping pip into embeddable Python"
    & $PythonExe $GetPipPath --no-warn-script-location
    if ($LASTEXITCODE -ne 0) {
        throw "get-pip.py failed with exit $LASTEXITCODE"
    }
}

Write-Step "Exporting locked dependencies from uv.lock (no dev)"
$ReqPath = Join-Path $OutDir "requirements.txt"
Push-Location $RepoRoot
try {
    & uv export --frozen --no-dev --no-emit-project --no-hashes -o $ReqPath
    if ($LASTEXITCODE -ne 0) {
        throw "uv export failed with exit $LASTEXITCODE"
    }
} finally {
    Pop-Location
}

Write-Step "Installing dependencies into sidecar (uv pip)"
Push-Location $RepoRoot
try {
    & uv pip install --python $PythonExe -r $ReqPath
    if ($LASTEXITCODE -ne 0) {
        throw "uv pip install failed with exit $LASTEXITCODE"
    }
} finally {
    Pop-Location
}

Write-Step "Copying src/, frontend/, agents/, skills/ into sidecar/"
Copy-Tree (Join-Path $RepoRoot "src") (Join-Path $OutDir "src")
Copy-Tree (Join-Path $RepoRoot "frontend") (Join-Path $OutDir "frontend")
Copy-Tree (Join-Path $RepoRoot "agents") (Join-Path $OutDir "agents")
Copy-Tree (Join-Path $RepoRoot "skills") (Join-Path $OutDir "skills")

Get-ChildItem -Path $OutDir -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Step "Smoke: import deep_agent.api.app:app"
$prevPythonPath = $env:PYTHONPATH
$prevDesktop = $env:DEEPAGENT_DESKTOP
$env:PYTHONPATH = Join-Path $OutDir "src"
$env:DEEPAGENT_DESKTOP = "1"
try {
    & $PythonExe -c "from deep_agent.api.app import app; print('deep_agent.api.app:app ok')"
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged import smoke failed with exit $LASTEXITCODE"
    }
} finally {
    $env:PYTHONPATH = $prevPythonPath
    $env:DEEPAGENT_DESKTOP = $prevDesktop
}

Write-Step "Smoke: brief uvicorn /health"
$HealthPort = 18765
$prevPythonPath = $env:PYTHONPATH
$prevDesktop = $env:DEEPAGENT_DESKTOP
$env:PYTHONPATH = Join-Path $OutDir "src"
$env:DEEPAGENT_DESKTOP = "1"
$uvicorn = Start-Process -FilePath $PythonExe -ArgumentList @(
    "-m", "uvicorn", "deep_agent.api.app:app", "--host", "127.0.0.1", "--port", "$HealthPort"
) -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $env:TEMP "da-uvicorn-out.log") -RedirectStandardError (Join-Path $env:TEMP "da-uvicorn-err.log")
try {
    $ok = $false
    for ($i = 0; $i -lt 60; $i++) {
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$HealthPort/health" -UseBasicParsing -TimeoutSec 2
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300) {
                $ok = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 250
        }
    }
    if (-not $ok) {
        throw "uvicorn /health smoke failed on port $HealthPort"
    }
    Write-Host "health ok"
} finally {
    if ($uvicorn -and -not $uvicorn.HasExited) {
        Stop-Process -Id $uvicorn.Id -Force -ErrorAction SilentlyContinue
        # Also kill children if any
        Get-CimInstance Win32_Process -Filter "ParentProcessId=$($uvicorn.Id)" -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    }
    $env:PYTHONPATH = $prevPythonPath
    $env:DEEPAGENT_DESKTOP = $prevDesktop
}

Write-Host ""
Write-Host "Sidecar ready at $OutDir" -ForegroundColor Green
Write-Host "  python:  $PythonExe"
$srcPath = Join-Path $OutDir "src"
Write-Host "  run:     `$env:PYTHONPATH='$srcPath'; & '$PythonExe' -m uvicorn deep_agent.api.app:app --host 127.0.0.1 --port 8010"
Write-Host "Next:      pnpm exec tauri build --bundles nsis"
