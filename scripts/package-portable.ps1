#Requires -Version 5.1
<#
.SYNOPSIS
  Zip a portable Deep Agent release (exe + resources). Tauri v2 has no portable target.

.DESCRIPTION
  After `pnpm tauri build`, copies the release executable and its resource tree
  into src-tauri/target/release/bundle/portable/ and writes a zip next to the
  NSIS installer.

  Usage:
    pnpm package:portable
    # or: powershell -File scripts/package-portable.ps1
#>
[CmdletBinding()]
param(
    [string]$ReleaseDir = "",
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
if (-not $ReleaseDir) {
    $ReleaseDir = Join-Path $RepoRoot "src-tauri\target\release"
}
$ReleaseDir = Resolve-Path $ReleaseDir

if (-not $Version) {
    $Version = ($env:APP_VERSION -as [string]).Trim()
}
if (-not $Version) {
    $confPath = Join-Path $RepoRoot "src-tauri\tauri.conf.json"
    if (Test-Path $confPath) {
        $conf = Get-Content -Raw -Path $confPath | ConvertFrom-Json
        $Version = [string]$conf.version
    }
}
if (-not $Version) {
    throw "Version not set. Pass -Version, set APP_VERSION, or set version in src-tauri/tauri.conf.json."
}

$ExeCandidates = @(
    (Join-Path $ReleaseDir "Deep Agent.exe"),
    (Join-Path $ReleaseDir "deep-agent.exe")
)
$Exe = $ExeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Exe) {
    throw "Release exe not found under $ReleaseDir. Run pnpm tauri build first."
}

$PortableRoot = Join-Path $ReleaseDir "bundle\portable"
$StageDir = Join-Path $PortableRoot "Deep Agent"
$ZipPath = Join-Path $PortableRoot "Deep-Agent-$Version-windows-x64-portable.zip"

if (Test-Path $PortableRoot) {
    Remove-Item -Recurse -Force $PortableRoot
}
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null

Write-Host "==> Staging portable payload from $ReleaseDir" -ForegroundColor Cyan
Copy-Item -Path $Exe -Destination (Join-Path $StageDir (Split-Path $Exe -Leaf)) -Force

foreach ($name in @("resources", "sidecar")) {
    $src = Join-Path $ReleaseDir $name
    if (Test-Path $src) {
        Write-Host "    copying $name/"
        Copy-Item -Path $src -Destination (Join-Path $StageDir $name) -Recurse -Force
    }
}

Get-ChildItem -Path $ReleaseDir -File | Where-Object { $_.Extension -eq ".dll" } | ForEach-Object {
    Copy-Item -Path $_.FullName -Destination (Join-Path $StageDir $_.Name) -Force
}

$ResSidecar = Join-Path $StageDir "resources\sidecar\python.exe"
$FlatSidecar = Join-Path $StageDir "sidecar\python.exe"
if (-not (Test-Path $ResSidecar) -and -not (Test-Path $FlatSidecar)) {
    Write-Warning "Packaged sidecar python.exe not found in stage. Did you run package-sidecar and rebuild?"
}

if (Test-Path $ZipPath) {
    Remove-Item -Force $ZipPath
}
Write-Host "==> Writing $ZipPath" -ForegroundColor Cyan
Compress-Archive -Path $StageDir -DestinationPath $ZipPath -Force

Write-Host ""
Write-Host "Portable zip: $ZipPath" -ForegroundColor Green
Write-Host "Staged dir:   $StageDir"
