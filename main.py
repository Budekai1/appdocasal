from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import re
from playwright.async_api import async_playwright

app = FastAPI()

# Permissões completas de CORS para o frontend (Netlify / Telemóvel)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class QrRequest(BaseModel):
    url: str

def categorizar_item(nome: str) -> str:
    n = nome.upper()
    if any(k in n for k in ['SBT', 'SABONETE', 'SH', 'SHAMPOO', 'CR COLG', 'DENTAL', 'P H FAM', 'HIGI', 'HAST']):
        return 'Banheiro'
    if any(k in n for k in ['DET', 'YPE', 'D PATO', 'TOALHA YURI', 'ALCOOL', 'COPERALC', 'LAVAN']):
        return 'Lavanderia'
    if any(k in n for k in ['PAO', 'PANCO', 'TAPIOCA', 'PRATO', 'PANELA', 'COZ']):
        return 'Cozinha'
    if any(k in n for k in ['GATORADE', 'TRENTO', 'ROSQ', 'LAZER', 'JOGO']):
        return 'Lazer'
    if any(k in n for k in ['CABO', 'USB', 'FONE', 'MOUSE']):
        return 'Tecnologia'
    return 'Mercado'

@app.get("/")
def home():
    return {"status": "API Online"}

@app.post("/consultar-nfe")
async def consultar_nfe(dados: QrRequest):
    url = dados.url.strip()
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="URL inválida fornecida.")

    itens = []
    
    try:
        async with async_playwright() as p:
            # Flags vitais para correr o Chromium no Linux sem GUI e sem privilégios de root
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--no-first-run",
                    "--no-zygote",
                    "--single-process"
                ]
            )
            
            # Simula um navegador real móvel para contornar verificações do portal fiscal
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
            )
            page = await context.new_page()

            try:
                # Abre a página da SEFAZ
                await page.goto(url, wait_until="domcontentloaded", timeout=25000)

                # Se houver botão/aba para expandir itens (comum no portal SP)
                btn_itens = page.locator("text=Itens")
                if await btn_itens.count() > 0:
                    try:
                        await btn_itens.first.click(timeout=3000)
                        await page.wait_for_timeout(1000)
                    except Exception:
                        pass

                # Procura por linhas de produtos na página
                linhas = await page.locator("tr[id^='Item'], tr.item, table.tabItens tr, .ui-grid-row, .box, tr").all()

                for linha in linhas:
                    texto = await linha.inner_text()
                    if not texto or ("Código" not in texto and "Qtde" not in texto):
                        continue

                    nome_match = re.search(r"^(.*?)(?:\(Código|\n|Qtde)", texto, re.MULTILINE)
                    qtd_match = re.search(r"Qtde\.?:\s*([\d,\.]+)", texto, re.IGNORECASE)
                    vl_total_match = re.search(r"(?:Vl\.\s*Total|Total)[\s:]*R?\$?\s*([\d,\.]+)", texto, re.IGNORECASE)

                    if nome_match and vl_total_match:
                        nome = nome_match.group(1).strip()
                        qtd_str = qtd_match.group(1).replace(",", ".") if qtd_match else "1"
                        total_str = vl_total_match.group(1).replace(".", "").replace(",", ".")

                        qtd = float(qtd_str)
                        vl_total = float(total_str)

                        itens.append({
                            "nome": nome,
                            "quantidade": int(qtd) if qtd.is_integer() else qtd,
                            "valorReal": round(vl_total, 2),
                            "categoria": categorizar_item(nome),
                            "status": "Comprado"
                        })
            finally:
                await browser.close()

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro no Playwright: {str(e)}")

    if not itens:
        raise HTTPException(status_code=404, detail="Itens não localizados na página da Fazenda.")

    return {"itens": itens, "total_itens": len(itens)}
