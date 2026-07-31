[CmdletBinding()]
param(
    [switch]$SkipT1ModelDownload,
    [switch]$SkipITKSnapInstall
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$InstallRoot = Join-Path $env:LOCALAPPDATA "LYS IRM"
$MiniforgeDirectory = Join-Path $InstallRoot "miniforge"
$EnvironmentDirectory = Join-Path $InstallRoot "env"
$ApplicationDirectory = Join-Path $InstallRoot "app"
$LogDirectory = Join-Path $InstallRoot "logs"
$MinimumFreeSpaceGiB = 8
$FeatureProfile = "full"
$EnvironmentFileName = "environment-win64.yml"
$ShortcutName = "LYS IRM"
$ShortcutDescription = "LYS IRM - native Windows with ANTsPyx"
$AntsPyxWheelName = "antspyx-0.6.3-cp311-cp311-win_amd64.whl"
$AntsPyxWheelSha256 = (
    "39a29ba5abbf3475dea70cf0d0a2472e34a5c854f99d2f08204a288f1f5aeac4"
)

$MiniforgeVersion = "26.1.1-3"
$MiniforgeInstallerName = "Miniforge3-$MiniforgeVersion-Windows-x86_64.exe"
$MiniforgeUri = (
    "https://github.com/conda-forge/miniforge/releases/download/" +
    "$MiniforgeVersion/$MiniforgeInstallerName"
)
$MiniforgeSha256 = "4d987034d25684fbed0fe7c691227067e37f7443061e2732c3b726c0c5dd45c2"

$ITKSnapInstallerName = "itksnap-4.4.0-20250909-win64-AMD64.exe"
$ITKSnapUri = (
    "https://downloads.sourceforge.net/project/itk-snap/itk-snap/4.4.0/" +
    $ITKSnapInstallerName
)
$ITKSnapSha256 = "4ccbb2d53e57d70edee3772d0ec02ff843ec6afa95fd0b5f00e49ba90fa624a0"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Show-Information {
    param(
        [string]$Title,
        [string]$Message
    )
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show(
        $Message,
        $Title,
        [System.Windows.MessageBoxButton]::OK,
        [System.Windows.MessageBoxImage]::Information
    ) | Out-Null
}

function Test-BundleIntegrity {
    $checksumFile = Join-Path $PSScriptRoot "SHA256SUMS.txt"
    if (-not (Test-Path -LiteralPath $checksumFile -PathType Leaf)) {
        throw "Le fichier de controle SHA256SUMS.txt est absent."
    }
    foreach ($line in Get-Content -LiteralPath $checksumFile) {
        if (-not $line.Trim()) {
            continue
        }
        if ($line -notmatch "^([0-9a-fA-F]{64})  (.+)$") {
            throw "Ligne de controle invalide: $line"
        }
        $expected = $Matches[1].ToUpperInvariant()
        $relative = $Matches[2].Replace("/", [IO.Path]::DirectorySeparatorChar)
        $target = Join-Path $PSScriptRoot $relative
        if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
            throw "Fichier du paquet absent: $relative"
        }
        $actual = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
        if ($actual -ne $expected) {
            throw "Le controle d'integrite a echoue pour $relative."
        }
    }
}

function Get-VerifiedDownload {
    param(
        [string]$Uri,
        [string]$Destination,
        [string]$ExpectedSha256
    )
    Invoke-WebRequest -Uri $Uri -OutFile $Destination -UseBasicParsing
    $actual = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash
    if ($actual -ne $ExpectedSha256.ToUpperInvariant()) {
        throw "Le controle SHA256 du telechargement a echoue: $Destination"
    }
}

function Find-ITKSnap {
    $candidates = @(
        (Join-Path $env:ProgramFiles "ITK-SNAP 4.4\bin\ITK-SNAP.exe"),
        (Join-Path $env:ProgramFiles "ITK-SNAP 4.4\ITK-SNAP.exe"),
        (Join-Path $env:ProgramFiles "ITK-SNAP\bin\ITK-SNAP.exe"),
        (Join-Path $env:ProgramFiles "ITK-SNAP\ITK-SNAP.exe")
    )
    return $candidates |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
        Select-Object -First 1
}

