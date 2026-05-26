import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

import browser_cookie3
import requests
from bs4 import BeautifulSoup


BASE_URL    = "https://www.nfse.gov.br"
EMITIDAS_URL = f"{BASE_URL}/EmissorNacional/Notas/Emitidas"
XML_NS      = "http://www.sped.fazenda.gov.br/nfse"
TIMEOUT     = 60
MAX_RETRIES = 5
DELAY       = 0.5
XML_WORKERS = 3


class ScraperError(Exception):
    pass


class AuthError(Exception):
    pass


class NFSeScraper:

    def __init__(self, data_inicial: str, data_final: str,
                 progress_callback=None, log_callback=None,
                 max_pages: int = 0, fetch_xml: bool = False, **kwargs):
        self.data_inicial = data_inicial
        self.data_final   = data_final
        self.progress     = progress_callback or (lambda msg, pct: None)
        self.log          = log_callback or (lambda msg: None)
        self.max_pages    = max_pages or 999_999
        self.fetch_xml    = fetch_xml
        self.session      = None

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self) -> list[dict]:
        self._criar_sessao()

        total_pages   = self._total_paginas()
        pages_to_fetch = min(total_pages, self.max_pages)
        self.progress(f"Total: {total_pages} página(s). Coletando dados…", 10)
        self.log(f"✅ Sessão ativa — {total_pages} página(s) encontrada(s)")

        # 1. Coleta tabela página a página
        all_records = []
        for pg in range(1, pages_to_fetch + 1):
            pct = 10 + int(50 * pg / pages_to_fetch)
            self.progress(f"Página {pg}/{pages_to_fetch}…", pct)
            rows = self._extrair_pagina(pg)
            all_records.extend(rows)
            self.log(f"📄 Página {pg:>4}/{pages_to_fetch} — {len(rows)} registro(s)  (total: {len(all_records)})")
            time.sleep(DELAY)

        # 2. Enriquece com dados do XML de cada nota (apenas relatório completo)
        if self.fetch_xml:
            all_records = self._enrich_with_xml(all_records)

        self.progress(f"Concluído — {len(all_records)} nota(s) encontrada(s).", 100)
        self.log(f"🏁 Concluído — {len(all_records)} nota(s) no total")
        return all_records

    # ------------------------------------------------------------------
    # Sessão
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

    def _get(self, url: str, params: dict = None) -> requests.Response:
        for tentativa in range(1, MAX_RETRIES + 1):
            try:
                return self.session.get(url, params=params, timeout=TIMEOUT)
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                wait = 2 ** tentativa
                self.log(f"⚠️  Timeout (tentativa {tentativa}/{MAX_RETRIES}) — aguardando {wait}s...")
                if tentativa == MAX_RETRIES:
                    raise ScraperError(f"Servidor não respondeu após {MAX_RETRIES} tentativas: {e}")
                time.sleep(wait)

    # ------------------------------------------------------------------
    # Paginação
    # ------------------------------------------------------------------

    def _total_paginas(self) -> int:
        self.progress("Verificando total de páginas…", 8)
        r    = self._get(EMITIDAS_URL, self._params(1))
        soup = BeautifulSoup(r.text, "html.parser")

        ultima = soup.find("a", title="Última")
        if ultima and ultima.get("href"):
            m = re.search(r"pg=(\d+)", ultima["href"])
            if m:
                return int(m.group(1))

        links = soup.select(".pagination a")
        nums  = [int(a.get_text(strip=True)) for a in links if a.get_text(strip=True).isdigit()]
        return max(nums) if nums else 1

    # ------------------------------------------------------------------
    # Extração da tabela
    # ------------------------------------------------------------------

    def _extrair_pagina(self, pg: int) -> list[dict]:
        r    = self._get(EMITIDAS_URL, self._params(pg))
        soup = BeautifulSoup(r.text, "html.parser")

        rows = []
        for tr in soup.select("table tbody tr"):
            cells = tr.find_all("td")
            if len(cells) < 5:
                continue

            # URL do XML no menu de opções (coluna 6)
            xml_url = ""
            if len(cells) > 6:
                link = cells[6].find("a", href=lambda h: h and "/Download/NFSe/" in h)
                if link:
                    xml_url = BASE_URL + link["href"]

            rows.append({
                "Geração":            cells[0].get_text(strip=True),
                "Emitida Para":       cells[1].get_text(" ", strip=True),
                "Competência":        cells[2].get_text(strip=True),
                "Município Emissor":  cells[3].get_text(strip=True),
                "Preço Serviço (R$)": cells[4].get_text(strip=True),
                "Situação":           self._situacao(cells[5]) if len(cells) > 5 else "",
                "_xml_url":           xml_url,
            })
        return rows

    def _situacao(self, cell) -> str:
        img = cell.find("img")
        if img:
            titulo = img.get("data-original-title", "")
            if titulo == "NFS-e emitida":   return "Normal"
            if titulo == "NFS-e cancelada": return "Cancelada"
            return titulo
        return cell.get_text(strip=True)

    # ------------------------------------------------------------------
    # Enriquecimento com XML
    # ------------------------------------------------------------------

    def _enrich_with_xml(self, records: list[dict]) -> list[dict]:
        total = len(records)
        self.progress(f"Buscando detalhes XML de {total} nota(s)…", 62)
        self.log(f"📋 Buscando XML de {total} nota(s) ({XML_WORKERS} paralelos)…")

        detalhes: dict[int, dict] = {}
        completed = 0

        with ThreadPoolExecutor(max_workers=XML_WORKERS) as executor:
            futures = {
                executor.submit(self._fetch_xml_detalhes, r["_xml_url"]): i
                for i, r in enumerate(records)
                if r.get("_xml_url")
            }
            for future in as_completed(futures):
                i = futures[future]
                try:
                    detalhes[i] = future.result()
                except Exception as e:
                    detalhes[i] = {}
                    self.log(f"⚠️  Erro XML nota {i+1}: {e}")
                completed += 1
                pct = 62 + int(33 * completed / max(total, 1))
                self.progress(f"XML {completed}/{total}…", pct)
                if completed % 50 == 0:
                    self.log(f"  XML {completed}/{total} processados…")

        result = []
        for i, r in enumerate(records):
            row = {k: v for k, v in r.items() if not k.startswith("_")}
            row.update(detalhes.get(i, {}))
            result.append(row)
        return result

    def _fetch_xml_detalhes(self, xml_url: str) -> dict:
        r = self._get(xml_url)
        if r.status_code != 200:
            return {}
        return self._parse_xml(r.text, xml_url)

    def _parse_xml(self, xml_text: str, xml_url: str = "") -> dict:
        ns = {"n": XML_NS}

        def txt(el, path):
            if el is None:
                return ""
            found = el.find(path, ns)
            return found.text.strip() if found is not None and found.text else ""

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return {}

        inf       = root.find(".//n:infNFSe", ns)
        dps       = root.find(".//n:infDPS",  ns)
        emit      = inf.find("n:emit",     ns) if inf  is not None else None
        prest     = dps.find("n:prest",    ns) if dps  is not None else None
        regTrib   = prest.find("n:regTrib",ns) if prest is not None else None
        toma      = dps.find("n:toma",     ns) if dps  is not None else None
        serv      = dps.find("n:serv",     ns) if dps  is not None else None
        cServ     = serv.find("n:cServ",   ns) if serv is not None else None
        end       = toma.find("n:end",     ns) if toma is not None else None
        endNac    = end.find("n:endNac",   ns) if end  is not None else None
        vals_nf   = inf.find("n:valores",  ns) if inf  is not None else None
        vals_dps  = dps.find("n:valores",  ns) if dps  is not None else None
        vServPrest= vals_dps.find("n:vServPrest", ns) if vals_dps is not None else None
        trib      = vals_dps.find("n:trib",       ns) if vals_dps is not None else None
        tribMun   = trib.find("n:tribMun",         ns) if trib    is not None else None
        tribFed   = trib.find("n:tribFed",         ns) if trib    is not None else None
        piscofins = tribFed.find("n:piscofins",    ns) if tribFed is not None else None

        toma_doc  = txt(toma,  "n:CNPJ") or txt(toma,  "n:CPF")
        prest_doc = txt(prest, "n:CNPJ") or txt(prest, "n:CPF")

        discriminacao = txt(cServ, "n:xDescServ") if cServ else ""
        discriminacao = " | ".join(
            line.strip() for line in discriminacao.splitlines() if line.strip()
        )

        return {
            # Identificação
            "Número NFS-e":           txt(inf,        "n:nNFSe"),
            "Chave de Acesso":        (inf.get("Id", "") if inf is not None else "").replace("NFS", ""),
            "Situação NFS-e":         txt(inf,        "n:cStat"),
            "Número DPS":             txt(dps,        "n:nDPS"),
            "Série":                  txt(dps,        "n:serie"),
            "Data Emissão":           txt(dps,        "n:dhEmi"),
            "Data Competência":       txt(dps,        "n:dCompet"),
            "Localidade Incidência":  txt(inf,        "n:xLocIncid"),
            # Prestador
            "CNPJ/CPF Prestador":     prest_doc,
            "Nome Prestador":         txt(emit,       "n:xNome"),
            "Simples Nacional":       txt(regTrib,    "n:opSimpNac"),
            "Regime Apuração SN":     txt(regTrib,    "n:regApTribSN"),
            "Regime Esp. Tributação": txt(regTrib,    "n:regEspTrib"),
            # Tomador
            "CNPJ/CPF Tomador":       toma_doc,
            "Nome Tomador":           txt(toma,       "n:xNome"),
            "Email Tomador":          txt(toma,       "n:email"),
            "Logradouro Tom.":        txt(end,        "n:xLgr"),
            "Número End. Tom.":       txt(end,        "n:nro"),
            "Bairro Tom.":            txt(end,        "n:xBairro"),
            "CEP Tom.":               txt(endNac,     "n:CEP"),
            "Município Tom.":         txt(endNac,     "n:cMun"),
            # Serviço
            "Cód. Serviço":           txt(cServ,      "n:cTribNac"),
            "Cód. Trib. Municipal":   txt(cServ,      "n:cTribMun"),
            "Cód. NBS":               txt(cServ,      "n:cNBS"),
            "Desc. Tributação Nac.":  txt(inf,        "n:xTribNac"),
            "Desc. Tributação Mun.":  txt(inf,        "n:xTribMun"),
            "Desc. NBS":              txt(inf,        "n:xNBS"),
            "Discriminação":          discriminacao,
            # Valores
            "Valor Serviço":          txt(vServPrest, "n:vServ"),
            "Desc. Incondicionado":   txt(vals_dps,   "n:vDescIncond"),
            "Desc. Condicionado":     txt(vals_dps,   "n:vDescCond"),
            "DED/RED (%)":            txt(vals_dps,   "n:pDR"),
            "Valor DED/RED":          txt(vals_dps,   "n:vDR"),
            "Base de Cálculo":        txt(vals_nf,    "n:vBC"),
            "Alíquota ISS (%)":       txt(vals_nf,    "n:pAliqAplic"),
            "Tipo Ret. ISSQN":        txt(tribMun,    "n:tpRetISSQN"),
            "Valor ISSQN":            txt(vals_nf,    "n:vISSQN"),
            # PIS/COFINS
            "CST PIS/COFINS":         txt(piscofins,  "n:CST"),
            "Base Cálc. PIS/COFINS":  txt(piscofins,  "n:vBCPisCofins"),
            "Alíquota PIS (%)":       txt(piscofins,  "n:pAliqPis"),
            "Alíquota COFINS (%)":    txt(piscofins,  "n:pAliqCofins"),
            "Valor PIS":              txt(piscofins,  "n:vPis"),
            "Valor COFINS":           txt(piscofins,  "n:vCofins"),
            "Tipo Ret. PIS/COFINS":   txt(piscofins,  "n:tpRetPisCofins"),
            # Retenções federais
            "Retenção CP":            txt(tribFed,    "n:vRetCP"),
            "Retenção IRRF":          txt(tribFed,    "n:vRetIRRF"),
            "Retenção CSLL":          txt(tribFed,    "n:vRetCSLL"),
            # Totais
            "Valor Total Retenções":  txt(vals_nf,    "n:vTotalRet"),
            "Valor Líquido":          txt(vals_nf,    "n:vLiq"),
            "URL":                    xml_url,
        }
