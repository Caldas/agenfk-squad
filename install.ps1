<#
.SYNOPSIS
  Links the squad into the user level of Claude Code on Windows. Idempotent. The twin of install.sh.

.DESCRIPTION
  Never overwrites a real file: it creates or updates links, and copies that it marked as its own.

    directories (skills)   a symbolic link when Windows allows it, otherwise a junction (no privilege needed)
    files (agents, hooks)  a symbolic link when Windows allows it, otherwise a MARKED COPY: the copy is
                           recorded in <config>\squad\copies.txt with its sha256, so the next run refreshes
                           it when the repository moved, and leaves it alone when you edited it.

  Only what lives in this repository is linked: a source that resolves elsewhere (a skill directory pointing
  at a download, say) is REFUSED.

.PARAMETER ConfigDir
  Claude Code's config directory. Default: %CLAUDE_CONFIG_DIR%, else %USERPROFILE%\.claude

.PARAMETER NoSymlink
  Do not try symbolic links: junctions for directories, marked copies for files.

.PARAMETER Uninstall
  Remove what this script made: links into the repository and marked copies that were not edited.
#>
param(
  [string]$ConfigDir = "",
  [switch]$NoSymlink,
  [switch]$Uninstall
)

$ErrorActionPreference = 'Continue'
$Squad = (Get-Item -LiteralPath $PSScriptRoot).FullName
$UserHome = $env:USERPROFILE
if (-not $ConfigDir) { $ConfigDir = $env:CLAUDE_CONFIG_DIR }
if (-not $ConfigDir) { $ConfigDir = Join-Path $UserHome '.claude' }
# a relative path is relative to where the user is standing in PowerShell, not to the process's directory
$Claude = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ConfigDir)

function Say([string]$m) { [Console]::Out.WriteLine($m) }
function Warn([string]$m) { [Console]::Error.WriteLine($m) }

