[CmdletBinding()]
param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "LYS-IRM"),
    [switch]$Unattended,
    [switch]$NoShortcuts
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$transcriptStarted = $false
$exitCode = 1
$releaseDirectory = $null

function Write-Step {
    param([string]$Message)
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Test-BundleIntegrity {
    $root = [IO.Path]::GetFullPath($PSScriptRoot) + [IO.Path]::DirectorySeparatorChar
    foreach ($line in Get-Content -LiteralPath (Join-Path $PSScriptRoot "SHA256SUMS.txt")) {
        if (-not $line.Trim()) { continue }
        if ($line -notmatch "^([0-9a-fA-F]{64})  (.+)$") {
            throw "Ligne de controle invalide: $line"
        }
        $expected = $Matches[1]
        $target = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot $Matches[2]))
        if (-not $target.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Chemin de paquet invalide: $target"
        }
        if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $expected) {
            throw "Le controle d'integrite a echoue: $target. Telechargez a nouveau le ZIP."
        }
    }
}

function New-LysShortcut {
    param([string]$Path)
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($Path)
    $shortcut.TargetPath = Join-Path $PSHOME "powershell.exe"
    $launcher = Join-Path $InstallRoot "Launch-LYS-IRM.ps1"
    $shortcut.Arguments = "-NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcher`""
    $shortcut.WorkingDirectory = $InstallRoot
    $shortcut.IconLocation = "$(Join-Path $InstallRoot 'lys-irm.ico'),0"
    $shortcut.Description = "LYS IRM - modeles T2"
    $shortcut.Save()
}

try {
    $InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
    $logDirectory = Join-Path $InstallRoot "logs"
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $logPath = Join-Path $logDirectory ("setup-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")
    Start-Transcript -LiteralPath $logPath -Force | Out-Null
    $transcriptStarted = $true
    Write-Step "Verification du paquet Windows T2 hors ligne"
    if (-not [Environment]::Is64BitProcess -or $env:PROCESSOR_ARCHITECTURE -ne "AMD64") {
        throw "Utilisez Windows x86-64 et PowerShell 64 bits."
    }
    Test-BundleIntegrity
    $manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot "handoff-manifest.json") -Raw | ConvertFrom-Json
    if ($manifest.target.feature_profile -ne "t2-only" -or $manifest.target.delivery -ne "offline") {
        throw "Ce paquet n'est pas une distribution Windows T2 hors ligne complete."
    }
    $runtimeArchive = Join-Path $PSScriptRoot "runtime\windows-runtime.zip"
    $runtimeManifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot "runtime\runtime-manifest.json") -Raw | ConvertFrom-Json
    if ($runtimeManifest.platform -ne "win-64" -or $runtimeManifest.relocation_test -ne "passed") {
        throw "Le runtime Windows n'a pas passe sa validation."
    }
    if ((Get-FileHash -LiteralPath $runtimeArchive -Algorithm SHA256).Hash -ne $runtimeManifest.archive_sha256) {
        throw "Le runtime Windows est incomplet ou corrompu."
    }
    $drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($InstallRoot))
    if ($drive.AvailableFreeSpace -lt 8GB) {
        throw "Au moins 8 Gio libres sont necessaires sur le disque d'installation."
    }

    # Each install has its own final prefix. Never update the colleague's pip/conda
    # environment in place, and never move a prefix after conda-unpack.
    $releaseId = [guid]::NewGuid().ToString("N").Substring(0, 12)
    $releaseDirectory = Join-Path $InstallRoot "releases\$releaseId"
    $environmentDirectory = Join-Path $releaseDirectory "env"
    $applicationDirectory = Join-Path $releaseDirectory "app"
    $modelDirectory = Join-Path $releaseDirectory "models"
    New-Item -ItemType Directory -Path $environmentDirectory -Force | Out-Null
    Write-Step "Extraction du runtime inclus (aucun telechargement)"
    & (Join-Path $env:SystemRoot "System32\tar.exe") -xf $runtimeArchive -C $environmentDirectory
    if ($LASTEXITCODE -ne 0) { throw "L'extraction du runtime a echoue: $LASTEXITCODE" }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "app") -Destination $applicationDirectory -Recurse
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "models") -Destination $modelDirectory -Recurse
    $python = Join-Path $environmentDirectory "python.exe"
    $env:PATH = "$environmentDirectory;$(Join-Path $environmentDirectory 'Library\bin');$env:PATH"
    $env:PYTHONPATH = Join-Path $applicationDirectory "src"
    $env:PYTHONHOME = $environmentDirectory
    $env:PYTHONNOUSERSITE = "1"
    $env:LYS_IRM_FEATURE_PROFILE = "t2-only"
    $env:LYS_IRM_MODELS_DIRECTORY = $modelDirectory
    $env:QT_QPA_PLATFORM = "offscreen"
    $env:QT_QPA_FONTDIR = Join-Path $env:WINDIR "Fonts"
    $env:ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS = "2"
    $env:OMP_NUM_THREADS = "2"
    $env:MKL_NUM_THREADS = "2"
    & $python (Join-Path $environmentDirectory "Scripts\conda-unpack-script.py")
    if ($LASTEXITCODE -ne 0) { throw "La configuration des chemins du runtime a echoue." }

    Write-Step "Verification des modeles inclus, du runtime et du demarrage T2"
    & $python -m lys_bbb_app.windows_smoke --models-directory $modelDirectory
    if ($LASTEXITCODE -ne 0) { throw "Le test de demarrage T2 a echoue: code $LASTEXITCODE. Consultez $logPath" }

    # Publish the selected install only after every required validation passes.
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "Launch-LYS-IRM.ps1") -Destination $InstallRoot -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "lys-irm.ico") -Destination $InstallRoot -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "handoff-manifest.json") -Destination $releaseDirectory
    $active = @{ schema_version = 1; release_id = $releaseId; feature_profile = "t2-only" }
    $activePath = Join-Path $InstallRoot "active-install.json"
    $stagedActive = Join-Path $InstallRoot "active-install.new.json"
    $active | ConvertTo-Json | Set-Content -LiteralPath $stagedActive -Encoding UTF8
    if (Test-Path -LiteralPath $activePath) {
        Copy-Item -LiteralPath $activePath -Destination (Join-Path $InstallRoot "active-install.previous.json") -Force
    }
    Move-Item -LiteralPath $stagedActive -Destination $activePath -Force
    if (-not $NoShortcuts) {
        Write-Step "Creation des raccourcis"
        New-LysShortcut (Join-Path ([Environment]::GetFolderPath("Desktop")) "LYS IRM.lnk")
        New-LysShortcut (Join-Path ([Environment]::GetFolderPath("Programs")) "LYS IRM.lnk")
    }
    Write-Host "`nLYS IRM est pret. Modeles T2 uniquement; aucun modele T1 installe." -ForegroundColor Green
    Write-Host "Journal: $logPath"
    Write-Host "ITK-SNAP est facultatif et peut etre installe separement pour l'edition manuelle."
    if (-not $Unattended) {
        Add-Type -AssemblyName PresentationFramework
        [System.Windows.MessageBox]::Show("Installation terminee. Lancez LYS IRM depuis le Bureau.", "LYS IRM") | Out-Null
    }
    $exitCode = 0
}
catch {
    Write-Host "`nERREUR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Journal disponible dans: $(Join-Path $InstallRoot 'logs')"
    Write-Host "Les donnees d'etude et les installations precedentes sont conservees."
}
finally {
    if ($transcriptStarted) { Stop-Transcript | Out-Null }
}
exit $exitCode
