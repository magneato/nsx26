set -e
cd /dl
xvfb-run -a wine python-3.12.10-amd64.exe /quiet InstallAllUsers=1 PrependPath=1 Include_test=0 TargetDir='C:\Python312'
wineserver -w
xvfb-run -a wine tesseract-setup.exe /S
wineserver -w
ls "/wine/drive_c/Python312/python.exe" "/wine/drive_c/Program Files/Tesseract-OCR/tesseract.exe"
wine 'C:\Python312\python.exe' -c "import sys, os; print(sys.version, os.name, sys.getfilesystemencoding(), sys.stdout.encoding)"
wine 'C:\Program Files\Tesseract-OCR\tesseract.exe' --version
