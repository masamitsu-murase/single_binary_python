
set PYTHON=C:\Users\murase\AppData\Local\Programs\Python\Python313\python.exe
call SingleBinaryBuild\get_externals.bat --libffi-src
call SingleBinaryBuild\build.bat -c Release -p x64 -t Build --no-ssl --no-tkinter
