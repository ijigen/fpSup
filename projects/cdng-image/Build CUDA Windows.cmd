@echo off
cd /d "%~dp0"
where nvcc >nul 2>nul
if errorlevel 1 (
  echo Install the NVIDIA CUDA Toolkit and run this in an x64 Visual Studio Developer Prompt.
  pause
  exit /b 1
)
nvcc -O3 -std=c++17 --shared -cudart=static -gencode arch=compute_75,code=[sm_75,compute_75] -Xcompiler /MD cdng_image\native\cuda_backend.cu -o cdng_image\native\cdng_cuda.dll
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m unittest tests.test_gpu -v
pause
