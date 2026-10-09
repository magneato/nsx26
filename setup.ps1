# One-time setup on Windows 11: Tesseract, a Python venv, fonts, the corpus, the word model.
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1             (installs Python 3.12 and Tesseract with winget if missing)
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1 -NoWinget   (skip winget)
param([switch]$NoWinget)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$onWindows = $env:OS -eq "Windows_NT"          # also true in Windows PowerShell 5.1, which has no $IsWindows

function Invoke-Native {
    # Run a program and judge it by its exit code only. Windows PowerShell 5.1 with
    # ErrorActionPreference=Stop can turn a program's harmless stderr output (pip notices)
    # into a terminating error, so native calls run with Continue.
    param([string]$What, [string]$Exe, [string[]]$ArgList)
    $saved = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Exe @ArgList 2>&1 | ForEach-Object { "$_" } | Write-Host; $rc = $LASTEXITCODE }
    finally { $ErrorActionPreference = $saved }
    if ($rc -ne 0) { throw "$What failed (exit code $rc)" }
}

function Find-Python {
    # returns @(exe, args...) for a Python 3.10+, or $null
    $candidates = @(@("py", "-3"), @("python"), @("python3"))
    foreach ($c in $candidates) {
        $exe = $c[0]
        $rest = @($c | Select-Object -Skip 1)
        if (Get-Command $exe -ErrorAction SilentlyContinue) {
            $saved = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            try { $ok = & $exe @rest -c "import sys; print(sys.version_info >= (3, 10))" 2>$null }
            finally { $ErrorActionPreference = $saved }
            if ("$ok".Trim() -eq "True") { return ,$c }
        }
    }
    return $null
}

function Find-Tesseract {
    foreach ($p in @($env:NSX26_TESSERACT, "$env:ProgramFiles\Tesseract-OCR\tesseract.exe",
                     "${env:ProgramFiles(x86)}\Tesseract-OCR\tesseract.exe")) {
        if ($p -and (Test-Path -LiteralPath $p)) { return $p }
    }
    $cmd = Get-Command tesseract -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

if (-not $NoWinget -and $onWindows) {
    $winget = @("--exact", "--accept-source-agreements", "--accept-package-agreements")
    if (-not (Find-Python)) { winget install --id Python.Python.3.12 @winget }
    if (-not (Find-Tesseract)) { winget install --id UB-Mannheim.TesseractOCR @winget }
}

$py = Find-Python
if (-not $py) { throw "Python 3.10+ is required: winget install Python.Python.3.12, then open a new terminal." }
if (-not (Find-Tesseract)) { throw "Tesseract is required: winget install UB-Mannheim.TesseractOCR (or set NSX26_TESSERACT)." }

$venvPy = if ($onWindows) { Join-Path $PSScriptRoot ".venv\Scripts\python.exe" } else { Join-Path $PSScriptRoot ".venv/bin/python" }
if (-not (Test-Path -LiteralPath $venvPy)) {
    $rest = @($py | Select-Object -Skip 1)
    Invoke-Native "creating .venv" $py[0] ($rest + @("-m", "venv", ".venv"))
}
Invoke-Native "upgrading pip" $venvPy @("-m", "pip", "install", "--quiet", "--upgrade", "pip")
Invoke-Native "installing requirements" $venvPy @("-m", "pip", "install", "--quiet", "-r", "requirements.txt")
Invoke-Native "downloading fonts and corpus" $venvPy @((Join-Path $PSScriptRoot "tools" | Join-Path -ChildPath "fetch.py"))
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot "data" | Join-Path -ChildPath "wordmodel.npz"))) {
    $tool = Join-Path $PSScriptRoot $(if ($onWindows) { "unredact.cmd" } else { "unredact.sh" })
    Invoke-Native "training the word model" $tool @("train")
}
if ($onWindows) { Write-Host "ready: .\redact.cmd --help   .\unredact.cmd --help   .\unredact.cmd evaluate" }
else { Write-Host "ready: ./redact.sh --help   ./unredact.sh --help   ./unredact.sh evaluate" }
