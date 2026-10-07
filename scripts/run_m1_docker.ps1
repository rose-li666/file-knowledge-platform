param(
    [string]$ZipPath = 'D:\__10_.zip',
    [string]$ReportDirectory = '',
    [int]$Port = 8000
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $ReportDirectory) { $ReportDirectory = Join-Path (Split-Path -Parent $projectRoot) 'm1-docker' }
$fixturePath = (Resolve-Path -LiteralPath $ZipPath).Path
New-Item -ItemType Directory -Force -Path $ReportDirectory | Out-Null
$reportRoot = (Resolve-Path -LiteralPath $ReportDirectory).Path
$results = [System.Collections.Generic.List[object]]::new()
$started = [DateTimeOffset]::UtcNow
$failure = $null
$restOptions = @{}
if ((Get-Command Invoke-RestMethod).Parameters.ContainsKey('NoProxy')) { $restOptions.NoProxy = $true }

function Invoke-DockerStep {
    param([string]$Label, [string[]]$Arguments)
    $clock = [Diagnostics.Stopwatch]::StartNew()
    Write-Host ('Executing: docker ' + ($Arguments -join ' '))
    $priorPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & docker @Arguments 2>&1 | ForEach-Object { $_.ToString() } | Tee-Object -FilePath (Join-Path $reportRoot ($Label + '.log')) | Out-Host
    $commandExit = $LASTEXITCODE
    $ErrorActionPreference = $priorPreference
    $results.Add([pscustomobject]@{ step=$Label; command=('docker '+($Arguments -join ' ')); exitCode=$commandExit; seconds=[math]::Round($clock.Elapsed.TotalSeconds,3) })
    if ($commandExit -ne 0) { throw ('Docker step failed: ' + $Label + ', exit ' + $commandExit) }
}

Push-Location -LiteralPath $projectRoot
$priorPort = $env:APP_PORT
try {
    $env:APP_PORT = "$Port"
    Invoke-DockerStep -Label '01-version' -Arguments @('version')
    Invoke-DockerStep -Label '02-config' -Arguments @('compose','config','--quiet')
    Invoke-DockerStep -Label '03-build-start' -Arguments @('compose','up','--build','-d')
    Invoke-DockerStep -Label '04-status' -Arguments @('compose','ps')
    $baseUrl = "http://127.0.0.1:$Port"
    $healthClock = [Diagnostics.Stopwatch]::StartNew()
    $health = $null
    while ($healthClock.Elapsed.TotalSeconds -lt 120) {
        try {
            $health = Invoke-RestMethod -Uri "$baseUrl/api/v1/health" -TimeoutSec 5 @restOptions
            break
        } catch { Start-Sleep -Seconds 2 }
    }
    if (-not $health) { throw 'Health endpoint did not respond within 120 seconds' }
    $health | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $reportRoot 'health.json') -Encoding utf8
    if ($health.status -ne 'ready') { throw ('Health reports ' + $health.status + '; inspect health.json') }
    $results.Add([pscustomobject]@{ step='health'; passed=$true; seconds=[math]::Round($healthClock.Elapsed.TotalSeconds,3) })
    $probeValue = 'M1 Docker actual probe ' + [Guid]::NewGuid().ToString()
    $saved = Invoke-RestMethod -Uri "$baseUrl/api/v1/m1/probes" -Method Post -ContentType 'application/json' -Body (@{value=$probeValue}|ConvertTo-Json) @restOptions
    $read = Invoke-RestMethod -Uri "$baseUrl/api/v1/m1/probes" @restOptions
    if (-not ($read.items | Where-Object { $_.id -eq $saved.id -and $_.value -eq $probeValue })) { throw 'Database read does not match written probe' }
    $results.Add([pscustomobject]@{step='database-write-read'; passed=$true; id=$saved.id})
    $pageOptions = @{}
    if ((Get-Command Invoke-WebRequest).Parameters.ContainsKey('NoProxy')) { $pageOptions.NoProxy=$true }
    $page = Invoke-WebRequest -Uri "$baseUrl/" -UseBasicParsing @pageOptions
    if ($page.StatusCode -ne 200 -or $page.Content -notmatch 'id="root"') { throw 'Built frontend HTML not served' }
    $assets = [regex]::Matches($page.Content,'(?:src|href)="(/assets/[^\"]+)"')
    if ($assets.Count -lt 2) { throw 'Frontend build assets missing from HTML' }
    foreach ($asset in $assets) {
        $assetResponse = Invoke-WebRequest -Uri ($baseUrl + $asset.Groups[1].Value) -UseBasicParsing @pageOptions
        if ($assetResponse.StatusCode -ne 200) { throw ('Frontend asset unavailable: '+$asset.Groups[1].Value) }
    }
    $results.Add([pscustomobject]@{step='frontend-html-assets';passed=$true;browserRender='not automatically verified'})
    Invoke-DockerStep -Label '05-container-semantic' -Arguments @(
        'compose','run','--rm','--no-deps',
        '-v',($fixturePath+':/fixtures/test-documents.zip:ro'),
        '-v',($reportRoot+':/reports'),
        'app','python','scripts/evaluate_m1.py',
        '--zip','/fixtures/test-documents.zip','--model-dir','/opt/models/bge',
        '--data-dir','/data','--report','/reports/semantic-results.json'
    )
} catch {
    $failure = $_.Exception.Message
    Write-Warning $failure
} finally {
    $ErrorActionPreference = 'Continue'
    & docker compose logs --tail=100 app 2>&1 | ForEach-Object { $_.ToString() } | Set-Content -LiteralPath (Join-Path $reportRoot 'app.log') -Encoding utf8
    $summary = [ordered]@{
        executedBy='user normal PowerShell; inspect actual generated logs';
        startedUtc=$started.ToString('o'); finishedUtc=[DateTimeOffset]::UtcNow.ToString('o');
        steps=$results.ToArray(); failure=$failure;
        browserRender='manual verification still required';
        deferred=@('M5 task recovery','M5 deduplication','M5 fault injection')
    }
    $summary | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $reportRoot 'execution-summary.json') -Encoding utf8
    $env:APP_PORT = $priorPort
    Pop-Location
}
Write-Host ('Evidence saved to: ' + $reportRoot)
if ($failure) { exit 1 }
Write-Host ('Open '+"http://localhost:$Port"+' and click the database probe button to verify real browser interaction.')
