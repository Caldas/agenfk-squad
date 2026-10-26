<#
.SYNOPSIS
  One-command install of agenfk-squad on Windows. The twin of get.sh (which is for Linux, WSL and macOS).

.DESCRIPTION
    irm https://raw.githubusercontent.com/eduardopin/agenfk-squad/main/get.ps1 | iex
    & ([scriptblock]::Create((irm https://raw.githubusercontent.com/eduardopin/agenfk-squad/main/get.ps1))) -Beta

  Options (the same as environment variables; an option wins over a variable):
    -Stable          the latest vX.Y.Z tag on main, or main while there is none (default)
    -Beta            the beta branch                       SQUAD_CHANNEL=stable|beta
    -Ref <name>      a tag, branch or commit               SQUAD_REF=<name>
    -Uninstall       remove the squad's hook entries from settings.json and the links and marked copies
                     that install.ps1 made; the clone stays
    -Purge           with -Uninstall: delete the clone as well
  Other variables:
    SQUAD_HOME         where the clone lives (default %USERPROFILE%\.local\share\agenfk-squad)
    SQUAD_REPO         where to clone from (default the GitHub repository)
    SQUAD_PYTHON       the Python 3.10+ executable to run the installer's scripts with (default: python, else py -3)
    CLAUDE_CONFIG_DIR  Claude Code's config directory (default %USERPROFILE%\.claude)

  Steps: checks the prerequisites (git, Python 3.10+); clones, or updates the clone with fetch and checkout
  (a clone with local changes is refused, never overwritten); runs the clone's install.ps1, which links
  directories and links or marks-and-copies files; registers the hooks from hooks/manifest.json in
  settings.json with scripts/squad_settings.py (merge, idempotent, backup first, invalid JSON is left alone).
  Running it again updates.

  It never closes your terminal: it is meant to run in your session (irm | iex), so an error is reported
  and the prompt comes back. Run as a file (-File), the exit code is the result.
#>
param(
  [switch]$Stable,
  [switch]$Beta,
  [string]$Ref = "",
  [switch]$Uninstall,
  [switch]$Purge,
  [switch]$Help,
  [Parameter(ValueFromRemainingArguments = $true)]$Rest
)

# Everything lives in one function, so that nothing but its name reaches the caller's session (the function
# removes itself at the end), and so that `return` and `throw` end it without ending the caller's shell.
function Invoke-SquadGet {
  param($State, [bool]$Stable, [bool]$Beta, [string]$Ref, [bool]$Uninstall, [bool]$Purge, [bool]$Help, $Rest)

  $ErrorActionPreference = 'Continue'
  $DefaultRepo = 'https://github.com/eduardopin/agenfk-squad.git'
  $GetUrl = 'https://raw.githubusercontent.com/eduardopin/agenfk-squad/main/get.ps1'
  $State.Exit = 0

  function Say([string]$m) { [Console]::Out.WriteLine($m) }
  function Warn([string]$m) { [Console]::Error.WriteLine("WARNING $m") }
  function Die([string]$m) { throw $m }
  function Resolve([string]$p) { return $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($p) }

  if ($Help) {
    Say "agenfk-squad installer for Windows: irm $GetUrl | iex"
    Say "  -Stable | -Beta | -Ref <tag|branch|commit>     what to install (default: the latest vX.Y.Z tag on main)"
    Say "  -Uninstall [-Purge]                             remove the hooks, links and marked copies; -Purge also deletes the clone"
    Say "  SQUAD_HOME SQUAD_REPO SQUAD_PYTHON SQUAD_CHANNEL SQUAD_REF CLAUDE_CONFIG_DIR   environment variables"
    return
  }
  if ($Rest -and @($Rest).Count -gt 0) { Die "unknown option '$(@($Rest)[0])' (see -Help)" }

  $UserHome = $env:USERPROFILE
  $Repo = $env:SQUAD_REPO; if (-not $Repo) { $Repo = $DefaultRepo }
  $Dir = $env:SQUAD_HOME; if (-not $Dir) { $Dir = Join-Path $UserHome '.local\share\agenfk-squad' }
  $Claude = $env:CLAUDE_CONFIG_DIR; if (-not $Claude) { $Claude = Join-Path $UserHome '.claude' }
  $Channel = $env:SQUAD_CHANNEL; if (-not $Channel) { $Channel = 'stable' }
  $RefName = $env:SQUAD_REF

  if ($Stable -and $Beta) { Die "choose one: -Stable or -Beta" }
  if (($Stable -or $Beta) -and $Ref) { Die "choose one: -Beta or -Ref" }
  if ($Ref) { $RefName = $Ref }
  elseif ($Beta) { $Channel = 'beta'; $RefName = '' }
  elseif ($Stable) { $Channel = 'stable'; $RefName = '' }
  if ($Channel -ne 'stable' -and $Channel -ne 'beta') { Die "unknown channel '$Channel': use stable or beta, or -Ref <tag|branch|commit>" }
  if ($Purge -and -not $Uninstall) { Die "-Purge only goes with -Uninstall" }

  # a relative path is relative to where the user is standing in PowerShell, not to the process's directory
  $Dir = Resolve $Dir
  $Claude = Resolve $Claude

  # ---------------------------------------------------------------- prerequisites
  function Have([string]$name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }

  # The interpreter that runs the installer's scripts: SQUAD_PYTHON, else a real `python`, else `py -3`.
  # The `python` in %LOCALAPPDATA%\Microsoft\WindowsApps is the Microsoft Store stub, not an install.
  function PythonCommand {
    if ($env:SQUAD_PYTHON) { return @($env:SQUAD_PYTHON) }
    $p = Get-Command python -ErrorAction SilentlyContinue
    if ($p -and ($p.Source -notmatch 'WindowsApps')) { return @($p.Source) }
    if (Have 'py') { return @('py', '-3') }
    return @()
  }
  $pyCmd = @(PythonCommand)
  function Py {                     # runs the chosen interpreter with the given arguments
    $exe = $pyCmd[0]
    $pre = @()
    if ($pyCmd.Count -gt 1) { $pre = $pyCmd[1..($pyCmd.Count - 1)] }
    & $exe @pre @args
  }

  $missing = $false
  if (-not (Have 'git')) {
    [Console]::Error.WriteLine("MISSING git: run: winget install --id Git.Git   (https://git-scm.com/download/win)")
    $missing = $true
  }
  $pyHow = "install Python from https://www.python.org/downloads/ (or: winget install Python.Python.3.12) and tick 'Add python.exe to PATH'." +
           " If typing 'python' opens the Microsoft Store, turn that alias off: Settings > Apps > Advanced app settings > App execution aliases."
  if ($pyCmd.Count -eq 0) {
    [Console]::Error.WriteLine("MISSING python 3.10 or newer: $pyHow")
    $missing = $true
  } else {
    $pyv = ''
    try { $pyv = (Py -c "import sys; print('%d.%d' % sys.version_info[:2]); sys.exit(sys.version_info < (3, 10))" 2>$null | Out-String).Trim() } catch { }
    if ($LASTEXITCODE -ne 0) {
      $found = $pyv; if (-not $found) { $found = 'a python that does not run' }
      [Console]::Error.WriteLine("MISSING python 3.10 or newer (found $found): $pyHow")
      $missing = $true
    }
  }
  if ($missing) { Die "install what is missing above, then run this again. Nothing was changed." }

  if (-not $Uninstall) {
    if (-not (Have 'claude')) { Warn "Claude Code ('claude') is not on PATH. The squad runs inside it: https://claude.com/claude-code" }
    if (-not (Have 'agenfk')) { Warn "the 'agenfk' CLI is not on PATH. The squad's agents call it: https://github.com/cglab-public/agenfk" }
  }

  function GitIn { & git -C $Dir @args }   # not `Git`: command names are case-insensitive, and a function wins over git.exe

  # ---------------------------------------------------------------- uninstall
  # SQUAD_HOME is trusted with deletes and checkouts only once it looks like the squad:
  # SQUAD_HOME=%USERPROFILE%, or a dotfiles repository, must never qualify.
  function IsClone([string]$p) {
    return ((Test-Path -LiteralPath (Join-Path $p '.git')) -and (Test-Path -LiteralPath (Join-Path $p 'hooks\squad-watch.py')) -and
            ((Test-Path -LiteralPath (Join-Path $p 'install.ps1')) -or (Test-Path -LiteralPath (Join-Path $p 'install.sh'))))
  }
  function NotAClone {
    Die "$Dir does not look like an agenfk-squad clone (no .git, install.ps1 and hooks\squad-watch.py), so nothing was changed. Point SQUAD_HOME at the clone"
  }

  if ($Uninstall) {
    if ((Test-Path -LiteralPath $Dir) -and -not (IsClone $Dir)) { NotAClone }
    $settingsScript = Join-Path $Dir 'scripts\squad_settings.py'
    $manifest = Join-Path $Dir 'hooks\manifest.json'
    if ((Test-Path -LiteralPath $settingsScript) -and (Test-Path -LiteralPath $manifest)) {
      Py $settingsScript uninstall --config $Claude --manifest $manifest
      if ($LASTEXITCODE -ne 0) { Die "settings.json was left as it was (see above); nothing else was removed" }
    } else {
      Warn "no installer files in $Dir, so the hook entries in $Claude\settings.json were left: remove the squad-*.py entries by hand, or set SQUAD_HOME to the clone"
    }
    $installer = Join-Path $Dir 'install.ps1'
    if (Test-Path -LiteralPath $installer) {
      & $installer -ConfigDir $Claude -Uninstall
      if ($LASTEXITCODE -ne 0) { Die "the hooks are out of settings.json but install.ps1 -Uninstall failed (exit $LASTEXITCODE, see above): the links are still there, and the clone was kept" }
    }
    if ($Purge -and (Test-Path -LiteralPath $Dir)) {
      if (-not (IsClone $Dir)) { NotAClone }
      if ((GitIn status --porcelain | Out-String).Trim()) {
        Die "$Dir has local changes: not deleting it. Save what you need, then delete it by hand"
      }
      Remove-Item -LiteralPath $Dir -Recurse -Force
      Say "removed $Dir"
    }
    Say ""
    Say "agenfk-squad uninstalled."
    if ((-not $Purge) -and (Test-Path -LiteralPath $Dir)) { Say "The clone is still in $Dir (add -Purge to delete it)." }
    Say "Sessions already open keep the old hooks until they restart: open a new Claude Code session."
    return
  }

  # ---------------------------------------------------------------- clone or update
  if ((Test-Path -LiteralPath $Dir) -and -not (Test-Path -LiteralPath $Dir -PathType Container)) {
    Die "$Dir exists and is not a directory. Move it, or set SQUAD_HOME to another place"
  }
  if (Test-Path -LiteralPath (Join-Path $Dir '.git')) {
    if (-not (IsClone $Dir)) { NotAClone }
    $changes = (GitIn status --porcelain | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { Die "$Dir is not a usable git clone" }
    if ($changes) {
      [Console]::Error.WriteLine($changes)
      Die "$Dir has local changes (above). The installer never overwrites them: commit or stash them (git -C `"$Dir`" stash), or move the clone away, then run this again. Nothing was changed."
    }
    Say "updating $Dir"
    GitIn fetch --quiet --tags origin
    if ($LASTEXITCODE -ne 0) { Die "could not fetch from origin (git's message is above)" }
  } elseif ((Test-Path -LiteralPath $Dir) -and (@(Get-ChildItem -LiteralPath $Dir -Force).Count -gt 0)) {
    Die "$Dir exists, is not empty and is not a git clone. Move it, or set SQUAD_HOME to another place"
  } else {
    Say "cloning $Repo into $Dir"
    New-Item -ItemType Directory -Force -Path (Split-Path $Dir) | Out-Null
    & git clone --quiet -- $Repo $Dir      # `--`: a SQUAD_REPO that starts with a dash is a path, never an option
    if ($LASTEXITCODE -ne 0) { Die "could not clone $Repo (git's message is above)" }
    GitIn fetch --quiet --tags origin
    if ($LASTEXITCODE -ne 0) { Die "cloned, but could not fetch the tags from origin (git's message is above)" }
  }

  function CommitOf([string]$name) {
    $spec = $name + '^{commit}'
    $c = (GitIn rev-parse --quiet --verify $spec 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { return '' }
    return $c
  }

  $commit = ''
  if ($RefName) {
    $commit = CommitOf "refs/remotes/origin/$RefName"
    if (-not $commit) { $commit = CommitOf "refs/tags/$RefName" }
    if (-not $commit -and -not $RefName.StartsWith('-')) { $commit = CommitOf $RefName }
    if (-not $commit) { Die "'$RefName' is not a branch, tag or commit of the repository" }
    $label = "ref $RefName"
  } elseif ($Channel -eq 'beta') {
    $commit = CommitOf 'refs/remotes/origin/beta'
    if (-not $commit) { Die "the repository has no beta branch" }
    $label = 'beta'
  } else {
    if (-not (CommitOf 'refs/remotes/origin/main')) { Die "the repository has no main branch" }
    # releases only: vX.Y.Z, so a pre-release such as v1.0.0-rc2 is not "stable"
    $tag = @(GitIn tag --list 'v*' --merged refs/remotes/origin/main --sort=-v:refname 2>$null | Where-Object { $_ -match '^v[0-9]+\.[0-9]+\.[0-9]+$' })
    if ($tag.Count -gt 0) {
      $commit = CommitOf "refs/tags/$($tag[0])"
      $label = "stable ($($tag[0]))"
    } else {
      $commit = CommitOf 'refs/remotes/origin/main'
      $label = 'stable (main: no release tag yet)'
    }
  }

  foreach ($f in @('install.ps1', 'scripts/squad_settings.py', 'hooks/manifest.json')) {
    $spec = "${commit}:$f"
    GitIn cat-file -e $spec 2>$null
    if ($LASTEXITCODE -ne 0) { Die "$label predates this installer (it has no $f). Choose a newer one, or install by hand: docs/installation.md" }
  }
  GitIn -c advice.detachedHead=false checkout --quiet --detach $commit
  if ($LASTEXITCODE -ne 0) { Die "could not check out $label (git's message is above). Nothing was installed" }
  $version = (GitIn describe --tags --always $commit | Out-String).Trim()

  # ---------------------------------------------------------------- install
  # settings.json first: if it cannot be edited, nothing gets linked either.
  Py (Join-Path $Dir 'scripts\squad_settings.py') check --config $Claude
  if ($LASTEXITCODE -ne 0) { Die "nothing was installed: fix settings.json, then run this again" }

  & (Join-Path $Dir 'install.ps1') -ConfigDir $Claude
  $linksRc = $LASTEXITCODE
  if ($linksRc -gt 1) { Die "install.ps1 failed (exit $linksRc, see above): nothing was registered in settings.json" }

  Say ""
  Py (Join-Path $Dir 'scripts\squad_settings.py') install --config $Claude --manifest (Join-Path $Dir 'hooks\manifest.json')
  if ($LASTEXITCODE -ne 0) { Die "the links are in place but the hooks were not registered (see above)" }

  Say ""
  Say "agenfk-squad installed"
  Say "  channel  $label"
  Say "  version  $version"
  Say "  clone    $Dir"
  Say "  config   $Claude"
  $bin = Join-Path $UserHome '.local\bin'
  if (-not (($env:PATH -split ';') | Where-Object { $_.TrimEnd('\') -eq $bin })) {
    Warn "$bin is not on PATH: add it, so that 'squad-turn' can be called by name"
  }
  Say ""
  Say "Next: open a NEW Claude Code session. Agents, skills and hooks are read when a session starts."
  Say "Update: run the same command again. Remove: & ([scriptblock]::Create((irm $GetUrl))) -Uninstall"
  if ($linksRc -ne 0) {
    Warn "install.ps1 skipped some links (SKIPPED above): a real file was in the way. See docs/installation.md, 'If you already have a ~/.claude/CLAUDE.md'"
    $State.Exit = 1
  }
}

$squadState = @{ Exit = 0 }
try {
  Invoke-SquadGet -State $squadState -Stable $Stable.IsPresent -Beta $Beta.IsPresent -Ref $Ref -Uninstall $Uninstall.IsPresent `
    -Purge $Purge.IsPresent -Help $Help.IsPresent -Rest $Rest
} catch {
  [Console]::Error.WriteLine("ERROR   " + $_.Exception.Message)
  $squadState.Exit = 1
}
Remove-Item Function:\Invoke-SquadGet -ErrorAction SilentlyContinue
$squadExit = $squadState.Exit
Remove-Variable squadState -ErrorAction SilentlyContinue
if ($PSCommandPath) { exit $squadExit }   # run as a file: the exit code is the result; in your session, the prompt comes back
Remove-Variable squadExit -ErrorAction SilentlyContinue
