@echo off
cd /d "%~dp0"
where cargo >nul 2>nul
if errorlevel 1 goto setup
where nvcc >nul 2>nul
if errorlevel 1 goto setup
cd rust
cargo build --release --locked --features cuda
if errorlevel 1 goto failed
cd ..
if not exist dist\Windows-CUDA mkdir dist\Windows-CUDA
copy /Y rust\target\release\cdng-image.exe dist\Windows-CUDA\CDNG-Image.exe
echo Built: dist\Windows-CUDA\CDNG-Image.exe
echo GPU self-tests run automatically when a CUDA job starts.
pause
exit /b 0
:setup
echo Install Rust stable MSVC, Visual Studio C++ Build Tools, and NVIDIA CUDA Toolkit.
echo Then run this file from an x64 Visual Studio Developer Command Prompt.
pause
exit /b 1
:failed
echo Build failed. Review the compiler output above.
pause
exit /b 1
