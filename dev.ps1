$ErrorActionPreference = "Stop"

$backend = Start-Process uv `
    -ArgumentList "run", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory "$PSScriptRoot\backend" `
    -NoNewWindow `
    -PassThru

try {
    Set-Location "$PSScriptRoot\frontend"
    pnpm dev
}
finally {
    if (-not $backend.HasExited) {
        taskkill /PID $backend.Id /T /F | Out-Null
    }
    Set-Location $PSScriptRoot
}
