
set PYTHON=C:\Users\murase\AppData\Local\Programs\Python\Python313\python.exe
call SingleBinaryBuild\get_externals.bat --libffi-src
if NOT DEFINED LIBFFI_SOURCE set LIBFFI_SOURCE=%~dp0externals\libffi-3.4.4
call SingleBinaryBuild\prepare_libffi.bat -x64
call SingleBinaryBuild\build.bat -c Release -p x64 -t Build --no-ssl --no-tkinter