if (-not ('SquadNative' -as [type])) {
  Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;
public static class SquadNative {
  [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
  static extern SafeFileHandle CreateFileW(string name, uint access, uint share, IntPtr sec, uint disp, uint flags, IntPtr tmpl);
  [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
  static extern uint GetFinalPathNameByHandleW(SafeFileHandle h, StringBuilder b, uint n, uint flags);
  // The path with every link on the way resolved (long names, final targets), or null when it does not exist.
  public static string Real(string path) {
    using (SafeFileHandle h = CreateFileW(path, 0, 7, IntPtr.Zero, 3, 0x02000000, IntPtr.Zero)) {
      if (h.IsInvalid) return null;
      StringBuilder sb = new StringBuilder(32768);
      if (GetFinalPathNameByHandleW(h, sb, 32768, 0) == 0) return null;
      string s = sb.ToString();
      if (s.StartsWith(@"\\?\UNC\")) return @"\\" + s.Substring(8);
      if (s.StartsWith(@"\\?\")) return s.Substring(4);
      return s;
    }
  }
}
'@
}

function Real([string]$p) { return [SquadNative]::Real($p) }
function SamePath([string]$a, [string]$b) {
  return ($a.TrimEnd('\').ToLowerInvariant() -eq $b.TrimEnd('\').ToLowerInvariant())
}

$SquadReal = Real $Squad
if (-not $SquadReal) { Warn "ERROR   cannot resolve $Squad"; exit 2 }

function IsInsideRepo([string]$real) {
  return $real.ToLowerInvariant().StartsWith($SquadReal.TrimEnd('\').ToLowerInvariant() + '\')
}
function IsLink($item) {
  # not "any reparse point": a OneDrive placeholder or a dedup stub is one too, and it is a real file
  return ($item.LinkType -eq 'Junction' -or $item.LinkType -eq 'SymbolicLink')
}
function Sha([string]$path) { return (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() }

# ------------------------------------------------------------ the marks of the copies
$MarksFile = Join-Path (Join-Path $Claude 'squad') 'copies.txt'
$Marks = @{}
if (Test-Path -LiteralPath $MarksFile) {
  foreach ($line in [System.IO.File]::ReadAllLines($MarksFile)) {
    if ($line.Length -gt 66) { $Marks[$line.Substring(66).ToLowerInvariant()] = @($line.Substring(0, 64), $line.Substring(66)) }
  }
}
function SaveMarks {
  if ($Marks.Count -eq 0) {
    if (Test-Path -LiteralPath $MarksFile) { Remove-Item -LiteralPath $MarksFile -Force }
    return
  }
  New-Item -ItemType Directory -Force -Path (Split-Path $MarksFile) | Out-Null
  $lines = @()
  foreach ($k in ($Marks.Keys | Sort-Object)) { $lines += ($Marks[$k][0] + '  ' + $Marks[$k][1]) }
  [System.IO.File]::WriteAllLines($MarksFile, $lines)
}
function Mark([string]$dst, [string]$sha) { $Marks[$dst.ToLowerInvariant()] = @($sha, $dst) }
function Unmark([string]$dst) { $Marks.Remove($dst.ToLowerInvariant()) }

# ------------------------------------------------------------ links
$script:SymlinkOk = @{}
# Whether this account may create a symbolic link to a directory ('dir') or to a file ('file'): asked once, by trying.
function CanSymlink([string]$kind) {
  if ($NoSymlink) { return $false }
  if (-not $script:SymlinkOk.ContainsKey($kind)) {
    $probe = Join-Path ([System.IO.Path]::GetTempPath()) ('squad-link-' + [guid]::NewGuid().ToString('N'))
    $target = $Squad
    if ($kind -eq 'file') { $target = Join-Path $Squad 'CLAUDE.md' }
    $made = $false
    try {
      New-Item -ItemType SymbolicLink -Path $probe -Target $target -ErrorAction Stop | Out-Null
      $made = $true
    } catch { }
    $script:SymlinkOk[$kind] = $made
    if ($made) { try { RemoveLink (Get-Item -LiteralPath $probe -Force) } catch { } }
  }
  return $script:SymlinkOk[$kind]
}

# A copy that is recorded as the squad's: the next run may refresh it, and only while nobody edited it.
function CopyMarked([string]$src, [string]$dst) {
  try {
    Copy-Item -LiteralPath $src -Destination $dst -Force -ErrorAction Stop
    $have = Sha $dst
  } catch {
    Warn "SKIPPED $dst could not be copied ($($_.Exception.Message)) - close whatever has it open, then run again"
    return $false
  }
  Mark $dst $have
  return $true
}

function RemoveLink($item) {
  if ($item.PSIsContainer) { [System.IO.Directory]::Delete($item.FullName) } else { [System.IO.File]::Delete($item.FullName) }
}

function MakeLink([string]$src, [string]$dst, [bool]$isDir) {
  $kind = 'file'
  if ($isDir) { $kind = 'dir' }
  if (CanSymlink $kind) {
    try {
      New-Item -ItemType SymbolicLink -Path $dst -Target $src -ErrorAction Stop | Out-Null
      Say "ok      $dst -> $src"
      return $true
    } catch { }
  }
  if ($isDir) {
    try {
      New-Item -ItemType Junction -Path $dst -Target $src -ErrorAction Stop | Out-Null
      Say "ok      $dst -> $src (junction)"
      return $true
    } catch {
      Warn "SKIPPED $dst could not be linked ($($_.Exception.Message))"
      return $false
    }
  }
  if (-not (CopyMarked $src $dst)) { return $false }
  Say "copy    $dst (marked copy of $src)"
  return $true
}

function Link([string]$src, [string]$dst) {
  $isDir = Test-Path -LiteralPath $src -PathType Container
  $real = Real $src
  if (-not $real -or -not (IsInsideRepo $real)) {
    $shown = $real
    if (-not $shown) { $shown = '(unresolvable)' }
    Warn "REFUSED $src resolves to $shown, outside the squad repository ($SquadReal)."
    Warn "        A third-party skill goes in as a copy under skills/vendor/<name>/, with a line in"
    Warn "        skills/vendor/LOCK (origin, commit, sha256 from python tests/test_vendor.py --hash"
    Warn "        skills/vendor/<name>). See `"Proposing a skill`" in CONTRIBUTING.md. The rest is still linked."
    return $false
  }
  $item = Get-Item -LiteralPath $dst -Force -ErrorAction SilentlyContinue
  if ($item) {
    if (IsLink $item) {
      $now = Real $dst
      if ($now -and (SamePath $now $real)) { Say "same    $dst"; return $true }
      RemoveLink $item                                   # a link is the squad's to move, as ln -sfn does
      return (MakeLink $src $dst $isDir)
    }
    if ($isDir) { Warn "SKIPPED $dst exists and is not a link - resolve it by hand"; return $false }
    $key = $dst.ToLowerInvariant()
    if ($Marks.ContainsKey($key)) {
      $have = Sha $dst
      if ($have -ne $Marks[$key][0]) {
        Warn "SKIPPED $dst was edited after the squad copied it - keep it, or delete it and run again"
        return $false
      }
      if ($have -eq (Sha $src)) { Say "same    $dst"; return $true }
      if (-not (CopyMarked $src $dst)) { return $false }
      Say "update  $dst (marked copy of $src)"
      return $true
    }
    Warn "SKIPPED $dst exists and is not a link - resolve it by hand"
    return $false
  }
  return (MakeLink $src $dst $isDir)
}

# ------------------------------------------------------------ the launcher
# The interpreter, as words: SQUAD_PYTHON (one executable, spaces and all), else a real `python`, else `py -3`.
# The `python` in WindowsApps is the Microsoft Store stub, not an install.
function PythonParts {
  if ($env:SQUAD_PYTHON) { return @($env:SQUAD_PYTHON) }
  $p = Get-Command python -ErrorAction SilentlyContinue
  if ($p -and ($p.Source -notmatch 'WindowsApps')) { return @('python') }
  if (Get-Command py -ErrorAction SilentlyContinue) { return @('py', '-3') }
  return @()
}

$ShimMark = 'REM agenfk-squad: written by install.ps1'
$ShimPath = Join-Path (Join-Path (Join-Path $UserHome '.local') 'bin') 'squad-turn.cmd'

function WriteShim {
  $parts = @(PythonParts)
  if ($parts.Count -eq 0) {
    Warn "WARNING no Python 3 on PATH (not the Microsoft Store 'python' alias): squad-turn will not run until there is one."
    $parts = @('python')
  }
  $launcher = '"' + $parts[0] + '"'
  if ($parts.Count -gt 1) { $launcher += ' ' + ($parts[1..($parts.Count - 1)] -join ' ') }
  $body = "@echo off`r`n$ShimMark; it is rewritten on every run`r`n$launcher `"$Squad\hooks\squad-turn.py`" %*`r`n"
  # cmd reads a batch file in the OEM code page, not in UTF-8: a profile called "Jose" with an accent must survive
  $oem = [System.Text.Encoding]::GetEncoding([System.Globalization.CultureInfo]::CurrentCulture.TextInfo.OEMCodePage)
  $bytes = $oem.GetBytes($body)
  if (Test-Path -LiteralPath $ShimPath) {
    $now = [System.IO.File]::ReadAllBytes($ShimPath)
    if ([System.Convert]::ToBase64String($now) -eq [System.Convert]::ToBase64String($bytes)) { Say "same    $ShimPath"; return $true }
    if (-not $oem.GetString($now).Contains($ShimMark)) { Warn "SKIPPED $ShimPath exists and is not the squad's - resolve it by hand"; return $false }
  }
  New-Item -ItemType Directory -Force -Path (Split-Path $ShimPath) | Out-Null
  [System.IO.File]::WriteAllBytes($ShimPath, $bytes)
  Say "ok      $ShimPath -> $Squad\hooks\squad-turn.py"
  return $true
}

# ------------------------------------------------------------ uninstall
if ($Uninstall) {
  foreach ($sub in @('agents', 'skills', 'hooks', '.')) {
    $dir = Join-Path $Claude $sub
    if (-not (Test-Path -LiteralPath $dir)) { continue }
    foreach ($item in (Get-ChildItem -LiteralPath $dir -Force -ErrorAction SilentlyContinue)) {
      if (-not (IsLink $item)) { continue }
      $real = Real $item.FullName
      if ($real -and (IsInsideRepo $real)) { RemoveLink $item; Say "removed $($item.FullName)" }
    }
  }
  foreach ($k in @($Marks.Keys)) {
    $dst = $Marks[$k][1]
    if (-not (Test-Path -LiteralPath $dst)) { Unmark $dst; continue }
    if ((Sha $dst) -eq $Marks[$k][0]) {
      Remove-Item -LiteralPath $dst -Force
      Unmark $dst
      Say "removed $dst"
    } else {
      Warn "kept    $dst - it was edited after the squad copied it"
      Unmark $dst                                          # no longer ours
    }
  }
  SaveMarks
  if (Test-Path -LiteralPath $ShimPath) {
    if ([System.IO.File]::ReadAllText($ShimPath).Contains($ShimMark)) { Remove-Item -LiteralPath $ShimPath -Force; Say "removed $ShimPath" }
  }
  exit 0
}

# ------------------------------------------------------------ install
if (-not (Get-Command agenfk -ErrorAction SilentlyContinue)) {
  Warn "WARNING the 'agenfk' CLI is not on PATH. The squad is built on AgenFK:"
  Warn "        install it from https://github.com/cglab-public/agenfk before using the agents."
  Warn ""
}

foreach ($sub in @('agents', 'hooks', 'skills')) { New-Item -ItemType Directory -Force -Path (Join-Path $Claude $sub) | Out-Null }
$rc = 0

foreach ($f in (Get-ChildItem -LiteralPath (Join-Path $Squad 'agents') -Filter '*.md' -File)) {
  if (-not (Link $f.FullName (Join-Path (Join-Path $Claude 'agents') $f.Name))) { $rc = 1 }
}
# the squad's own skills (one directory per skill) and the third-party ones in vendor\
$skillDirs = @(Get-ChildItem -LiteralPath (Join-Path $Squad 'skills') -Directory -Force | Where-Object { $_.Name -ne 'vendor' })
$vendor = Join-Path (Join-Path $Squad 'skills') 'vendor'
if (Test-Path -LiteralPath $vendor) { $skillDirs += @(Get-ChildItem -LiteralPath $vendor -Directory -Force) }
foreach ($d in $skillDirs) {
  if (-not (Test-Path -LiteralPath (Join-Path $d.FullName 'SKILL.md'))) { continue }
  if (-not (Link $d.FullName (Join-Path (Join-Path $Claude 'skills') $d.Name))) { $rc = 1 }
}
if (-not (Link (Join-Path $Squad 'CLAUDE.md') (Join-Path $Claude 'CLAUDE.md'))) { $rc = 1 }
foreach ($h in @('squad-router.py', 'squad-watch.py', 'squad-switch.py', 'squad-turn.py')) {
  if (-not (Link (Join-Path (Join-Path $Squad 'hooks') $h) (Join-Path (Join-Path $Claude 'hooks') $h))) { $rc = 1 }
}
if (-not (WriteShim)) { $rc = 1 }

# oh-my-pi (omp) reads a different agent dialect at ~\.omp\agent\agents; see skills/harness-port/SKILL.md
if (Get-Command omp -ErrorAction SilentlyContinue) {
  $ext = Join-Path $UserHome '.omp\agent\extensions'
  New-Item -ItemType Directory -Force -Path $ext | Out-Null
  if (-not (Link (Join-Path (Join-Path $Squad 'extensions') 'squad-watch-omp.ts') (Join-Path $ext 'squad-watch-omp.ts'))) { $rc = 1 }
  $parts = @(PythonParts)
  if ($parts.Count -gt 0) {
    $exe = $parts[0]
    $pre = @()
    if ($parts.Count -gt 1) { $pre = $parts[1..($parts.Count - 1)] }
    $out = Join-Path $UserHome '.omp\agent\agents'
    & $exe @pre (Join-Path $Squad 'skills\harness-port\scripts\omp_agents.py') render --src (Join-Path $Squad 'agents') --out $out
    if ($LASTEXITCODE -eq 0) { Say "omp agents rendered into $out." } else { $rc = 1 }
  }
} else {
  Say "note    omp not on PATH; skipped the oh-my-pi agent adapter"
}

SaveMarks

Say ""
Say "New agents and skills only show up in sessions started after this step."
Say "Hooks in settings.json: scripts\squad_settings.py registers them (get.ps1 runs it for you)."
exit $rc
