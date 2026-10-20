# Installs Python 3.14 for the current user. Run by Setup-Jarvis.bat only when no Python 3.12+ was found and you said yes.
# First choice: winget (built into Windows 10/11, but missing on some "lite" builds). Second: the installer from python.org,
# which is checked for Python Software Foundation's signature before it is run. Exit code 0 = Python is installed.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"          # (the progress bar makes Invoke-WebRequest many times slower)

function Say($text) { Write-Host "  $text" }

if (Get-Command winget -ErrorAction SilentlyContinue) {
    Say "Installing Python 3.14 with winget (Windows' own installer tool)..."
    & winget install -e --id Python.Python.3.14 --scope user --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -eq 0) { Say "Python 3.14 is installed."; exit 0 }
    Say "winget did not finish (code $LASTEXITCODE); trying the download from python.org instead."
}

$versions = @("3.14.7", "3.14.6", "3.14.5", "3.14.4", "3.14.3", "3.14.2", "3.14.1", "3.14.0")
$folder = Join-Path $env:TEMP "JarvisSetup"
New-Item -ItemType Directory -Force -Path $folder | Out-Null
$file = $null
foreach ($v in $versions) {
    $url = "https://www.python.org/ftp/python/$v/python-$v-amd64.exe"
    $target = Join-Path $folder "python-$v-amd64.exe"
    try {
        Say "Downloading Python $v (about 27 MB) from python.org..."
        Invoke-WebRequest -Uri $url -OutFile $target -UseBasicParsing
        $file = $target
        break
    } catch {
        Say "Python $v is not available there; trying an older one."
    }
}
if (-not $file) {
    Say "Could not download Python. Opening the download page: install Python 3.14 (tick 'Add python.exe to PATH'), then run Setup-Jarvis.bat again."
    Start-Process "https://www.python.org/downloads/"
    exit 1
}

$signature = Get-AuthenticodeSignature -LiteralPath $file
if ($signature.Status -ne "Valid" -or $signature.SignerCertificate.Subject -notmatch "Python Software Foundation") {
    Say "The downloaded file is not signed by the Python Software Foundation ($($signature.Status)), so I will not run it."
    exit 1
}
Say "Signed by the Python Software Foundation. Installing for your account only (no administrator rights needed)..."
$process = Start-Process -FilePath $file -ArgumentList "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_launcher=1", "Include_pip=1", "Include_test=0", "Shortcuts=0" -Wait -PassThru
if ($process.ExitCode -ne 0) { Say "The installer stopped with code $($process.ExitCode)."; exit 1 }
Say "Python is installed."
exit 0
