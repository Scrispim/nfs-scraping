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
# O portal parece limitar a taxa de requisições por sessão/IP (bloqueio
# silencioso, sem erro — a página some e volta vazia). Delay alto reduz a
# chance de disparar esse limite.
DELAY       = 2.5
XML_WORKERS = 3
# Página vazia mas o portal ainda informa mais páginas => provável bloqueio
# temporário (rate limit) do portal por requisições em rajada. Tenta de novo
# com espera bem mais longa antes de desistir.
RETRY_DELAYS_EMPTY = [10, 20, 40, 60]


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

        total_pages_estimado = self._total_paginas()
        self.progress(f"Total estimado: {total_pages_estimado} página(s). Coletando dados…", 10)
        self.log(f"✅ Sessão ativa — {total_pages_estimado} página(s) informada(s) pelo portal (estimativa)")

        # Não confia apenas no total informado pelo widget de paginação do
        # portal, pois ele pode exibir só uma janela de páginas (ex.: até a
        # 21) mesmo havendo mais resultados. Continua até uma página vir vazia.
        all_records = []
        pg = 0
        tentativas_vazias = 0
        while True:
            pg += 1
            if pg > self.max_pages:
                break
            pct = 10 + int(50 * min(pg, total_pages_estimado) / max(total_pages_estimado, 1))
            self.progress(f"Página {pg}…", min(pct, 60))
            rows = self._extrair_pagina(pg)

            if not rows:
                ainda_faltam_paginas = pg <= total_pages_estimado
                if ainda_faltam_paginas and tentativas_vazias < len(RETRY_DELAYS_EMPTY):
                    espera = RETRY_DELAYS_EMPTY[tentativas_vazias]
                    tentativas_vazias += 1
                    self.log(
                        f"⚠️ Página {pg} veio vazia, mas o portal informa {total_pages_estimado} "
                        f"página(s) — possível bloqueio temporário. Aguardando {espera}s e "
                        f"tentando de novo ({tentativas_vazias}/{len(RETRY_DELAYS_EMPTY)})…"
                    )
                    time.sleep(espera)
                    pg -= 1  # tenta a mesma página de novo
                    continue
                break  # fim real dos resultados, ou tentativas esgotadas

            tentativas_vazias = 0
            all_records.extend(rows)
            self.log(f"📄 Página {pg:>4} — {len(rows)} registro(s)  (total: {len(all_records)})")
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
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Referer": EMITIDAS_URL,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

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

            emitida_para_bruto = cells[1].get_text(" ", strip=True)
            emitida_para, nome_cliente = self._separar_nome_cliente(emitida_para_bruto)
            rows.append({
                "Geração":            cells[0].get_text(strip=True),
                "Emitida Para":       emitida_para,
                "Nome Cliente":       nome_cliente,
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

    def _separar_nome_cliente(self, emitida_para_bruto: str) -> tuple[str, str]:
        """"021.355.926-92 - MILLENA LUIZA DINIZ FERREIRA" ->
        ("021.355.926-92", "MILLENA LUIZA DINIZ FERREIRA").

        O CPF/CNPJ termina em "-DD" (dígito verificador) sem espaços; o nome
        vem depois separado por " - " com espaços. Se não bater com esse
        formato (ex.: já é só um nome/razão social), mantém "Emitida Para"
        como veio e retorna nome vazio.
        """
        m = re.match(r"^([\d./]+-\d{2})\s*-\s*(.+)$", emitida_para_bruto)
        if not m:
            return emitida_para_bruto, ""
        return m.group(1).strip(), m.group(2).strip()

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
