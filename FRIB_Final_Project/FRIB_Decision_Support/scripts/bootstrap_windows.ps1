# Official full managed Python ZIP: private extraction, no machine registration.
[CmdletBinding()]
param(
    [switch]$ForcePrivatePython,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$LauncherArguments
)
# A parent PowerShell 7 session can supply incompatible module directories to
# Windows PowerShell 5. Use only this host's trusted built-in modules.
$env:PSModulePath = $PSHOME + '\Modules'
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeVersion = '3.13.16'
$runtimeRoot = Join-Path $projectRoot '.frib'
$privateRoot = Join-Path $runtimeRoot "python\$runtimeVersion"
$privatePython = Join-Path $privateRoot 'python.exe'
$bootstrapLock = $null

function Assert-ManagedPath([string]$Path) {
    $absolute = [System.IO.Path]::GetFullPath($Path)
    $root = [System.IO.Path]::GetFullPath($runtimeRoot)
    if ($absolute -ne $root -and -not $absolute.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Private runtime path escapes the project runtime folder.' }
    $current = $absolute
    while ($true) {
        if (Test-Path -LiteralPath $current) {
            $entry = Get-Item -LiteralPath $current -Force
            if (($entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -or $entry.LinkType -eq 'HardLink') { throw "Refusing a redirected private runtime path: $current" }
        }
        if ($current -eq $root) { break }
        $current = Split-Path -Parent $current
    }
}

function Test-UsablePython([string]$Executable, [string[]]$PrefixArguments = @(), [string]$ExpectedVersion = '') {
    if (-not $Executable -or $Executable -match '\\WindowsApps\\') { return $false }
    try {
        $startInfo = New-Object System.Diagnostics.ProcessStartInfo
        $startInfo.FileName = $Executable
        $versionCondition = '(3,11) <= sys.version_info[:2] < (3,14)'
        if ($ExpectedVersion) { $versionCondition = "sys.version_info[:3] == ($($ExpectedVersion.Replace('.', ',')))" }
        $startInfo.Arguments = (($PrefixArguments -join ' ') + ' -c "import sys,struct,ssl,venv; raise SystemExit(0 if ' + $versionCondition + ' and struct.calcsize(''P'') == 8 else 1)"').Trim()
        $startInfo.UseShellExecute = $false
        $startInfo.CreateNoWindow = $true
        $startInfo.RedirectStandardOutput = $true
        $startInfo.RedirectStandardError = $true
        $probe = New-Object System.Diagnostics.Process
        $probe.StartInfo = $startInfo
        [void]$probe.Start()
        if (-not $probe.WaitForExit(10000)) { $probe.Kill(); return $false }
        return $probe.ExitCode -eq 0
    } catch { return $false }
}

function Assert-Archive([string]$Path, [string]$ExpectedHash) {
    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::OpenRead($Path)
    try { $observed = [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $stream.Dispose(); $algorithm.Dispose() }
    if ($observed -ne $ExpectedHash) {
        throw 'Python download SHA256 verification failed. Unverified runtime files will not run; retry the download.'
    }
}

function Assert-PrivateRuntime([string]$Executable) {
    Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1') -ErrorAction Stop
    $signature = Microsoft.PowerShell.Security\Get-AuthenticodeSignature -LiteralPath $Executable
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch '(?:^|,\s*)CN=Python Software Foundation(?:,|$)') {
        throw 'Private Python signature verification failed. A valid Python Software Foundation signature is required.'
    }
    if (-not (Test-UsablePython $Executable @() $runtimeVersion)) { throw "The private Python runtime must be exactly $runtimeVersion, 64-bit, with working ssl and venv modules." }
}

try {
    Assert-ManagedPath $runtimeRoot
    [void](New-Item -ItemType Directory -Path $runtimeRoot -Force)
    $bootstrapLockPath = Join-Path $runtimeRoot 'bootstrap.lock'
    Assert-ManagedPath $bootstrapLockPath
    try { $bootstrapLock = [System.IO.File]::Open($bootstrapLockPath, 'OpenOrCreate', 'ReadWrite', 'None') }
    catch { throw 'Another FRIB bootstrap is already running. Wait for that setup window to finish, then retry.' }
    $selectedPython = $null
    $selectedPrefix = @()
    $forcePrivate = $ForcePrivatePython -or $env:FRIB_BOOTSTRAP_PYTHON -eq 'private'
    $pendingPath = Join-Path $runtimeRoot 'pending-upgrade.json'
    Assert-ManagedPath $pendingPath
    if (Test-Path -LiteralPath $pendingPath -PathType Leaf) {
        $pending = Get-Content -LiteralPath $pendingPath -Raw | ConvertFrom-Json
        if ($pending.upgrade_python -eq $true) {
            if ($pending.schema_version -ne '1.0' -or $pending.python_runtime -ne $runtimeVersion -or $pending.status -ne 'queued' -or $pending.apply_on -ne 'next_start') {
                throw 'The queued Python upgrade is invalid. Only the fixed, verified runtime is supported.'
            }
            $serviceLock = Join-Path $runtimeRoot 'services.lock'
            Assert-ManagedPath $serviceLock
            if (Test-Path -LiteralPath $serviceLock) {
                try {
                    $guard = [System.IO.File]::Open($serviceLock, 'Open', 'ReadWrite', 'None')
                    $guard.Dispose()
                } catch { throw 'Stop FRIB with Ctrl+C in its running window, then double-click Start FRIB.cmd to apply the queued upgrade.' }
            }
            $forcePrivate = $true
        }
    }
    if (-not $forcePrivate) {
        Assert-ManagedPath $privatePython
        $candidates = @()
        $pointerPath = Join-Path $runtimeRoot 'active-environment.json'
        Assert-ManagedPath $pointerPath
        if (Test-Path -LiteralPath $pointerPath -PathType Leaf) {
            $pointer = Get-Content -LiteralPath $pointerPath -Raw | ConvertFrom-Json
            if ($pointer.schema_version -ne '1.0' -or $pointer.path -cnotmatch '^environments/ENV-[a-f0-9]{32}$') { throw 'The active private environment pointer is invalid.' }
            $activePython = Join-Path (Join-Path $runtimeRoot $pointer.path) 'Scripts\python.exe'
            Assert-ManagedPath $activePython
            $candidates += $activePython
        }
        $candidates += @((Join-Path $projectRoot '.venv\Scripts\python.exe'), $privatePython)
        foreach ($candidate in $candidates) {
            if ((Test-Path -LiteralPath $candidate -PathType Leaf) -and (Test-UsablePython $candidate)) {
                if ($candidate -eq $privatePython) { Assert-PrivateRuntime $candidate }
                $selectedPython = $candidate; break
            }
        }
        if (-not $selectedPython) {
            $command = Get-Command py.exe -ErrorAction SilentlyContinue
            if ($command -and (Test-UsablePython $command.Source @('-3.13'))) { $selectedPython = $command.Source; $selectedPrefix = @('-3.13') }
        }
        if (-not $selectedPython) {
            $command = Get-Command python.exe -ErrorAction SilentlyContinue
            if ($command -and (Test-UsablePython $command.Source)) { $selectedPython = $command.Source }
        }
    } elseif (Test-Path -LiteralPath $privatePython -PathType Leaf) {
        Assert-ManagedPath $privatePython
        Assert-PrivateRuntime $privatePython
        $selectedPython = $privatePython
    }
    if (-not $selectedPython) {
        $architecture = $env:PROCESSOR_ARCHITEW6432
        if (-not $architecture) { $architecture = $env:PROCESSOR_ARCHITECTURE }
        switch ($architecture.ToUpperInvariant()) {
            'AMD64' { $archiveName = "python-$runtimeVersion-amd64.zip"; $expectedHash = 'bbf675bb5e763c1efbb09a3a461b259d81598a63c30c4b0d7ea11b9f063df159' }
            'ARM64' { $archiveName = "python-$runtimeVersion-arm64.zip"; $expectedHash = '49b24a002efcf7451fe47a52ad9bc57a012a0c987eb6a635973ede200c421044' }
            default { throw "Automatic setup requires 64-bit Windows x64 or ARM64. Detected: $architecture" }
        }
        $downloadRoot = Join-Path $runtimeRoot 'downloads'
        Assert-ManagedPath $downloadRoot
        [void](New-Item -ItemType Directory -Path $downloadRoot -Force)
        $archivePath = Join-Path $downloadRoot $archiveName
        Assert-ManagedPath $archivePath
        if (Test-Path -LiteralPath $archivePath -PathType Leaf) {
            try { Assert-Archive $archivePath $expectedHash }
            catch { Remove-Item -LiteralPath $archivePath -Force }
        }
        if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
            Write-Host "Downloading official Python $runtimeVersion for $architecture..."
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            $partial = "$archivePath.partial"
            Assert-ManagedPath $partial
            Invoke-WebRequest -UseBasicParsing -Uri "https://www.python.org/ftp/python/$runtimeVersion/$archiveName" -OutFile $partial
            Assert-Archive $partial $expectedHash
            Move-Item -LiteralPath $partial -Destination $archivePath -Force
        }
        Assert-Archive $archivePath $expectedHash
        Write-Host 'Preparing the private Python runtime. Administrator access is not needed...'
        $stagingRoot = Join-Path $runtimeRoot ('python\stage-' + [guid]::NewGuid().ToString('N'))
        Assert-ManagedPath $stagingRoot
        Assert-ManagedPath $privateRoot
        [void](New-Item -ItemType Directory -Path $stagingRoot -Force)
        # Windows' native bsdtar handles deep project paths without requiring a
        # machine-wide LongPathsEnabled registry change. Never use PATH lookup.
        $trustedTar = Join-Path $env:SystemRoot 'System32\tar.exe'
        if (Test-Path -LiteralPath $trustedTar -PathType Leaf) {
            & $trustedTar -xf $archivePath -C $stagingRoot
            if ($LASTEXITCODE -ne 0) { throw "Python archive extraction failed (exit $LASTEXITCODE)." }
        } else {
            if ($stagingRoot.Length -gt 120) { throw 'This Windows version lacks tar.exe for long paths. Move the project to a shorter folder, such as C:\FRIB, then retry.' }
            Add-Type -AssemblyName System.IO.Compression.FileSystem
            [System.IO.Compression.ZipFile]::ExtractToDirectory($archivePath, $stagingRoot)
        }
        Assert-PrivateRuntime (Join-Path $stagingRoot 'python.exe')
        if (Test-Path -LiteralPath $privateRoot) { throw 'A private runtime folder already exists but is incomplete. It was retained; inspect .frib/python before retrying.' }
        Move-Item -LiteralPath $stagingRoot -Destination $privateRoot
        $selectedPython = $privatePython
    }
    $bootstrapLock.Dispose()
    $bootstrapLock = $null
    Set-Location -LiteralPath $projectRoot
    # Child Python then retains extended paths throughout venv/ensurepip/pip.
    if (-not $selectedPython.StartsWith('\\?\')) {
        if ($selectedPython.StartsWith('\\')) { $selectedPython = '\\?\UNC\' + $selectedPython.Substring(2) }
        else { $selectedPython = '\\?\' + $selectedPython }
    }
    & $selectedPython @selectedPrefix (Join-Path $projectRoot 'start.py') @LauncherArguments
    exit $LASTEXITCODE
} catch {
    Write-Host ''
    Write-Host ('Setup could not continue: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host 'Project data has not been reset. Check the connection, disk space and permissions, then run Start FRIB.cmd again.'
    exit 1
} finally {
    if ($bootstrapLock) { $bootstrapLock.Dispose() }
}
