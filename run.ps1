# run.ps1 — starts the proxy and launches aider
# Usage: .\run.ps1

$scriptDir = $PSScriptRoot
if (-not $scriptDir) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}
$logPath = Join-Path $scriptDir "logs\raw_traffic.jsonl"
$pythonScripts = @(
    Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\Scripts"
    Join-Path $env:APPDATA "Python\Python313\Scripts"
)

foreach ($dir in $pythonScripts) {
    if ((Test-Path $dir) -and ($env:PATH -notlike "*$dir*")) {
        $env:PATH = "$dir;$env:PATH"
    }
}

# Load the .env file
Get-Content (Join-Path $scriptDir ".env") | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
        [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
    }
}

$key = $env:GEMINI_API_KEY
if (-not $key -or $key -eq "paste-your-key-here") {
    Write-Host "ERROR: Add your Gemini API key to .env first" -ForegroundColor Red
    exit 1
}

# Set up proxy routing — aider thinks it's talking to OpenAI, proxy forwards to Gemini
$env:OPENAI_API_KEY  = $key
$env:OPENAI_API_BASE  = "http://localhost:8000/v1beta/openai"
$env:OPENAI_BASE_URL  = "http://localhost:8000/v1beta/openai"

if (-not (Get-Command uvicorn -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: uvicorn is not on PATH. Activate the right Python environment first." -ForegroundColor Red
    exit 1
}

if (-not (Get-Command aider -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: aider is not on PATH." -ForegroundColor Red
    Write-Host "The package currently installed as 'aider' is not the Aider CLI, so it does not provide an aider command." -ForegroundColor Red
    Write-Host "Install the documented CLI with: python -m pip install aider-install`nThen run: aider-install" -ForegroundColor Red
    exit 1
}

# Clear old log and ensure the file exists for later reading
New-Item -ItemType Directory -Path (Join-Path $scriptDir "logs") -Force | Out-Null
if (Test-Path $logPath) { Remove-Item $logPath }
New-Item -ItemType File -Path $logPath -Force | Out-Null

# Start proxy in background
Write-Host "Starting proxy..." -ForegroundColor Cyan
$proxy = Start-Process -FilePath "uvicorn" -ArgumentList "proxy:app --port 8000" `
    -PassThru -WindowStyle Minimized
Start-Sleep -Seconds 2

Write-Host "Proxy running (PID $($proxy.Id))" -ForegroundColor Green
Write-Host "Traffic will be logged to $logPath" -ForegroundColor Green
Write-Host "OpenAI base URL for the harness: $env:OPENAI_BASE_URL" -ForegroundColor Green
Write-Host ""
Write-Host "Starting aider — use it normally, then Ctrl+C to exit and read the log." -ForegroundColor Yellow
Write-Host ""

# Launch aider — routed through proxy
aider --model openai/gemini-2.5-flash --no-auto-commits

# When aider exits, kill proxy
Write-Host ""
Write-Host "Aider exited. Stopping proxy..." -ForegroundColor Cyan
Stop-Process -Id $proxy.Id -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Done. Reading captured traffic:" -ForegroundColor Green
Write-Host ""

# Pretty-print the log
if (-not (Test-Path $logPath) -or ((Get-Item $logPath).Length -eq 0)) {
    Write-Host "No traffic was captured, so there is nothing to print." -ForegroundColor Yellow
    Write-Host "That usually means Aider did not send any requests through the proxy." -ForegroundColor Yellow
    Write-Host "If that seems wrong, check that the proxy started successfully and that OPENAI_BASE_URL or OPENAI_API_BASE is set to http://localhost:8000/v1beta/openai." -ForegroundColor Yellow
    exit 0
}

Get-Content $logPath | ForEach-Object {
    $entry = $_ | ConvertFrom-Json
    Write-Host "--- Request $($entry.id) | $($entry.ms)ms | status $($entry.status) ---" -ForegroundColor Cyan
    Write-Host "REQUEST:" -ForegroundColor Yellow
    $entry.request | ConvertTo-Json -Depth 10
    Write-Host "RESPONSE:" -ForegroundColor Green
    $entry.response | ConvertTo-Json -Depth 10
    Write-Host ""
}
