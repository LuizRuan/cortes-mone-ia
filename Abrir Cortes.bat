@echo off
title Cortes - Monetali
rem Abre o programa de cortes. Feche esta janela para encerrar.
cd /d "%~dp0"
echo Abrindo Cortes Studio... acesse http://127.0.0.1:7860 no navegador.
echo Deixe esta janela aberta enquanto usa. Para encerrar, feche esta janela.
echo.
py studio.py
if errorlevel 1 (
  echo.
  echo O programa parou com erro. Copie a mensagem acima e envie para o suporte.
  pause
)
