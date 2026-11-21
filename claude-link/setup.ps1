# ClaudeLink setup for Windows.
# 1. Copies the ClaudeLink addon into WoW Forever.
# 2. Installs the server (Python) in this folder.
# 3. Connects it to the Claude desktop app.
# Run:  powershell -ExecutionPolicy Bypass -File .\setup.ps1 [-Game "C:\...\_forever_"]
param([string]$Game)
$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Server = Join-Path $Here 'server'

# Run a program and return its exit code and output. Windows PowerShell treats
# anything a program prints to stderr (python --version, pip notices) as an error
# when $ErrorActionPreference is Stop, so relax it only around the call.
function Invoke-Native([string]$Exe, [string[]]$Arguments) {
  $old = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    $out = & $Exe @Arguments 2>&1 | ForEach-Object { "$_" } | Out-String
    return @{ Code = $LASTEXITCODE; Out = $out }
  } catch {
    return @{ Code = 1; Out = "$_" }
  } finally {
    $ErrorActionPreference = $old
  }
}

Write-Host ''
Write-Host 'ClaudeLink setup' -ForegroundColor Cyan

# --- 1. WoW Forever folder ---------------------------------------------------
if (-not $Game) {
  $candidates = @(
    "${env:ProgramFiles(x86)}\World of Warcraft\_forever_",
    "$env:ProgramFiles\World of Warcraft\_forever_",
    'C:\World of Warcraft\_forever_',
    'D:\World of Warcraft\_forever_'
  )
  $Game = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}
if (-not $Game -or -not (Test-Path $Game)) {
  $Game = (Read-Host 'Where is the _forever_ folder? (paste the full path)').Trim('"')
}
if (-not (Test-Path $Game)) { throw "Folder not found: $Game" }
Write-Host "WoW Forever folder: $Game"

# --- 2. Addon ------------------------------------------------------------------
$addons = Join-Path $Game 'Interface\AddOns'
New-Item -ItemType Directory -Force -Path $addons | Out-Null
$target = Join-Path $addons 'ClaudeLink'
if (Test-Path $target) { Remove-Item -Recurse -Force $target }
Copy-Item -Recurse (Join-Path $Here 'addon\ClaudeLink') $target
Write-Host "Addon installed in $target" -ForegroundColor Green

# --- 3. Python and the server ---------------------------------------------------
$py = $null
foreach ($cmd in @('py', 'python')) {
  if (Get-Command $cmd -ErrorAction SilentlyContinue) {
    $verArgs = if ($cmd -eq 'py') { @('-3', '--version') } else { @('--version') }
    $r = Invoke-Native $cmd $verArgs
    if ($r.Code -eq 0 -and $r.Out -match 'Python 3\.(\d+)' -and [int]$Matches[1] -ge 10) { $py = $cmd; break }
  }
}
if (-not $py) {
  throw 'Python 3.10 or newer is needed. Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH"), then run this again.'
}
Write-Host "Using Python: $py"
$venv = Join-Path $Server '.venv'
$venvPy = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $venvPy)) {
  $venvArgs = if ($py -eq 'py') { @('-3', '-m', 'venv', $venv) } else { @('-m', 'venv', $venv) }
  $r = Invoke-Native $py $venvArgs
  if ($r.Code -ne 0 -or -not (Test-Path $venvPy)) { throw "Creating the Python environment failed:`n$($r.Out)" }
}
Write-Host 'Installing Python packages (this can take a minute)...'
$null = Invoke-Native $venvPy @('-m', 'pip', 'install', '--upgrade', 'pip', '--quiet', '--disable-pip-version-check')
$r = Invoke-Native $venvPy @('-m', 'pip', 'install', '-r', (Join-Path $Server 'requirements.txt'), '--quiet', '--disable-pip-version-check')
if ($r.Code -ne 0) { throw "Installing the Python packages failed:`n$($r.Out)" }
# No quotes inside the code: Windows PowerShell 5.1 strips them when calling a program.
$r = Invoke-Native $venvPy @('-c', 'import mcp.server.fastmcp, mss, PIL')
if ($r.Code -ne 0) { throw "The Python packages did not install correctly:`n$($r.Out)" }
Write-Host 'Server installed' -ForegroundColor Green

$utf8 = New-Object System.Text.UTF8Encoding $false
$config = @{ wow_dir = $Game; window_title = 'World of Warcraft' } | ConvertTo-Json
[IO.File]::WriteAllText((Join-Path $Server 'config.json'), $config, $utf8)

# --- 4. Claude desktop app ------------------------------------------------------------
$dirs = @(Join-Path $env:APPDATA 'Claude')
$dirs += Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA 'Packages') -Filter 'Claude_*' -Directory -ErrorAction SilentlyContinue |
  ForEach-Object { Join-Path $_.FullName 'LocalCache\Roaming\Claude' } | Where-Object { Test-Path $_ }

$entry = [pscustomobject]@{ command = $venvPy; args = @((Join-Path $Server 'server.py')) }
foreach ($dir in $dirs) {
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
  $file = Join-Path $dir 'claude_desktop_config.json'
  $cfg = [pscustomobject]@{}
  if (Test-Path $file) {
    Copy-Item $file "$file.before-claudelink" -Force
    $text = [IO.File]::ReadAllText($file)
    if ($text.Trim()) { $cfg = $text | ConvertFrom-Json }
  }
  if (-not ($cfg.PSObject.Properties.Name -contains 'mcpServers')) {
    $cfg | Add-Member -NotePropertyName mcpServers -NotePropertyValue ([pscustomobject]@{})
  }
  $cfg.mcpServers | Add-Member -NotePropertyName 'wow-forever' -NotePropertyValue $entry -Force
  [IO.File]::WriteAllText($file, ($cfg | ConvertTo-Json -Depth 20), $utf8)
  Write-Host "Connected to Claude: $file" -ForegroundColor Green
}

Write-Host ''
Write-Host 'Done. Next:' -ForegroundColor Cyan
Write-Host '  1. Quit the Claude app completely (also from the tray icon) and open it again.'
Write-Host '  2. Start WoW Forever. Make sure ClaudeLink is enabled in the AddOns list.'
Write-Host '  3. In the game type /claudesync once.'
Write-Host '  4. Ask Claude: "check the link to my game".'