function New-LysShortcut {
    param([string]$ShortcutPath)

    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $powerShell = Join-Path $PSHOME "powershell.exe"
    $launcher = Join-Path $InstallRoot "Launch-LYS-IRM.ps1"
    $icon = Join-Path $InstallRoot "lys-irm.ico"
    $shortcut.TargetPath = $powerShell
    $shortcut.Arguments = (
        "-NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden " +
        "-File `"$launcher`""
    )
    $shortcut.WorkingDirectory = $InstallRoot
    $shortcut.IconLocation = "$icon,0"
    $shortcut.Description = $ShortcutDescription
    $shortcut.Save()
}

function Test-ModelRelease {
    param(
        [string]$Python,
        [string]$ReleasePath,
        [ValidateSet("T1", "T2")]
        [string]$Kind
    )

    if ($Kind -eq "T1") {
        $validation = (
            "import sys; from pathlib import Path; " +
            "from lys_bbb.t1_brain_mask_release import " +
            "validate_t1_brain_mask_release as validate; " +
            "validate(Path(sys.argv[1]))"
        )
    }
    else {
        $validation = (
            "import sys; from pathlib import Path; " +
            "from lys_bbb.t2_model_release import " +
            "validate_t2_model_release as validate; " +
            "validate(Path(sys.argv[1]))"
        )
    }
    & $Python -c $validation $ReleasePath
    return ($LASTEXITCODE -eq 0)
}

function Install-BundledModelRelease {
    param(
        [string]$Python,
        [string]$Source,
        [string]$Destination,
        [ValidateSet("T1", "T2")]
        [string]$Kind,
        [string[]]$IdentityFiles
    )

    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
        return $false
    }
    $sameRelease = Test-Path -LiteralPath $Destination -PathType Container
    if ($sameRelease) {
        foreach ($relative in $IdentityFiles) {
            $bundledFile = Join-Path $Source $relative
            $installedFile = Join-Path $Destination $relative
            if (-not (Test-Path -LiteralPath $installedFile -PathType Leaf)) {
                $sameRelease = $false
                break
            }
            $bundledHash = (
                Get-FileHash -LiteralPath $bundledFile -Algorithm SHA256
            ).Hash
            $installedHash = (
                Get-FileHash -LiteralPath $installedFile -Algorithm SHA256
            ).Hash
            if ($bundledHash -ne $installedHash) {
                $sameRelease = $false
                break
            }
        }
    }
    if (
        $sameRelease -and
        (Test-ModelRelease `
            -Python $Python `
            -ReleasePath $Destination `
            -Kind $Kind)
    ) {
        return $true
    }

    $parent = Split-Path $Destination -Parent
    $name = Split-Path $Destination -Leaf
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $staged = Join-Path $parent (".$name-new-" + [guid]::NewGuid().ToString("N"))
    try {
        Copy-Item -LiteralPath $Source -Destination $staged -Recurse
        if (
            -not (Test-ModelRelease `
                -Python $Python `
                -ReleasePath $staged `
                -Kind $Kind)
        ) {
            throw "Le modele $Kind inclus n'a pas passe sa validation."
        }
        if (Test-Path -LiteralPath $Destination -PathType Container) {
            $backup = (
                "$Destination.previous." +
                (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
            )
            Move-Item -LiteralPath $Destination -Destination $backup
        }
        Move-Item -LiteralPath $staged -Destination $Destination
        return $true
    }
    finally {
        if (Test-Path -LiteralPath $staged -PathType Container) {
            Remove-Item -LiteralPath $staged -Recurse -Force
        }
    }
}

$TemporaryDirectory = Join-Path (
    [IO.Path]::GetTempPath()
) ("LYS-IRM-Setup-" + [guid]::NewGuid().ToString("N"))
$StagedApplication = $null

try {
    Write-Step "Controle du paquet et de la machine"
    if (-not [Environment]::Is64BitOperatingSystem) {
        throw "LYS IRM requiert Windows 64 bits."
    }
    $architecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
    if ($architecture -ne [System.Runtime.InteropServices.Architecture]::X64) {
        throw "Ce paquet requiert un processeur Intel/AMD x86-64: $architecture."
    }
    Test-BundleIntegrity
    $manifestPath = Join-Path $PSScriptRoot "handoff-manifest.json"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "Le manifeste du paquet est absent."
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw |
        ConvertFrom-Json
    $FeatureProfile = [string]$manifest.target.feature_profile
    if ($FeatureProfile -ne "full") {
        throw "Profil Windows natif non pris en charge: $FeatureProfile"
    }

    $systemDrive = Get-CimInstance `
        Win32_LogicalDisk `
        -Filter "DeviceID='$($env:SystemDrive)'"
    $freeSpaceGiB = [math]::Round($systemDrive.FreeSpace / 1GB, 1)
    if ($freeSpaceGiB -lt $MinimumFreeSpaceGiB) {
        throw (
            "Espace insuffisant: $freeSpaceGiB Gio libres; " +
            "$MinimumFreeSpaceGiB Gio requis."
        )
    }
    $memory = Get-CimInstance Win32_ComputerSystem
    $memoryGiB = [math]::Round($memory.TotalPhysicalMemory / 1GB, 1)
    if ($memoryGiB -lt 7) {
        Write-Warning (
            "Seulement $memoryGiB Gio de RAM detectes. " +
            "Les traitements ML seront limites."
        )
    }

    New-Item -ItemType Directory -Path $TemporaryDirectory -Force | Out-Null
    New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null

    $conda = Join-Path $MiniforgeDirectory "Scripts\conda.exe"
    if (-not (Test-Path -LiteralPath $conda -PathType Leaf)) {
        Write-Step "Installation de Miniforge pour Windows"
        $miniforgeInstaller = Join-Path $TemporaryDirectory $MiniforgeInstallerName
        Get-VerifiedDownload `
            -Uri $MiniforgeUri `
            -Destination $miniforgeInstaller `
            -ExpectedSha256 $MiniforgeSha256
        $arguments = @(
            "/InstallationType=JustMe",
            "/RegisterPython=0",
            "/S",
            "/D=$MiniforgeDirectory"
        )
        $process = Start-Process `
            -FilePath $miniforgeInstaller `
            -ArgumentList $arguments `
            -Wait `
            -PassThru
        if ($process.ExitCode -ne 0) {
            throw "Miniforge n'a pas pu etre installe: code $($process.ExitCode)."
        }
    }
    if (-not (Test-Path -LiteralPath $conda -PathType Leaf)) {
        throw "Miniforge est termine mais conda.exe est absent."
    }

    Write-Step "Installation des dependances Windows natives"
    Write-Host "Cette etape telecharge plusieurs Gio et peut durer 15 a 40 minutes."
    $StagedApplication = Join-Path (
        Split-Path $ApplicationDirectory -Parent
    ) ("app-new-" + [guid]::NewGuid().ToString("N"))
    Copy-Item `
        -LiteralPath (Join-Path $PSScriptRoot "app") `
        -Destination $StagedApplication `
        -Recurse
    $environmentFile = Join-Path (
        $StagedApplication
    ) "packaging\windows-native\$EnvironmentFileName"
    if (-not (Test-Path -LiteralPath $environmentFile -PathType Leaf)) {
        throw "Le fichier d'environnement Windows est absent."
    }
    if (Test-Path -LiteralPath (
        Join-Path $EnvironmentDirectory "python.exe"
    ) -PathType Leaf) {
        & $conda env update `
            --prefix $EnvironmentDirectory `
            --file $environmentFile `
            --prune
    }
    else {
        & $conda env create `
            --prefix $EnvironmentDirectory `
            --file $environmentFile
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Conda n'a pas pu installer les dependances: code $LASTEXITCODE."
    }

    $python = Join-Path $EnvironmentDirectory "python.exe"
    $env:PATH = (
        "$EnvironmentDirectory;" +
        (Join-Path $EnvironmentDirectory "Library\bin") +
        ";$env:PATH"
    )
    Write-Step "Telechargement et verification de la roue ANTsPyx Windows"
    $wheelDirectory = Join-Path $TemporaryDirectory "antspyx-wheel"
    New-Item -ItemType Directory -Path $wheelDirectory -Force | Out-Null
    & $python -m pip download `
        --dest $wheelDirectory `
        --only-binary=:all: `
        --no-deps `
        "antspyx==0.6.3"
    if ($LASTEXITCODE -ne 0) {
        throw "La roue ANTsPyx Windows n'a pas pu etre telechargee."
    }
    $wheelPath = Join-Path $wheelDirectory $AntsPyxWheelName
    if (-not (Test-Path -LiteralPath $wheelPath -PathType Leaf)) {
        throw "La roue ANTsPyx attendue est absente: $AntsPyxWheelName"
    }
    $wheelHash = (
        Get-FileHash -LiteralPath $wheelPath -Algorithm SHA256
    ).Hash
    if ($wheelHash -ne $AntsPyxWheelSha256.ToUpperInvariant()) {
        throw "Le controle SHA256 de la roue ANTsPyx a echoue."
    }
    & $python -m pip install --no-deps $wheelPath
    if ($LASTEXITCODE -ne 0) {
        throw "ANTsPyx n'a pas pu etre installe: code $LASTEXITCODE."
    }

    $backupApplication = $null
    if (Test-Path -LiteralPath $ApplicationDirectory -PathType Container) {
        $backupApplication = (
            "$ApplicationDirectory.previous." +
            (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
        )
        Move-Item -LiteralPath $ApplicationDirectory -Destination $backupApplication
    }
    Move-Item -LiteralPath $StagedApplication -Destination $ApplicationDirectory
    $StagedApplication = $null

    & $python -m pip install --no-deps --editable $ApplicationDirectory
    if ($LASTEXITCODE -ne 0) {
        $failedApplication = (
            "$ApplicationDirectory.failed." +
            (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
        )
        Move-Item -LiteralPath $ApplicationDirectory -Destination $failedApplication
        if ($backupApplication) {
            Move-Item `
                -LiteralPath $backupApplication `
                -Destination $ApplicationDirectory
        }
        throw "L'application n'a pas pu etre installee: code $LASTEXITCODE."
    }

    $modelInstallRoot = Join-Path $InstallRoot "models"
    $bundledModelRoot = Join-Path $PSScriptRoot "models"
    $t1ModelDirectory = Join-Path $modelInstallRoot "rs2net-m-seam-v1"
    $bundledT1Model = Join-Path $bundledModelRoot "rs2net-m-seam-v1"
    if (Test-Path -LiteralPath $bundledT1Model -PathType Container) {
        Write-Step "Installation du modele T1 inclus et verifie"
        Install-BundledModelRelease `
            -Python $python `
            -Source $bundledT1Model `
            -Destination $t1ModelDirectory `
            -Kind "T1" `
            -IdentityFiles @("release.json") | Out-Null
    }
    elseif (-not $SkipT1ModelDownload) {
        Write-Step "Telechargement du modele T1 examine"
        if (-not (Test-Path -LiteralPath $t1ModelDirectory -PathType Container)) {
            & $python `
                -m lys_bbb.t1_brain_mask_setup_cli `
                --destination $t1ModelDirectory
            if ($LASTEXITCODE -ne 0) {
                Write-Warning (
                    "Le modele T1 n'a pas pu etre telecharge. " +
                    "L'application reste utilisable; consultez le journal."
                )
            }
        }
    }

    $bundledT2Standard = Join-Path $bundledModelRoot "lys_v3_standard3d_nnunet"
    if (Test-Path -LiteralPath $bundledT2Standard -PathType Container) {
        Write-Step "Installation du modele T2 LYS v3 fold 1 et de l'ensemble fold 0+1"
        Install-BundledModelRelease `
            -Python $python `
            -Source $bundledT2Standard `
            -Destination (
                Join-Path $modelInstallRoot "lys_v3_standard3d_nnunet"
            ) `
            -Kind "T2" `
            -IdentityFiles @(
                "model_metadata.json",
                "SHA256SUMS",
                "dataset.json",
                "plans.json"
            ) | Out-Null
    }
    else {
        Write-Warning (
            "Le modele T2 LYS v3 fold 1 par defaut n'est pas inclus."
        )
    }

    $bundledT2Small = Join-Path $bundledModelRoot "lys_v1_small_ratlesnetv2"
    if (Test-Path -LiteralPath $bundledT2Small -PathType Container) {
        Write-Step "Installation du petit modele T2 historique"
        Install-BundledModelRelease `
            -Python $python `
            -Source $bundledT2Small `
            -Destination (
                Join-Path $modelInstallRoot "lys_v1_small_ratlesnetv2"
            ) `
            -Kind "T2" `
            -IdentityFiles @(
                "bundle_manifest.json",
                "frozen_spec.json",
                "selected_threshold.json",
                "SHA256SUMS"
            ) | Out-Null
    }

    if (-not $SkipITKSnapInstall -and -not (Find-ITKSnap)) {
        Write-Step "Installation facultative d'ITK-SNAP 4.4"
        Write-Host (
            "Windows demandera une autorisation administrateur uniquement " +
            "pour installer l'editeur ITK-SNAP."
        )
        try {
            $itkSnapInstaller = Join-Path $TemporaryDirectory $ITKSnapInstallerName
            Get-VerifiedDownload `
                -Uri $ITKSnapUri `
                -Destination $itkSnapInstaller `
                -ExpectedSha256 $ITKSnapSha256
            $process = Start-Process `
                -FilePath $itkSnapInstaller `
                -ArgumentList @("/S") `
                -Verb RunAs `
                -Wait `
                -PassThru
            if ($process.ExitCode -ne 0) {
                throw "Code d'installation ITK-SNAP: $($process.ExitCode)."
            }
        }
        catch {
            Write-Warning (
                "ITK-SNAP n'a pas ete installe. L'application fonctionnera, " +
                "mais l'edition manuelle externe restera indisponible. " +
                "Detail: $($_.Exception.Message)"
            )
        }
    }

    Write-Step "Test de demarrage natif avec ANTsPyx"
    $smokeScript = (
        "import ants, scipy, SimpleITK, torch, statsmodels; " +
        "import sklearn, yaml, webcolors, PIL, requests; " +
        "assert ants.__version__ == '0.6.3'; " +
        "assert scipy.__version__ == '1.15.2'; " +
        "from PySide6.QtWidgets import QApplication; " +
        "from lys_bbb_app.features import active_features; " +
        "from lys_bbb_app.ui.main_window import MainWindow; " +
        "app=QApplication([]); features=active_features(); " +
        "window=MainWindow(features=features); " +
        "assert features.atlas_mapping; " +
        "assert features.ants_backend == 'antspyx'; " +
        "assert window.workspace_page.atlas_mapping_panel is not None; " +
        "window.close()"
    )
    $previousProfile = $env:LYS_IRM_FEATURE_PROFILE
    $previousQtPlatform = $env:QT_QPA_PLATFORM
    try {
        $env:LYS_IRM_FEATURE_PROFILE = $FeatureProfile
        $env:QT_QPA_PLATFORM = "offscreen"
        & $python -c $smokeScript
        if ($LASTEXITCODE -ne 0) {
            throw "Le test de demarrage natif a echoue: code $LASTEXITCODE."
        }
    }
    finally {
        $env:LYS_IRM_FEATURE_PROFILE = $previousProfile
        $env:QT_QPA_PLATFORM = $previousQtPlatform
    }

    Write-Step "Creation de l'icone Windows"
    Copy-Item `
        -LiteralPath (Join-Path $PSScriptRoot "Launch-LYS-IRM.ps1") `
        -Destination $InstallRoot `
        -Force
    Copy-Item `
        -LiteralPath (Join-Path $PSScriptRoot "lys-irm.ico") `
        -Destination $InstallRoot `
        -Force
    Copy-Item `
        -LiteralPath (Join-Path $PSScriptRoot "handoff-manifest.json") `
        -Destination $InstallRoot `
        -Force

    $desktopShortcut = Join-Path (
        [Environment]::GetFolderPath("Desktop")
    ) "$ShortcutName.lnk"
    foreach ($legacyName in @(
        "MRI Tool.lnk",
        "LYS BBB.lnk",
        "LYS BBB - test Windows.lnk",
        "LYS BBB - apercu ANTsPyx.lnk"
    )) {
        Remove-Item `
            -LiteralPath (Join-Path (
                [Environment]::GetFolderPath("Desktop")
            ) $legacyName) `
            -Force `
            -ErrorAction SilentlyContinue
        Remove-Item `
            -LiteralPath (Join-Path (
                [Environment]::GetFolderPath("Programs")
            ) $legacyName) `
            -Force `
            -ErrorAction SilentlyContinue
    }
    New-LysShortcut -ShortcutPath $desktopShortcut
    $programs = [Environment]::GetFolderPath("Programs")
    New-LysShortcut `
        -ShortcutPath (Join-Path $programs "$ShortcutName.lnk")

    Write-Host ""
    Write-Host "Installation native terminee." -ForegroundColor Green
    Write-Host "Aucun composant Ubuntu ou WSL2 n'a ete installe."
    $completionMessage = (
        "L'installation native ANTsPyx est terminee.`n`n" +
        "Utilisez l'icone '$ShortcutName' du Bureau.`n" +
        "Les registrations doivent toujours etre examinees dans leurs panneaux QC."
    )
    Show-Information `
        -Title "LYS IRM est pret" `
        -Message $completionMessage
    exit 0
}
catch {
    Write-Host ""
    Write-Host "ERREUR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    if (
        $StagedApplication -and
        (Test-Path -LiteralPath $StagedApplication -PathType Container)
    ) {
        Remove-Item -LiteralPath $StagedApplication -Recurse -Force
    }
    if (Test-Path -LiteralPath $TemporaryDirectory -PathType Container) {
        Remove-Item -LiteralPath $TemporaryDirectory -Recurse -Force
    }
}
