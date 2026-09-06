<#
.SYNOPSIS
    Put a book_creator icon on the Desktop (and optionally the Start menu).

.DESCRIPTION
    Creates a shortcut to launch.cmd, which starts the web UI on the best
    interpreter available and opens a browser once it is answering.

    The Desktop folder is asked of Windows rather than assumed to be
    %USERPROFILE%\Desktop: with OneDrive's "Back up your folders" turned on --
    the default on a new Windows 11 machine -- the real Desktop lives under
    OneDrive, and a shortcut written to the other path simply never appears.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install_shortcut.ps1
    powershell -ExecutionPolicy Bypass -File install_shortcut.ps1 -StartMenu
    powershell -ExecutionPolicy Bypass -File install_shortcut.ps1 -Remove
#>
[CmdletBinding()]
param(
    [switch]$StartMenu,
    [switch]$Remove,
    [string]$Name = "book_creator"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = Join-Path $root "launch.cmd"
$icon = Join-Path $root "assets\book_creator.ico"

$targets = @([Environment]::GetFolderPath("Desktop"))
if ($StartMenu) {
    $targets += Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs"
}

if ($Remove) {
    foreach ($dir in $targets) {
        $lnk = Join-Path $dir "$Name.lnk"
        if (Test-Path $lnk) { Remove-Item $lnk -Force; "Removed $lnk" }
        else { "Nothing at $lnk" }
    }
    return
}

if (-not (Test-Path $target)) { throw "launch.cmd is missing from $root" }
if (-not (Test-Path $icon)) {
    Write-Warning "No icon at $icon - run 'python make_icon.py' to draw it. Using the default."
}

$shell = New-Object -ComObject WScript.Shell
foreach ($dir in $targets) {
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    $lnk = Join-Path $dir "$Name.lnk"
    $sc = $shell.CreateShortcut($lnk)
    $sc.TargetPath = $target
    # Without this the app would run from wherever Explorer happened to be,
    # and every relative path it uses (input/, output/, cache/) would be wrong.
    $sc.WorkingDirectory = $root
    $sc.Description = "book_creator - dual-language print-on-demand builder"
    $sc.WindowStyle = 7            # start minimised: the browser is the app
    if (Test-Path $icon) { $sc.IconLocation = $icon }
    $sc.Save()
    "Created $lnk"
}
