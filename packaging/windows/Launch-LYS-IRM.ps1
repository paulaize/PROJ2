[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$DistroName = "Ubuntu"
$LinuxUser = "lysirm"
$PythonExecutable = "/opt/lys-irm/env/bin/python"
$IconPath = "/opt/lys-irm/share/lys-irm.ico"
$WindowsInstallDirectory = Join-Path $env:LOCALAPPDATA "LYS IRM"
$LogPath = Join-Path $WindowsInstallDirectory "launcher.log"

try {
    New-Item -ItemType Directory -Path $WindowsInstallDirectory -Force | Out-Null
    "[$(Get-Date -Format o)] Starting LYS IRM." | Set-Content -LiteralPath $LogPath
    $arguments = @(
        "--distribution", $DistroName,
        "--user", $LinuxUser,
        "--exec",
        "/usr/bin/env",
        "LYS_IRM_ICON=$IconPath",
        "ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS=2",
        "OMP_NUM_THREADS=2",
        "MKL_NUM_THREADS=2",
        $PythonExecutable,
        "-m", "lys_bbb_app"
    )
    & wsl.exe @arguments *>> $LogPath
    if ($LASTEXITCODE -ne 0) {
        throw "LYS IRM s'est arrete avec le code $LASTEXITCODE."
    }
}
catch {
    Add-Type -AssemblyName PresentationFramework
    $message = "$($_.Exception.Message)`n`nJournal: $LogPath"
    [System.Windows.MessageBox]::Show(
        $message,
        "LYS IRM - erreur de demarrage",
        [System.Windows.MessageBoxButton]::OK,
        [System.Windows.MessageBoxImage]::Error
    ) | Out-Null
    exit 1
}
