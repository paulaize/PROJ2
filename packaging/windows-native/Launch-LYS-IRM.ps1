[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$InstallRoot = $PSScriptRoot
$logDirectory = Join-Path $InstallRoot "logs"
$outputLog = Join-Path $logDirectory "launcher-output.log"
$errorLog = Join-Path $logDirectory "launcher-error.log"
try {
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $active = Get-Content -LiteralPath (Join-Path $InstallRoot "active-install.json") -Raw | ConvertFrom-Json
    if ($active.feature_profile -ne "t2-only" -or $active.release_id -notmatch '^[0-9a-f]{12}$') {
        throw "Installation non reconnue. Relancez Setup-LYS-IRM.cmd."
    }
    $release = Join-Path $InstallRoot "releases\$($active.release_id)"
    $runtime = Join-Path $release "env"
    $application = Join-Path $release "app"
    $python = Join-Path $runtime "pythonw.exe"
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Runtime absent. Relancez Setup-LYS-IRM.cmd."
    }
    $env:PATH = "$runtime;$(Join-Path $runtime 'Library\bin');$env:PATH"
    $env:PYTHONPATH = Join-Path $application "src"
    $env:PYTHONHOME = $runtime
    $env:PYTHONNOUSERSITE = "1"
    $env:PYTHONUTF8 = "1"
    $env:LYS_IRM_FEATURE_PROFILE = "t2-only"
    $env:LYS_IRM_MODELS_DIRECTORY = Join-Path $release "models"
    $env:LYS_IRM_ICON = Join-Path $InstallRoot "lys-irm.ico"
    $env:QT_QPA_PLATFORM = "windows"
    $env:QT_QPA_FONTDIR = Join-Path $env:WINDIR "Fonts"
    $env:ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS = "2"
    $env:OMP_NUM_THREADS = "2"
    $env:MKL_NUM_THREADS = "2"
    $process = Start-Process -FilePath $python -ArgumentList @("-m", "lys_bbb_app") `
        -WorkingDirectory $application -RedirectStandardOutput $outputLog `
        -RedirectStandardError $errorLog -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "LYS IRM s'est arrete avec le code $($process.ExitCode)."
    }
}
catch {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show(
        "$($_.Exception.Message)`n`nJournaux:`n$outputLog`n$errorLog",
        "LYS IRM - erreur de demarrage"
    ) | Out-Null
    exit 1
}
