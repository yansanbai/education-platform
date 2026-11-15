param([switch]$Demo,[int]$Port=8000)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$python=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if($Demo){$env:MOCK_GRADING='1'}else{$env:MOCK_GRADING='0'}
$worker=Start-Process -FilePath $python -ArgumentList 'app.py','worker' -WindowStyle Hidden -PassThru
try { & $python -m uvicorn app:app --host 127.0.0.1 --port $Port }
finally { if(-not $worker.HasExited){Stop-Process -Id $worker.Id} }
