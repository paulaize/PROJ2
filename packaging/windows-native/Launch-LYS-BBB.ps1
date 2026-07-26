[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$InstallRoot = Join-Path $env:LOCALAPPDATA "LYS_BBB"
$ApplicationDirectory = Join-Path $InstallRoot "app"
$Pythonw = Join-Path $InstallRoot "env\pythonw.exe"
$IconPath = Join-Path $InstallRoot "lys-bbb.ico"
$LogDirectory = Join-Path $InstallRoot "logs"
$OutputLog = Join-Path $LogDirectory "launcher-output.log"
$ErrorLog = Join-Path $LogDirectory "launcher-error.log"

try {
    if (-not (Test-Path -LiteralPath $Pythonw -PathType Leaf)) {
        throw "Le runtime LYS BBB est absent. Relancez Setup-LYS-BBB.cmd."
    }
    if (-not (Test-Path -LiteralPath $ApplicationDirectory -PathType Container)) {
        throw "Les fichiers de LYS BBB sont absents. Relancez Setup-LYS-BBB.cmd."
    }

    New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
    "[$(Get-Date -Format o)] Starting native LYS BBB." |
        Set-Content -LiteralPath $OutputLog
    Set-Content -LiteralPath $ErrorLog -Value ""

    $env:LYS_BBB_FEATURE_PROFILE = "windows_native_no_ants_v1"
    $env:LYS_BBB_ICON = $IconPath
    $env:ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS = "2"
    $env:OMP_NUM_THREADS = "2"
    $env:MKL_NUM_THREADS = "2"

    $process = Start-Process `
        -FilePath $Pythonw `
        -ArgumentList @("-m", "lys_bbb_app") `
        -WorkingDirectory $ApplicationDirectory `
        -RedirectStandardOutput $OutputLog `
        -RedirectStandardError $ErrorLog `
        -Wait `
        -PassThru
    if ($process.ExitCode -ne 0) {
        throw "LYS BBB s'est arrete avec le code $($process.ExitCode)."
    }
}
catch {
    Add-Type -AssemblyName PresentationFramework
    $message = (
        "$($_.Exception.Message)`n`n" +
        "Journaux:`n$OutputLog`n$ErrorLog"
    )
    [System.Windows.MessageBox]::Show(
        $message,
        "LYS BBB - erreur de demarrage",
        [System.Windows.MessageBoxButton]::OK,
        [System.Windows.MessageBoxImage]::Error
    ) | Out-Null
    exit 1
}
