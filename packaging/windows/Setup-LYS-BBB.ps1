[CmdletBinding()]
param(
    [switch]$SkipT1ModelDownload
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$DistroName = "Ubuntu"
$WindowsInstallDirectory = Join-Path $env:LOCALAPPDATA "LYS BBB"
$MinimumFreeSpaceGiB = 12
$WslInstallWasRequested = $false

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

function Get-InstalledDistributions {
    $output = & wsl.exe --list --quiet 2>$null
    if ($LASTEXITCODE -ne 0) {
        return @()
    }
    return @($output | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}

function Install-WslIfNeeded {
    $installed = Get-InstalledDistributions
    if ($installed -contains $DistroName) {
        return
    }

    Write-Step "Installation de WSL2 et Ubuntu"
    $script:WslInstallWasRequested = $true
    Write-Host "Windows va demander une autorisation administrateur."
    $arguments = @(
        "--install",
        "--distribution", $DistroName,
        "--no-launch"
    )
    $process = Start-Process -FilePath "wsl.exe" `
        -ArgumentList $arguments `
        -Verb RunAs `
        -Wait `
        -PassThru
    if ($process.ExitCode -ne 0) {
        throw "Windows n'a pas pu installer WSL/Ubuntu (code $($process.ExitCode))."
    }

    $installed = Get-InstalledDistributions
    if ($installed -notcontains $DistroName) {
        Show-Information `
            -Title "Redemarrage requis" `
            -Message ("Windows doit redemarrer pour terminer WSL2.`n`n" +
                "Apres le redemarrage, double-cliquez a nouveau sur Setup-LYS-BBB.cmd.")
        exit 0
    }
}

function New-LysShortcut {
    param([string]$ShortcutPath)

    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $powerShell = Join-Path $PSHOME "powershell.exe"
    $launcher = Join-Path $WindowsInstallDirectory "Launch-LYS-BBB.ps1"
    $icon = Join-Path $WindowsInstallDirectory "lys-bbb.ico"
    $shortcut.TargetPath = $powerShell
    $shortcut.Arguments = "-NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcher`""
    $shortcut.WorkingDirectory = $WindowsInstallDirectory
    $shortcut.IconLocation = "$icon,0"
    $shortcut.Description = "LYS BBB Scientific Workflows"
    $shortcut.Save()
}

try {
    Write-Step "Controle du paquet"
    if (-not [Environment]::Is64BitOperatingSystem) {
        throw "LYS BBB requiert Windows 64 bits."
    }
    $architecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
    if ($architecture -ne [System.Runtime.InteropServices.Architecture]::X64) {
        throw "Ce paquet requiert un processeur Intel/AMD x86-64; architecture detectee: $architecture."
    }
    Test-BundleIntegrity

    $systemDrive = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$($env:SystemDrive)'"
    $freeSpaceGiB = [math]::Round($systemDrive.FreeSpace / 1GB, 1)
    if ($freeSpaceGiB -lt $MinimumFreeSpaceGiB) {
        throw "Espace insuffisant: $freeSpaceGiB Gio libres; $MinimumFreeSpaceGiB Gio requis."
    }

    $memory = Get-CimInstance Win32_ComputerSystem
    $memoryGiB = [math]::Round($memory.TotalPhysicalMemory / 1GB, 1)
    if ($memoryGiB -lt 7) {
        Write-Warning "Seulement $memoryGiB Gio de RAM detectes. Les traitements ML seront limites."
    }

    Install-WslIfNeeded

    Write-Step "Verification de WSL2"
    & wsl.exe --set-default-version 2 | Out-Host
    & wsl.exe --set-version $DistroName 2 | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Ubuntu n'a pas pu etre configure en WSL2."
    }
    & wsl.exe --distribution $DistroName --user root --exec /bin/true
    if ($LASTEXITCODE -ne 0) {
        if ($WslInstallWasRequested) {
            Show-Information `
                -Title "Redemarrage requis" `
                -Message ("Windows doit redemarrer pour terminer WSL2.`n`n" +
                    "Apres le redemarrage, double-cliquez a nouveau sur Setup-LYS-BBB.cmd.")
            exit 0
        }
        throw "Ubuntu/WSL2 est installe mais ne peut pas demarrer."
    }

    $bundleWslPath = (& wsl.exe --distribution $DistroName --user root --exec `
        wslpath -a $PSScriptRoot).Trim()
    $windowsProfileWslPath = (& wsl.exe --distribution $DistroName --user root --exec `
        wslpath -a $env:USERPROFILE).Trim()
    if (-not $bundleWslPath) {
        throw "Le dossier du paquet n'est pas accessible depuis Ubuntu."
    }

    Write-Step "Installation des dependances scientifiques"
    Write-Host "Cette etape telecharge plusieurs Gio et peut durer 20 a 45 minutes."
    $skipModel = if ($SkipT1ModelDownload) { "1" } else { "0" }
    & wsl.exe --distribution $DistroName --user root --exec `
        /bin/bash "$bundleWslPath/Install-LYS-BBB.sh" `
        "$bundleWslPath/app" `
        "$windowsProfileWslPath" `
        "$skipModel"
    if ($LASTEXITCODE -ne 0) {
        throw "L'installation dans Ubuntu a echoue (code $LASTEXITCODE)."
    }

    Write-Step "Creation de l'icone Windows"
    New-Item -ItemType Directory -Path $WindowsInstallDirectory -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "Launch-LYS-BBB.ps1") `
        -Destination $WindowsInstallDirectory -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "lys-bbb.ico") `
        -Destination $WindowsInstallDirectory -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "handoff-manifest.json") `
        -Destination $WindowsInstallDirectory -Force

    $desktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "LYS BBB.lnk"
    New-LysShortcut -ShortcutPath $desktopShortcut
    $programs = [Environment]::GetFolderPath("Programs")
    New-LysShortcut -ShortcutPath (Join-Path $programs "LYS BBB.lnk")

    Write-Host ""
    Write-Host "Installation terminee." -ForegroundColor Green
    Write-Host "Double-cliquez sur l'icone 'LYS BBB' du Bureau pour demarrer."
    Show-Information `
        -Title "LYS BBB est pret" `
        -Message "L'installation est terminee. Utilisez l'icone LYS BBB du Bureau."
    exit 0
}
catch {
    Write-Host ""
    Write-Host "ERREUR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
