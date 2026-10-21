#!/usr/bin/env bash
pip install -r requirements.txt
playwright install-deps chromium
playwright install chromium
