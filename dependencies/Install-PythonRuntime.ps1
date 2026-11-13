[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$fribDependencyRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$fribRuntimeRoot = Join-Path $fribDependencyRoot 'python'
$fribDownloads = Join-Path $fribDependencyRoot 'downloads'
$fribArchive = Join-Path $fribDownloads 'python-3.13.16-amd64.zip'
$fribSource = 'https://www.python.org/ftp/python/3.13.16/python-3.13.16-amd64.zip'
$fribExpectedHash = 'bbf675bb5e763c1efbb09a3a461b259d81598a63c30c4b0d7ea11b9f063df159'
$fribExecutable = Join-Path $fribRuntimeRoot 'python.exe'
function Assert-DependencyPath([string]$Path) {
    $fribAbsolute = [System.IO.Path]::GetFullPath($Path)
    if (-not $fribAbsolute.StartsWith($fribDependencyRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Python installation target must stay inside the dependencies folder.'
    }
    $fribCurrent = $fribAbsolute
    while ($fribCurrent -ne $fribDependencyRoot) {
        if (Test-Path -LiteralPath $fribCurrent) {
            $fribEntry = Get-Item -LiteralPath $fribCurrent -Force
            if (($fribEntry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -or $fribEntry.LinkType -eq 'HardLink') {
                throw 'Python dependency paths must not redirect through a link.'
            }
        }
        $fribCurrent = Split-Path -Parent $fribCurrent
    }
}
Assert-DependencyPath $fribArchive
Assert-DependencyPath $fribRuntimeRoot
New-Item -ItemType Directory -Path $fribDownloads -Force | Out-Null
if (-not (Test-Path -LiteralPath $fribArchive -PathType Leaf)) {
    $fribPartial = $fribArchive + '.partial'
    Assert-DependencyPath $fribPartial
    Write-Output 'Downloading the official Python 3.13.16 x64 runtime.'
    Invoke-WebRequest -UseBasicParsing -Uri $fribSource -OutFile $fribPartial
    if ((Get-FileHash -LiteralPath $fribPartial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $fribExpectedHash) {
        throw 'The Python archive did not match the project-pinned SHA-256; it will not be executed.'
    }
    Move-Item -LiteralPath $fribPartial -Destination $fribArchive
}
$fribObservedHash = (Get-FileHash -LiteralPath $fribArchive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($fribObservedHash -ne $fribExpectedHash) { throw 'Existing Python archive checksum mismatch; retained without execution.' }
if (-not (Test-Path -LiteralPath $fribExecutable -PathType Leaf)) {
    if (Test-Path -LiteralPath $fribRuntimeRoot) { throw 'Existing Python folder is incomplete; preserved for inspection.' }
    $fribStage = Join-Path $fribDependencyRoot ('python-stage-' + [guid]::NewGuid().ToString('N'))
    Assert-DependencyPath $fribStage
    New-Item -ItemType Directory -Path $fribStage | Out-Null
    & (Join-Path $env:SystemRoot 'System32\tar.exe') -xf $fribArchive -C $fribStage
    if ($LASTEXITCODE -ne 0) { throw 'The verified Python archive could not be extracted.' }
    $fribStageExecutable = Join-Path $fribStage 'python.exe'
    $fribSignature = Get-AuthenticodeSignature -LiteralPath $fribStageExecutable
    if ($fribSignature.Status -ne 'Valid' -or $fribSignature.SignerCertificate.Subject -notmatch '(?:^|,\s*)CN=Python Software Foundation(?:,|$)') {
        throw 'The extracted runtime did not have a valid Python Software Foundation signature.'
    }
    Assert-DependencyPath $fribRuntimeRoot
    Move-Item -LiteralPath $fribStage -Destination $fribRuntimeRoot
}
$fribSignature = Get-AuthenticodeSignature -LiteralPath $fribExecutable
if ($fribSignature.Status -ne 'Valid' -or $fribSignature.SignerCertificate.Subject -notmatch '(?:^|,\s*)CN=Python Software Foundation(?:,|$)') { throw 'Installed Python signature check failed.' }
$fribProbe = & $fribExecutable -c 'import sys,struct,ssl,venv,ensurepip,json; assert sys.version_info[:3] == (3,13,16); assert struct.calcsize("P") == 8; print(json.dumps({"version":sys.version.split()[0],"bits":struct.calcsize("P")*8,"executable":sys.executable,"ssl":ssl.OPENSSL_VERSION,"ensurepip":ensurepip.version()}))'
if ($LASTEXITCODE -ne 0) { throw 'Installed Python capability check failed.' }
$fribCapabilities = $fribProbe | ConvertFrom-Json
$fribReceipt = [ordered]@{
    component = 'private-python'; installed_at_utc = [DateTime]::UtcNow.ToString('o'); source = $fribSource
    archive = $fribArchive; sha256 = $fribObservedHash; executable = $fribExecutable
    authenticode_status = $fribSignature.Status.ToString(); signer = $fribSignature.SignerCertificate.Subject
    capabilities = $fribCapabilities; system_path_changed = $false; system_registration_changed = $false
}
$fribReceipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $fribDependencyRoot 'python-installation.json') -Encoding utf8
$fribReceipt | ConvertTo-Json -Depth 6
