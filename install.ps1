<#
.SYNOPSIS
  agent-memory-kit installer.
.DESCRIPTION
  Copies the kit into a target repository. Local file copy only: no network,
  no package installs, no writes outside the target directory. Existing files
  are never overwritten unless -Force is passed.
.EXAMPLE
  .\install.ps1 C:\src\my-project
.EXAMPLE
  .\install.ps1 . -Force
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Target,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$src = $PSScriptRoot

if (-not (Test-Path -LiteralPath $Target -PathType Container)) {
    Write-Error "'$Target' is not a directory"
    exit 2
}
$Target = (Resolve-Path -LiteralPath $Target).Path
if ($Target -eq $src) {
    Write-Error "Target is the kit itself; pass your project directory"
    exit 2
}

$files = @(
    'AGENTS.md',
    'SETUP.md',
    '.github/copilot-instructions.md',
    '.agent/skills/codebase-memory/SKILL.md',
    '.agent/skills/codebase-memory/index.py',
    '.agent/skills/codebase-memory/query.py'
)

$copied = 0
$skipped = 0
foreach ($f in $files) {
    $rel  = $f -replace '/', [IO.Path]::DirectorySeparatorChar
    $dest = Join-Path $Target $rel
    if ((Test-Path -LiteralPath $dest) -and (-not $Force)) {
        Write-Host "  skip     $f (exists; use -Force to overwrite)"
        $skipped++
        continue
    }
    $dir = Split-Path -Parent $dest
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    Copy-Item -LiteralPath (Join-Path $src $rel) -Destination $dest -Force
    Write-Host "  install  $f"
    $copied++
}

Write-Host ""
Write-Host "$copied file(s) installed, $skipped skipped."
Write-Host ""
Write-Host "Next:"
Write-Host "  cd `"$Target`""
Write-Host "  Add-Content .gitignore '.agent/work/'"
Write-Host "  python .agent\skills\codebase-memory\index.py build"
Write-Host ""
Write-Host "Add '.agent/memory/' to .gitignore too if each developer should build"
Write-Host "their own index instead of sharing one committed map."
