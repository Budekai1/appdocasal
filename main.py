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
            
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            try:
                # Carrega a página da SEFAZ
                await page.goto(url, wait_until="networkidle", timeout=30000)

                # Clica em botões comuns de expandir itens na SEFAZ SP se existirem
                for seletor_btn in ["text=Visualizar Itens", "text=Itens", "#btnItens", ".btn-itens", "text=Produtos"]:
                    try:
                        btn = page.locator(seletor_btn)
                        if await btn.count() > 0:
                            await btn.first.click(timeout=2000)
                            await page.wait_for_timeout(1000)
                            break
                    except Exception:
                        pass

                # Pega todo o texto da tabela de resultados ou do corpo da página
                conteudo_texto = await page.inner_text("body")

                # Padrão de extração por blocos de texto (exato do layout SEFAZ-SP)
                linhas = [l.strip() for l in conteudo_texto.split("\n") if l.strip()]
                
                i = 0
                while i < len(linhas):
                    linha = linhas[i]
                    
                    # Procura linhas com "Qtde.:" ou "Quantidade:"
                    match_qtd = re.search(r"Qtde\.?:\s*([\d,\.]+)", linha, re.IGNORECASE)
                    match_unit = re.search(r"Vl\.\s*Unit\.?:\s*([\d,\.]+)", linha, re.IGNORECASE)
                    
                    if match_qtd:
                        nome = linhas[i - 1] if i > 0 else "Produto"
                        nome = re.sub(r"\(Código.*?\)", "", nome).strip()
                        
                        qtd_val = float(match_qtd.group(1).replace(",", "."))
                        
                        # Tenta pegar valor total na linha atual ou na próxima
                        match_tot = re.search(r"Vl\.\s*Total[\s:]*([\d,\.]+)", linha, re.IGNORECASE)
                        if match_tot:
                            vl_total = float(match_tot.group(1).replace(".", "").replace(",", "."))
                        elif i + 1 < len(linhas) and re.match(r"^[\d,\.]+$", linhas[i + 1]):
                            vl_total = float(linhas[i + 1].replace(".", "").replace(",", "."))
                        elif match_unit:
                            vl_unit = float(match_unit.group(1).replace(".", "").replace(",", "."))
                            vl_total = qtd_val * vl_unit
                        else:
                            vl_total = 0.0

                        if vl_total > 0:
                            itens.append({
                                "nome": nome,
                                "quantidade": int(qtd_val) if qtd_val.is_integer() else qtd_val,
                                "valorReal": round(vl_total, 2),
                                "categoria": categorizar_item(nome),
                                "status": "Comprado"
                            })
                    i += 1

                # Se a busca por texto não achar, tenta tabela direta
                if not itens:
                    tabela_linhas = await page.locator("#tabResult tr, table.tabItens tr, tr[id^='Item']").all()
                    for tr in tabela_linhas:
                        t = await tr.inner_text()
                        m_qtd = re.search(r"Qtde\.?:\s*([\d,\.]+)", t, re.IGNORECASE)
                        m_tot = re.search(r"Total[\s:]*([\d,\.]+)", t, re.IGNORECASE)
                        m_nome = re.search(r"^(.*?)(?:\(Código|\n|Qtde)", t)
                        if m_qtd and m_tot:
                            q = float(m_qtd.group(1).replace(",", "."))
                            v = float(m_tot.group(1).replace(".", "").replace(",", "."))
                            n = m_nome.group(1).strip() if m_nome else "Produto"
                            itens.append({
                                "nome": n,
                                "quantidade": int(q) if q.is_integer() else q,
                                "valorReal": round(v, 2),
                                "categoria": categorizar_item(n),
                                "status": "Comprado"
                            })

            finally:
                await browser.close()

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro no Playwright: {str(e)}")

    if not itens:
        raise HTTPException(status_code=404, detail="Itens não localizados na página da Fazenda.")

    return {"itens": itens, "total_itens": len(itens)}
