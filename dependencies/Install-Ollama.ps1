[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$fribRoot=[IO.Path]::GetFullPath($PSScriptRoot)
$fribTarget=Join-Path $fribRoot 'ollama'
$fribExecutable=Join-Path $fribTarget 'ollama.exe'
function Assert-FribPath([string]$Path) {
    $fribAbsolute=[IO.Path]::GetFullPath($Path)
    if (-not $fribAbsolute.StartsWith($fribRoot+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Ollama path escapes dependencies.' }
    $fribCurrent=$fribAbsolute
    while ($fribCurrent -ne $fribRoot) {
        if (Test-Path -LiteralPath $fribCurrent) {
            $fribEntry=Get-Item -LiteralPath $fribCurrent -Force
            if (($fribEntry.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $fribEntry.LinkType -eq 'HardLink') { throw 'Ollama paths must not redirect through links.' }
        }
        $fribCurrent=Split-Path -Parent $fribCurrent
    }
}
Assert-FribPath $fribTarget
if (-not (Test-Path -LiteralPath $fribExecutable -PathType Leaf)) {
    if (Test-Path -LiteralPath $fribTarget) { throw 'An incomplete Ollama folder exists. It was preserved for inspection.' }
    $fribDownloads=Join-Path $fribRoot 'downloads'
    Assert-FribPath $fribDownloads
    New-Item -ItemType Directory -Path $fribDownloads -Force | Out-Null
    $fribArchive=Join-Path $fribDownloads 'ollama-0.40.16-windows-amd64.zip'
    $fribExpected='50fcf5ad54277f2fa5d173ebfc93bcb017adbc0c9ef2314daabc96ca9e6aa64e'
    if (-not (Test-Path -LiteralPath $fribArchive -PathType Leaf)) {
        $fribPartial=$fribArchive+'.partial'
        Assert-FribPath $fribPartial
        Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/ollama/ollama/releases/download/v0.40.16/ollama-windows-amd64.zip' -OutFile $fribPartial
        if ((Get-FileHash -LiteralPath $fribPartial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $fribExpected) { throw 'Ollama download checksum mismatch.' }
        Move-Item -LiteralPath $fribPartial -Destination $fribArchive
    }
    if ((Get-FileHash -LiteralPath $fribArchive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $fribExpected) { throw 'Ollama archive checksum mismatch.' }
    $fribStage=Join-Path $fribRoot ('ollama-stage-'+[guid]::NewGuid().ToString('N'))
    Assert-FribPath $fribStage
    Expand-Archive -LiteralPath $fribArchive -DestinationPath $fribStage
    $fribSignature=Get-AuthenticodeSignature -LiteralPath (Join-Path $fribStage 'ollama.exe')
    if ($fribSignature.Status -ne 'Valid' -or $fribSignature.SignerCertificate.Subject -notmatch '(?:^|,\s*)CN=Ollama Inc\.(?:,|$)') { throw 'Ollama signature validation failed.' }
    Assert-FribPath $fribStage
    Assert-FribPath $fribTarget
    Move-Item -LiteralPath $fribStage -Destination $fribTarget
}
$fribSignature=Get-AuthenticodeSignature -LiteralPath $fribExecutable
if ($fribSignature.Status -ne 'Valid' -or $fribSignature.SignerCertificate.Subject -notmatch '(?:^|,\s*)CN=Ollama Inc\.(?:,|$)') { throw 'Installed Ollama signature validation failed.' }
Write-Output 'Private Ollama engine verified.'
