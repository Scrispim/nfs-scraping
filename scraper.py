import re
import time

import browser_cookie3
import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.nfse.gov.br"
EMITIDAS_URL = f"{BASE_URL}/EmissorNacional/Notas/Emitidas"
TIMEOUT = 60
MAX_RETRIES = 5
DELAY = 0.5  # segundos entre requisições


class ScraperError(Exception):
    pass


class AuthError(Exception):
    pass


class NFSeScraper:

    def __init__(self, data_inicial: str, data_final: str, progress_callback=None, log_callback=None, max_pages: int = 0, **kwargs):
        self.data_inicial = data_inicial
        self.data_final = data_final
        self.progress = progress_callback or (lambda msg, pct: None)
        self.log = log_callback or (lambda msg: None)
        self.max_pages = max_pages or 999_999
        self.session = None

    def run(self) -> list[dict]:
        self._criar_sessao()
        total_pages = self._total_paginas()
        pages_to_fetch = min(total_pages, self.max_pages)
        self.progress(f"Total: {total_pages} página(s). Coletando dados…", 20)
        self.log(f"✅ Sessão ativa — {total_pages} página(s) encontrada(s)")

        all_records = []
        for pg in range(1, pages_to_fetch + 1):
            pct = 20 + int(75 * pg / pages_to_fetch)
            self.progress(f"Página {pg}/{pages_to_fetch}…", pct)
            rows = self._extrair_pagina(pg)
            all_records.extend(rows)
            self.log(f"📄 Página {pg:>4}/{pages_to_fetch} — {len(rows)} registro(s)  (total: {len(all_records)})")
            time.sleep(DELAY)

        self.progress(f"Concluído — {len(all_records)} nota(s) encontrada(s).", 100)
        self.log(f"🏁 Concluído — {len(all_records)} nota(s) no total")
        return all_records

    # ------------------------------------------------------------------

    def _criar_sessao(self):
        self.progress("Lendo sessão do Chrome…", 5)
        try:
            cookies = browser_cookie3.chrome(domain_name="nfse.gov.br")
        except Exception as e:
            raise ScraperError(f"Não foi possível ler os cookies do Chrome: {e}")

        self.session = requests.Session()
        self.session.cookies.update(cookies)
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})

        r = self._get(EMITIDAS_URL, self._params(1))
        if "Login" in r.url or "login" in r.url:
            raise ScraperError(
                "Sessão expirada. Abra o Chrome, acesse o portal NFS-e, faça login e tente novamente."
            )

    def _params(self, pg: int) -> dict:
        return {"datainicio": self.data_inicial, "datafim": self.data_final, "pg": pg}

    def _get(self, url: str, params: dict) -> requests.Response:
        for tentativa in range(1, MAX_RETRIES + 1):
            try:
                return self.session.get(url, params=params, timeout=TIMEOUT)
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                wait = 2 ** tentativa
                self.log(f"⚠️  Timeout (tentativa {tentativa}/{MAX_RETRIES}) — aguardando {wait}s...")
                if tentativa == MAX_RETRIES:
                    raise ScraperError(f"Servidor não respondeu após {MAX_RETRIES} tentativas: {e}")
                time.sleep(wait)

    def _total_paginas(self) -> int:
        self.progress("Verificando total de páginas…", 10)
        r = self._get(EMITIDAS_URL, self._params(1))
        soup = BeautifulSoup(r.text, "html.parser")

        ultima = soup.find("a", title="Última")
        if ultima and ultima.get("href"):
            m = re.search(r"pg=(\d+)", ultima["href"])
            if m:
                return int(m.group(1))

        links = soup.select(".pagination a")
        nums = [int(a.get_text(strip=True)) for a in links if a.get_text(strip=True).isdigit()]
        return max(nums) if nums else 1

    def _extrair_pagina(self, pg: int) -> list[dict]:
        r = self._get(EMITIDAS_URL, self._params(pg))
        soup = BeautifulSoup(r.text, "html.parser")

        rows = []
        for tr in soup.select("table tbody tr"):
            cells = tr.find_all("td")
            if len(cells) < 5:
                continue
            rows.append({
                "Geração":            cells[0].get_text(strip=True),
                "Emitida Para":       cells[1].get_text(" ", strip=True),
                "Competência":        cells[2].get_text(strip=True),
                "Município Emissor":  cells[3].get_text(strip=True),
                "Preço Serviço (R$)": cells[4].get_text(strip=True),
                "Situação":           cells[5].get_text(strip=True) if len(cells) > 5 else "",
            })
        return rows
