@echo off
title Cortes - Monetali
rem Abre o programa de cortes. Feche esta janela para encerrar.
cd /d "%~dp0"
echo Abrindo o programa de cortes... o navegador abre sozinho em alguns segundos.
echo Deixe esta janela aberta enquanto usa. Para encerrar, feche esta janela.
echo.
py app.py
if errorlevel 1 (
  echo.
  echo O programa parou com erro. Copie a mensagem acima e envie para o suporte.
  pause
)
