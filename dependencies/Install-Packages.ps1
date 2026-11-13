[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$dependencyRoot = $PSScriptRoot
$projectRoot = Join-Path (Split-Path -Parent $dependencyRoot) 'FRIB_Final_Project\FRIB_Decision_Support'
$basePython = Join-Path $dependencyRoot 'python\python.exe'
$environmentRoot = Join-Path $dependencyRoot 'venv'
$environmentPython = Join-Path $environmentRoot 'Scripts\python.exe'
foreach ($directory in @('logs', 'cache\pip', 'temp')) {
    New-Item -ItemType Directory -Path (Join-Path $dependencyRoot $directory) -Force | Out-Null
}
$env:PIP_CACHE_DIR = Join-Path $dependencyRoot 'cache\pip'
$env:TEMP = Join-Path $dependencyRoot 'temp'
$env:TMP = $env:TEMP
$env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
Push-Location -LiteralPath $projectRoot
try {
if (-not (Test-Path -LiteralPath $environmentPython -PathType Leaf)) {
    & ('\\?\' + $basePython) -m venv --without-pip $environmentRoot
    if ($LASTEXITCODE) { throw "Virtual environment creation failed ($LASTEXITCODE)." }
}
& ('\\?\' + $environmentPython) -m ensurepip --upgrade --default-pip
if ($LASTEXITCODE) { throw "pip preparation failed ($LASTEXITCODE)." }
& ('\\?\' + $environmentPython) -m pip install --upgrade 'pip>=26.1.2' 'setuptools>=68' wheel
if ($LASTEXITCODE) { throw "Build tools installation failed ($LASTEXITCODE)." }
& ('\\?\' + $environmentPython) -m pip install -e ($projectRoot + '[ui]')
if ($LASTEXITCODE) { throw "Application dependency installation failed ($LASTEXITCODE)." }
& ('\\?\' + $environmentPython) -m pip check
if ($LASTEXITCODE) { throw "Installed packages failed consistency checks ($LASTEXITCODE)." }
& ('\\?\' + $environmentPython) -m pip list --format=json | Set-Content -LiteralPath (Join-Path $dependencyRoot 'installed-packages.json') -Encoding utf8
Write-Output 'Project packages are installed in dependencies\venv.'
} finally {
    Pop-Location
}
