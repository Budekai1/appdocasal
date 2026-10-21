#!/usr/bin/env bash
set -e
# Atualiza o pip
pip install --upgrade pip
# Instala as dependências Python
pip install -r requirements.txt
# Força o Playwright a descarregar o navegador para uma pasta fixa do projeto
export PLAYWRIGHT_BROWSERS_PATH="./pw-browsers"
playwright install chromium
