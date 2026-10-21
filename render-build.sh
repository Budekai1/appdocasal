#!/usr/bin/env bash
set -e
# Atualiza o pip
pip install --upgrade pip
# Instala as dependências Python
pip install -r requirements.txt
# Instala apenas o binário do Chromium sem tentar aceder ao utilizador root
playwright install chromium
