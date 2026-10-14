# Starts the local portable PostgreSQL for the TechIS demo (no Docker).
# Portable install lives OUTSIDE the repository at C:\pg17.
# Usage (from the project root):  .\scripts\start-postgres.ps1
$pgCtl = "C:\pg17\pgsql\bin\pg_ctl.exe"
$dataDir = "C:\pg17\pgsql\data"
$log = "C:\pg17\pg.log"

$listening = Get-NetTCPConnection -LocalPort 5432 -State Listen -ErrorAction SilentlyContinue
if ($listening) {
    Write-Host "PostgreSQL already running on port 5432."
    exit 0
}

Start-Process -FilePath $pgCtl `
    -ArgumentList "-D `"$dataDir`" -l `"$log`" -w start -o `"-p 5432 -h 127.0.0.1`"" `
    -WindowStyle Hidden

# Wait for the port to come up
$ok = $false
foreach ($i in 1..20) {
    Start-Sleep -Seconds 1
    if (Get-NetTCPConnection -LocalPort 5432 -State Listen -ErrorAction SilentlyContinue) {
        $ok = $true
        break
    }
}
if ($ok) {
    Write-Host "PostgreSQL started (detached) on 127.0.0.1:5432."
} else {
    Write-Error "PostgreSQL failed to start. Check $log"
    exit 1
}

# Stop with:  C:\pg17\pgsql\bin\pg_ctl.exe -D C:\pg17\pgsql\data stop
