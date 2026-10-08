param([Parameter(Mandatory=$true)][string]$ZipPath)
# Python runner writes UTF-8 logs and creates its own Compose project/volume.
& python (Join-Path $PSScriptRoot 'run_m6_docker.py') --zip $ZipPath
exit $LASTEXITCODE
