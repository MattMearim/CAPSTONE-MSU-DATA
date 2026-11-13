[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$fribRoot=[IO.Path]::GetFullPath($PSScriptRoot)
Write-Output 'Preparing private Python and application packages...'
& (Join-Path $fribRoot 'Install-PythonRuntime.ps1')
& (Join-Path $fribRoot 'Install-Packages.ps1')
Write-Output 'Preparing the private model engine...'
& (Join-Path $fribRoot 'Install-Ollama.ps1')
$fribPython=Join-Path $fribRoot 'venv\Scripts\python.exe'
Write-Output 'Preparing semantic search embeddings...'
& $fribPython (Join-Path $fribRoot 'Install-EmbeddingModel.py')
if ($LASTEXITCODE) { throw 'Embedding preparation failed.' }
Write-Output 'Preparing the main AI model...'
& $fribPython (Join-Path $fribRoot 'Prepare-Models.py')
if ($LASTEXITCODE) { throw 'Main-model preparation failed.' }
& $fribPython (Join-Path $fribRoot 'Verify-Models.py')
if ($LASTEXITCODE) { throw 'Real-model verification failed.' }
Write-Output 'Setup complete. Open START_PROJECT.cmd to run the workspace.'
