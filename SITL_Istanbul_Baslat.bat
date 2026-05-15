@echo off
title SITL - Istanbul
echo ============================================
echo  SITL Istanbul'da baslatiliyor...
echo  Drone konumu: Istanbul (41.0082, 28.9784)
echo ============================================
echo.
echo GCS baglanti: tcp:127.0.0.1:5762
echo.
wsl bash -l ~/sitl_istanbul.sh
pause
