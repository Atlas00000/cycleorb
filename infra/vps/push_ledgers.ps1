# INF-P7-T04: VPS side of the forward telemetry. Copies the EA's live ledgers
# (Common\Files\CycleORB\CORB_<magic>_<symbol>_live_{decisions,events,shadow}.csv) to a folder that syncs to the
# workstation (e.g. OneDrive). One-way: it only reads the ledgers and only writes to -Target; no port is opened and
# the terminal is not touched. The EA keeps the files open for writing, so they are read with shared access.
#
#   powershell -ExecutionPolicy Bypass -File push_ledgers.ps1 -Target "$env:OneDrive\CycleORB_vps"
#   powershell -ExecutionPolicy Bypass -File push_ledgers.ps1 -Target "$env:OneDrive\CycleORB_vps" -Install   # hourly task
param(
    [Parameter(Mandatory = $true)][string]$Target,
    [switch]$Install
)
$ErrorActionPreference = "Stop"
$source = Join-Path $env:APPDATA "MetaQuotes\Terminal\Common\Files\CycleORB"

if ($Install) {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Target `"$Target`""
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 1)
    Register-ScheduledTask -TaskName "CycleORB ledger push" -Action $action -Trigger $trigger -Force | Out-Null
    Write-Output "scheduled hourly: CycleORB ledger push -> $Target"
}

New-Item -ItemType Directory -Force -Path $Target | Out-Null
$copied = 0
foreach ($f in Get-ChildItem $source -Filter "CORB_*_live_*.csv") {
    $tmp = Join-Path $Target ($f.Name + ".part")
    $dst = Join-Path $Target $f.Name
    $in = [System.IO.File]::Open($f.FullName, 'Open', 'Read', 'ReadWrite')
    try {
        $out = [System.IO.File]::Create($tmp)
        try { $in.CopyTo($out) } finally { $out.Close() }
    } finally { $in.Close() }
    if ((Test-Path $dst) -and ((Get-FileHash $dst).Hash -eq (Get-FileHash $tmp).Hash)) {
        Remove-Item $tmp
    } else {
        Move-Item $tmp $dst -Force
        $copied++
    }
}
Write-Output "$(Get-Date -Format s) pushed $copied changed ledger file(s) to $Target"
