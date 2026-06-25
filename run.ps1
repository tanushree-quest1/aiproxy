$scriptDir = $PSScriptRoot
if (-not $scriptDir) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}

$logPath = Join-Path $scriptDir "logs\raw_traffic.json"

Get-Content (Join-Path $scriptDir ".env") | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
        [System.Environment]::SetEnvironmentVariable(
            $matches[1].Trim(),
            $matches[2].Trim(),
            "Process"
        )
    }
}

$key = $env:GEMINI_API_KEY

New-Item -ItemType Directory -Path (Join-Path $scriptDir "logs") -Force | Out-Null

if (Test-Path $logPath) {
    Remove-Item $logPath
}

New-Item -ItemType File -Path $logPath -Force | Out-Null

Write-Host "Starting custom Gemini proxy..." -ForegroundColor Cyan

$proxy = Start-Process `
    -FilePath "uvicorn" `
    -ArgumentList "proxy:app --port 8000" `
    -PassThru `
    -WindowStyle Minimized

Start-Sleep -Seconds 2

Write-Host "Custom proxy PID: $($proxy.Id)" -ForegroundColor Green

$env:OPENAI_API_KEY = $key
$env:OPENAI_API_BASE = "http://localhost:8000/v1beta/openai"
$env:OPENAI_BASE_URL = "http://localhost:8000/v1beta/openai"

Write-Host ""
Write-Host "Chain active:" -ForegroundColor Green
Write-Host "Opencode -> Custom Proxy (8000) -> Gemini"
Write-Host ""

Write-Host "Starting Opencode..." -ForegroundColor Yellow
Write-Host ""

opencode `
    -m gemini-proxy/gemini-2.5-flash

Write-Host ""
Write-Host "Stopping custom proxy..." -ForegroundColor Cyan

Stop-Process -Id $proxy.Id -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Raw traffic log:"
Write-Host $logPath