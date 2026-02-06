
set PYTHON=C:\Users\murase\AppData\Local\Programs\Python\Python313\python.exe
call SingleBinaryBuild\get_externals.bat --tkinter-src --openssl-src --libffi-src --no-llvm
set LIBFFI_SOURCE=%~dp0externals\libffi-3.4.4
set "VCVARSALL=C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvarsall.bat"
call SingleBinaryBuild\prepare_libffi.bat -x64 --install-cygwin
call SingleBinaryBuild\prepare_ssl.bat
call SingleBinaryBuild\prepare_tcltk.bat
call SingleBinaryBuild\build.bat -c Release -p x64 -t Build
