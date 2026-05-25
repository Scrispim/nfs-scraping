@echo off
chcp 65001 >nul
title NFS-e — Extrator de Relatórios

echo ========================================
echo   NFS-e — Extrator de Relatórios
echo ========================================
echo.

:: Vai para a pasta onde este arquivo está
cd /d "%~dp0"

:: Verifica se Python está instalado
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado.
    echo.
    echo Instale o Python em: https://www.python.org/downloads/
    echo IMPORTANTE: marque "Add Python to PATH" durante a instalacao.
    echo.
    echo Apos instalar, clique duas vezes neste arquivo novamente.
    start https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [OK] Python encontrado.

:: Cria ambiente virtual se nao existir
if not exist ".venv\" (
    echo.
    echo Configurando o app pela primeira vez ^(so acontece uma vez^)...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    python -m pip install --quiet --upgrade pip
    python -m pip install --quiet -r requirements.txt
    echo [OK] Instalacao concluida!
) else (
    call .venv\Scripts\activate.bat
)

echo.
echo Iniciando o app...
echo Acesse: http://localhost:8501
echo Para encerrar: feche esta janela
echo.

:: Abre o browser automaticamente após 3 segundos
start /b cmd /c "timeout /t 3 >nul && start http://localhost:8501"

python -m streamlit run app.py --server.port 8501 --server.headless true
