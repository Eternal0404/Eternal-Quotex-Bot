$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host "=== Eternal Quotex Bot Build Script ===" -ForegroundColor Cyan

# Load .env file if it exists (before checking environment variables)
$envFile = Join-Path $root ".env"
if (Test-Path $envFile) {
    Write-Host "Loading environment variables from .env file..." -ForegroundColor Green
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#")) {
            $key, $value = $line -split "=", 2
            if ($key -and $value) {
                [Environment]::SetEnvironmentVariable($key.Trim(), $value.Trim(), "Process")
                Write-Host "  Loaded: $key" -ForegroundColor Gray
            }
        }
    }
}

# Pre-build: Clean __pycache__ directories
Write-Host "Cleaning __pycache__ directories..." -ForegroundColor Yellow
Get-ChildItem -Path $root -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue | ForEach-Object {
    try {
        Remove-Item -Path $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
    } catch {}
}

# Clean .pyc files
Write-Host "Cleaning .pyc files..." -ForegroundColor Yellow
Get-ChildItem -Path $root -Recurse -Filter "*.pyc" -ErrorAction SilentlyContinue | ForEach-Object {
    try {
        Remove-Item -Path $_.FullName -Force -ErrorAction SilentlyContinue
    } catch {}
}

$dist = Join-Path $root "dist"
$build = Join-Path $root "build"
$fallbackDist = Join-Path $root "dist_rebuild"
$fallbackBuild = Join-Path $root "build_rebuild"

function Remove-DirectoryIfPossible {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return $true
    }

    try {
        Remove-Item -LiteralPath $Path -Recurse -Force
        return $true
    }
    catch {
        Write-Warning "Could not remove $Path. A fallback output folder will be used."
        return $false
    }
}

$useFallback = $false
if (-not (Remove-DirectoryIfPossible -Path $dist)) {
    $useFallback = $true
}

if (-not (Remove-DirectoryIfPossible -Path $build)) {
    $useFallback = $true
}

$distPath = if ($useFallback) { $fallbackDist } else { $dist }
$buildPath = if ($useFallback) { $fallbackBuild } else { $build }

if ($useFallback) {
    Remove-DirectoryIfPossible -Path $fallbackDist | Out-Null
    Remove-DirectoryIfPossible -Path $fallbackBuild | Out-Null
}

# Check for environment variables
$licenseApiUrl = $env:LICENSE_API_URL
$licenseToken = $env:LICENSE_SHARED_TOKEN
if (-not $licenseApiUrl) {
    Write-Warning "LICENSE_API_URL environment variable is not set. License validation will require manual configuration."
}
if (-not $licenseToken) {
    Write-Warning "LICENSE_SHARED_TOKEN environment variable is not set. Admin actions will require manual token configuration."
}

Write-Host "Starting PyInstaller build..." -ForegroundColor Green

$args = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--distpath", $distPath,
    "--workpath", $buildPath,
    "main.spec"
)

python @args

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

# Post-build verification
$exeDir = Join-Path $distPath "."
$exeFile = Get-ChildItem -Path $distPath -Filter "*.exe" | Select-Object -First 1

if (Test-Path $exeFile) {
    $fileSize = (Get-Item $exeFile).Length
    $sizeMB = [math]::Round($fileSize / 1MB, 2)
    Write-Host ""
    Write-Host "=== Build Successful ===" -ForegroundColor Green
    Write-Host "Executable: $exeFile" -ForegroundColor White
    Write-Host "Size: ${sizeMB} MB" -ForegroundColor White
    
    if ($fileSize -lt 10MB) {
        Write-Warning "Executable size is less than 10MB. This may indicate missing dependencies."
    } else {
        Write-Host "Executable size looks reasonable." -ForegroundColor Green
    }
} else {
    Write-Error "Executable not found after build: $exeFile"
    exit 1
}

# Copy .env file to dist directory if it exists
if (Test-Path $envFile) {
    $destEnv = Join-Path $exeDir ".env"
    Copy-Item -Path $envFile -Destination $destEnv -Force
    Write-Host "Copied .env file to distribution folder." -ForegroundColor Green
}

# Verify no session files included
$jsonlCount = (Get-ChildItem -Path $exeDir -Recurse -Filter "*.jsonl" -ErrorAction SilentlyContinue | Measure-Object).Count
if ($jsonlCount -gt 0) {
    Write-Warning "Found $jsonlCount session file(s) in build output. These should be excluded."
} else {
    Write-Host "No session files included in build output." -ForegroundColor Green
}

Write-Host ""
Write-Host "Build complete:" -ForegroundColor Cyan
Write-Host $exeDir -ForegroundColor White
