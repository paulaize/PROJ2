[CmdletBinding()]
param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "LYS-IRM"),
    [switch]$Unattended,
    [switch]$NoShortcuts
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$logPath = $null
$exitCode = 1
$releaseDirectory = $null

function Write-Step {
    param([string]$Message)
    Write-Host $Message
    Add-Content -LiteralPath $logPath -Value $Message -Encoding UTF8
}

function Invoke-LoggedProcess {
    param([string]$FilePath, [string[]]$Arguments, [string]$Step)
    $stdout = "$logPath.$Step.stdout"
    $stderr = "$logPath.$Step.stderr"
    # Windows paths may contain spaces. These internally constructed arguments
    # never contain embedded quotes or end in a directory separator.
    $quoted = ($Arguments | ForEach-Object { '"' + $_ + '"' }) -join ' '
    Add-Content -LiteralPath $logPath -Value "`n[$Step] $FilePath $quoted" -Encoding UTF8
    $process = Start-Process -FilePath $FilePath -ArgumentList $quoted `
        -NoNewWindow -Wait -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    foreach ($output in @($stdout, $stderr)) {
        if ((Test-Path -LiteralPath $output) -and (Get-Item -LiteralPath $output).Length -gt 0) {
            Add-Content -LiteralPath $logPath -Value (Get-Content -LiteralPath $output -Raw -Encoding UTF8) -Encoding UTF8
        }
    }
    Add-Content -LiteralPath $logPath -Value "Exit code: $($process.ExitCode)" -Encoding UTF8
    if ($process.ExitCode -ne 0) { throw "$Step : code $($process.ExitCode)" }
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
    $logPath = Join-Path $logDirectory ("setup-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff") + ".log")
    Set-Content -LiteralPath $logPath -Value "LYS IRM setup - $(Get-Date -Format o) - $InstallRoot" -Encoding UTF8
    Write-Step "Verification..."
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
    Write-Step "Installation..."
    Invoke-LoggedProcess -FilePath (Join-Path $env:SystemRoot "System32\tar.exe") `
        -Arguments @("-xf", $runtimeArchive, "-C", $environmentDirectory) -Step "extract"
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "app") -Destination $applicationDirectory -Recurse
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "models") -Destination $modelDirectory -Recurse
    $python = Join-Path $environmentDirectory "python.exe"
    $env:PATH = "$environmentDirectory;$(Join-Path $environmentDirectory 'Library\bin');$env:PATH"
    $env:PYTHONPATH = Join-Path $applicationDirectory "src"
    $env:PYTHONHOME = $environmentDirectory
    $env:PYTHONNOUSERSITE = "1"
    $env:PYTHONUTF8 = "1"
    $env:LYS_IRM_FEATURE_PROFILE = "t2-only"
    $env:LYS_IRM_MODELS_DIRECTORY = $modelDirectory
    $env:QT_QPA_PLATFORM = "offscreen"
    $env:QT_QPA_FONTDIR = Join-Path $env:WINDIR "Fonts"
    $env:ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS = "2"
    $env:OMP_NUM_THREADS = "2"
    $env:MKL_NUM_THREADS = "2"
    Invoke-LoggedProcess -FilePath $python `
        -Arguments @((Join-Path $environmentDirectory "Scripts\conda-unpack-script.py")) -Step "relocate"

    Write-Step "Finalisation..."
    Invoke-LoggedProcess -FilePath $python `
        -Arguments @("-m", "lys_bbb_app.windows_smoke", "--models-directory", $modelDirectory) -Step "startup"

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
        New-LysShortcut (Join-Path ([Environment]::GetFolderPath("Desktop")) "LYS IRM.lnk")
        New-LysShortcut (Join-Path ([Environment]::GetFolderPath("Programs")) "LYS IRM.lnk")
    }
    Write-Step "Installation terminee. Lancez LYS IRM depuis le Bureau."
    $exitCode = 0
}
catch {
    $failure = $_ | Out-String
    Write-Host "Installation interrompue." -ForegroundColor Red
    if ($logPath -and (Test-Path -LiteralPath $logPath)) {
        Add-Content -LiteralPath $logPath -Value $failure -Encoding UTF8
        Write-Host "Journal : $logPath"
    } else {
        Write-Host $_.Exception.Message
    }
}
exit $exitCode
