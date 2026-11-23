# Stage one authentication key for the *existing* Windows Strata source install.
# Does not stop/restart Strata, spawn a model, change LAN rules or send the key.
# Windows PowerShell 5.1+.
param([switch]$Stage)
$ErrorActionPreference = 'Stop'
$config = 'D:\local-ai-probe\Strata\strata-coder-iq1_m.json'
if (-not $Stage) {
    Write-Output 'NO_CHANGE_PASS_-Stage_TO_STAGE_KEY'
    exit 0
}
if (-not [IO.File]::Exists($config)) { throw 'EXISTING_STRATA_CONFIG_NOT_FOUND' }
$file = Get-Item -LiteralPath $config
if (($file.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw 'STRATA_CONFIG_SYMLINK_REJECTED'
}
$data = Get-Content -LiteralPath $config -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $data.exe -or -not $data.args -or -not $data.model_name) {
    throw 'STRATA_ENGINE_CONFIG_UNRECOGNISED'
}
$key = [string]$data.api_key
if ($key -eq 'none') { $key = '' }
if (-not [string]::IsNullOrWhiteSpace($key)) {
    if ($key.Length -lt 16) { throw 'EXISTING_KEY_TOO_SHORT' }
    Set-Clipboard -Value $key
    Write-Output 'EXISTING_KEY_COPIED_NO_CHANGE'
    exit 0
}
$backup = $config + '.before-auth.bak'
if ([IO.File]::Exists($backup)) { throw 'BACKUP_ALREADY_EXISTS_REVIEW_REQUIRED' }
$bytes = New-Object byte[] 32
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
$key = ([Convert]::ToBase64String($bytes)).TrimEnd('=').Replace('+','-').Replace('/','_')
$data | Add-Member -NotePropertyName api_key -NotePropertyValue $key -Force
$temp = $config + '.auth-' + [guid]::NewGuid().ToString('N') + '.tmp'
try {
    [IO.File]::WriteAllText($temp, ($data | ConvertTo-Json -Depth 100),
                           ([System.Text.UTF8Encoding]::new($false)))
    # Transactional write and one rollback copy of the previous no-key JSON.
    [IO.File]::Replace($temp, $config, $backup, $true)
} finally {
    if ([IO.File]::Exists($temp)) { Remove-Item -LiteralPath $temp }
}
Set-Clipboard -Value $key
Write-Output 'STRATA_AUTH_KEY_STAGED_IN_JSON'
Write-Output 'KEY_COPIED_TO_WINDOWS_CLIPBOARD'
Write-Output 'RUNNING_STRATA_UNCHANGED_RESTART_REQUIRED'
