const BASE      = "https://www.nfse.gov.br/EmissorNacional/Notas/Emitidas";
const BASE_HOST = "https://www.nfse.gov.br";
const DELAY_MS  = 500;
const XML_NS    = "http://www.sped.fazenda.gov.br/nfse";
const XML_WORKERS = 3;

let dadosColetados = [];

// --- Datas padrão (últimos 30 dias) ---
const hoje = new Date();
const h30 = new Date(); h30.setDate(hoje.getDate() - 30);
document.getElementById("dataFim").value    = fmtISO(hoje);
document.getElementById("dataInicio").value = fmtISO(h30);

// --- Aviso 30 dias ---
function verificaLimite() {
  const di = new Date(document.getElementById("dataInicio").value);
  const df = new Date(document.getElementById("dataFim").value);
  const dias = (df - di) / 86400000;
  document.getElementById("avisoLimite").style.display = dias > 30 ? "block" : "none";
}
document.getElementById("dataInicio").addEventListener("change", verificaLimite);
document.getElementById("dataFim").addEventListener("change", verificaLimite);

function tipoRelatorio() {
  return document.querySelector("input[name='tipoRelatorio']:checked").value;
}

// --- Botão Buscar ---
document.getElementById("btnBuscar").addEventListener("click", async () => {
  const di = document.getElementById("dataInicio").value;
  const df = document.getElementById("dataFim").value;
  if (!di || !df) { alert("Preencha as datas."); return; }

  const diaBR = isoParaBR(di);
  const dfBR  = isoParaBR(df);
  const completo = tipoRelatorio() === "completo";

  const btn  = document.getElementById("btnBuscar");
  const stat = document.getElementById("status");
  const log  = document.getElementById("log");

  btn.disabled = true;
  dadosColetados = [];
  document.getElementById("btnBaixar").style.display = "none";
  stat.style.display = "block";
  log.style.display  = "block";
  log.textContent    = "";

  function setStatus(msg) { stat.textContent = msg; }
  function addLog(msg)    { log.textContent += msg + "\n"; log.scrollTop = log.scrollHeight; }

  try {
    setStatus("Verificando sessão e total de páginas…");
    const totalPag = await getTotalPaginas(diaBR, dfBR);
    addLog(`✅ Sessão ativa — ${totalPag} página(s) encontrada(s)`);

    for (let pg = 1; pg <= totalPag; pg++) {
      setStatus(`Página ${pg}/${totalPag}…`);
      const rows = await extrairPagina(diaBR, dfBR, pg, completo);
      dadosColetados.push(...rows);
      addLog(`📄 Página ${String(pg).padStart(4)} — ${rows.length} registro(s)  (total: ${dadosColetados.length})`);
      if (pg < totalPag) await sleep(DELAY_MS);
    }

    if (completo) {
      addLog(`📋 Buscando XML de ${dadosColetados.length} nota(s) (${XML_WORKERS} paralelos)…`);
      await enriquecerComXML(dadosColetados, setStatus, addLog);
    }

    addLog(`🏁 Concluído — ${dadosColetados.length} nota(s) no total`);
    setStatus(`✅ ${dadosColetados.length} nota(s) encontrada(s). Clique em Baixar Excel.`);
    document.getElementById("btnBaixar").style.display = "block";

  } catch (e) {
    setStatus("❌ Erro: " + e.message);
    addLog("ERRO: " + e.message);
  }

  btn.disabled = false;
});

// --- Botão Baixar ---
document.getElementById("btnBaixar").addEventListener("click", () => {
  if (!dadosColetados.length) return;
  const di = document.getElementById("dataInicio").value;
  const df = document.getElementById("dataFim").value;
  const completo = tipoRelatorio() === "completo";
  baixarCSV(dadosColetados, di, df, completo);
});

// ------------------------------------------------------------------
// Funções de scraping
// ------------------------------------------------------------------

async function getTotalPaginas(di, df) {
  const html = await fetchPagina(di, df, 1);
  if (!html) throw new Error("Sessão expirada. Faça login no portal NFS-e e tente novamente.");

  const doc   = new DOMParser().parseFromString(html, "text/html");
  const ultima = doc.querySelector("a[title='Última']");
  if (ultima) {
    const m = ultima.href.match(/pg=(\d+)/);
    if (m) return parseInt(m[1]);
  }
  const links = [...doc.querySelectorAll(".pagination a")];
  const nums  = links.map(a => parseInt(a.textContent.trim())).filter(n => !isNaN(n));
  return nums.length ? Math.max(...nums) : 1;
}

async function extrairPagina(di, df, pg, incluirXmlUrl) {
  const html = await fetchPagina(di, df, pg);
  const doc  = new DOMParser().parseFromString(html, "text/html");
  const rows = [];
  doc.querySelectorAll("table tbody tr").forEach(tr => {
    const cells = tr.querySelectorAll("td");
    if (cells.length < 5) return;

    let xmlUrl = "";
    if (incluirXmlUrl && cells.length > 6) {
      const link = [...cells[6].querySelectorAll("a")].find(a => {
        const h = a.getAttribute("href");
        return h && h.includes("/Download/NFSe/");
      });
      if (link) xmlUrl = BASE_HOST + link.getAttribute("href");
    }

    rows.push({
      "Geração":            cells[0].innerText.trim(),
      "Emitida Para":       cells[1].innerText.trim().replace(/\s+/g, " "),
      "Competência":        cells[2].innerText.trim(),
      "Município Emissor":  cells[3].innerText.trim(),
      "Preço Serviço (R$)": cells[4].innerText.trim(),
      "Situação":           cells[5] ? parseSituacao(cells[5]) : "",
      "_xml_url":           xmlUrl,
    });
  });
  return rows;
}

async function fetchPagina(di, df, pg) {
  const url = `${BASE}?datainicio=${encodeURIComponent(di)}&datafim=${encodeURIComponent(df)}&pg=${pg}`;
  const resp = await fetch(url, { credentials: "include" });
  if (resp.url.includes("Login") || resp.url.includes("login")) return null;
  return resp.text();
}

// ------------------------------------------------------------------
// Enriquecimento com XML
// ------------------------------------------------------------------

async function enriquecerComXML(records, setStatus, addLog) {
  const total = records.length;
  let completed = 0;
  let erros = 0;

  // Processa em lotes de XML_WORKERS
  for (let i = 0; i < records.length; i += XML_WORKERS) {
    const lote = records.slice(i, i + XML_WORKERS);
    await Promise.all(lote.map(async (r) => {
      if (r._xml_url) {
        try {
          const detalhes = await fetchXmlDetalhes(r._xml_url);
          detalhes["URL"] = r._xml_url;
          Object.assign(r, detalhes);
        } catch (e) {
          erros++;
          addLog(`⚠️ Erro XML nota ${completed + 1}: ${e.message}`);
        }
      }
      completed++;
      setStatus(`XML ${completed}/${total}…`);
      if (completed % 50 === 0) addLog(`  XML ${completed}/${total} processados…`);
    }));
  }
  if (erros > 0) addLog(`⚠️ ${erros} nota(s) sem XML.`);
}

async function fetchXmlDetalhes(xmlUrl) {
  const resp = await fetch(xmlUrl, { credentials: "include" });
  if (!resp.ok) return {};
  const text = await resp.text();
  return parseXml(text);
}

function parseXml(xmlText) {
  const parser = new DOMParser();
  const doc = parser.parseFromString(xmlText, "application/xml");

  // Verifica erro de parse
  const errEl = doc.getElementsByTagName("parsererror")[0];
  if (errEl) return {};

  function get(root, tag) {
    if (!root) return null;
    return root.getElementsByTagName(tag)[0] || null;
  }

  function txt(root, tag) {
    const el = get(root, tag);
    return el ? (el.textContent || "").trim() : "";
  }

  const inf       = get(doc,   "infNFSe");
  const dps       = get(doc,   "infDPS");
  const emit      = get(inf,   "emit");
  const prest     = get(dps,   "prest");
  const regTrib   = get(prest, "regTrib");
  const toma      = get(dps,   "toma");
  const serv      = get(dps,   "serv");
  const cServ     = get(serv,  "cServ");
  const end       = get(toma,  "end");
  const endNac    = get(end,   "endNac");
  // valores financeiros: primeiro <valores> dentro de infNFSe (antes do DPS)
  const valsAll   = inf ? inf.getElementsByTagName("valores") : [];
  const vals_nf   = valsAll[0] || null;
  const vals_dps  = get(dps,   "valores");
  const vServPrest= get(vals_dps, "vServPrest");
  const trib      = get(vals_dps, "trib");
  const tribMun   = get(trib,  "tribMun");
  const tribFed   = get(trib,  "tribFed");
  const piscofins = get(tribFed, "piscofins");

  const tomaDoc  = txt(toma,  "CNPJ") || txt(toma,  "CPF");
  const prestDoc = txt(prest, "CNPJ") || txt(prest, "CPF");

  const xDesc = get(cServ, "xDescServ");
  const discriminacao = xDesc
    ? (xDesc.textContent || "").split("\n").map(l => l.trim()).filter(Boolean).join(" | ")
    : "";

  const infId = inf ? (inf.getAttribute("Id") || "").replace("NFS", "") : "";

  return {
    // Identificação
    "Número NFS-e":           txt(inf,        "nNFSe"),
    "Chave de Acesso":        infId,
    "Situação NFS-e":         txt(inf,        "cStat"),
    "Número DPS":             txt(dps,        "nDPS"),
    "Série":                  txt(dps,        "serie"),
    "Data Emissão":           txt(dps,        "dhEmi"),
    "Data Competência":       txt(dps,        "dCompet"),
    "Localidade Incidência":  txt(inf,        "xLocIncid"),
    // Prestador
    "CNPJ/CPF Prestador":     prestDoc,
    "Nome Prestador":         txt(emit,       "xNome"),
    "Simples Nacional":       txt(regTrib,    "opSimpNac"),
    "Regime Apuração SN":     txt(regTrib,    "regApTribSN"),
    "Regime Esp. Tributação": txt(regTrib,    "regEspTrib"),
    // Tomador
    "CNPJ/CPF Tomador":       tomaDoc,
    "Nome Tomador":           txt(toma,       "xNome"),
    "Email Tomador":          txt(toma,       "email"),
    "Logradouro Tom.":        txt(end,        "xLgr"),
    "Número End. Tom.":       txt(end,        "nro"),
    "Bairro Tom.":            txt(end,        "xBairro"),
    "CEP Tom.":               txt(endNac,     "CEP"),
    "Município Tom.":         txt(endNac,     "cMun"),
    // Serviço
    "Cód. Serviço":           txt(cServ,      "cTribNac"),
    "Cód. Trib. Municipal":   txt(cServ,      "cTribMun"),
    "Cód. NBS":               txt(cServ,      "cNBS"),
    "Desc. Tributação Nac.":  txt(inf,        "xTribNac"),
    "Desc. Tributação Mun.":  txt(inf,        "xTribMun"),
    "Desc. NBS":              txt(inf,        "xNBS"),
    "Discriminação":          discriminacao,
    // Valores
    "Valor Serviço":          txt(vServPrest, "vServ"),
    "Desc. Incondicionado":   txt(vals_dps,   "vDescIncond"),
    "Desc. Condicionado":     txt(vals_dps,   "vDescCond"),
    "DED/RED (%)":            txt(vals_dps,   "pDR"),
    "Valor DED/RED":          txt(vals_dps,   "vDR"),
    "Base de Cálculo":        txt(vals_nf,    "vBC"),
    "Alíquota ISS (%)":       txt(vals_nf,    "pAliqAplic"),
    "Tipo Ret. ISSQN":        txt(tribMun,    "tpRetISSQN"),
    "Valor ISSQN":            txt(vals_nf,    "vISSQN"),
    // PIS/COFINS
    "CST PIS/COFINS":         txt(piscofins,  "CST"),
    "Base Cálc. PIS/COFINS":  txt(piscofins,  "vBCPisCofins"),
    "Alíquota PIS (%)":       txt(piscofins,  "pAliqPis"),
    "Alíquota COFINS (%)":    txt(piscofins,  "pAliqCofins"),
    "Valor PIS":              txt(piscofins,  "vPis"),
    "Valor COFINS":           txt(piscofins,  "vCofins"),
    "Tipo Ret. PIS/COFINS":   txt(piscofins,  "tpRetPisCofins"),
    // Retenções
    "Retenção CP":            txt(tribFed,    "vRetCP"),
    "Retenção IRRF":          txt(tribFed,    "vRetIRRF"),
    "Retenção CSLL":          txt(tribFed,    "vRetCSLL"),
    // Totais
    "Valor Total Retenções":  txt(vals_nf,    "vTotalRet"),
    "Valor Líquido":          txt(vals_nf,    "vLiq"),
    // Metadados
    "URL":                    "",  // preenchido via Object.assign em enriquecerComXML
  };
}

// ------------------------------------------------------------------
// Utilitário de situação
// ------------------------------------------------------------------

function parseSituacao(cell) {
  const img = cell.querySelector("img");
  if (img) {
    const titulo = img.getAttribute("data-original-title") || "";
    if (titulo === "NFS-e emitida")   return "Normal";
    if (titulo === "NFS-e cancelada") return "Cancelada";
    return titulo;
  }
  return cell.innerText.trim();
}

// ------------------------------------------------------------------
// Gera CSV e baixa
// ------------------------------------------------------------------

const HEADERS_SIMPLES = [
  "Geração", "Emitida Para", "Competência", "Município Emissor", "Preço Serviço (R$)", "Situação",
];

const HEADERS_COMPLETO = [
  // Colunas base
  "Geração", "Emitida Para", "Competência", "Município Emissor", "Preço Serviço (R$)", "Situação",
  // Identificação
  "Número NFS-e", "Chave de Acesso", "Situação NFS-e", "Número DPS",
  "Série", "Data Emissão", "Data Competência", "Localidade Incidência",
  // Prestador
  "CNPJ/CPF Prestador", "Nome Prestador",
  "Simples Nacional", "Regime Apuração SN", "Regime Esp. Tributação",
  // Tomador
  "CNPJ/CPF Tomador", "Nome Tomador", "Email Tomador",
  "Logradouro Tom.", "Número End. Tom.", "Bairro Tom.", "CEP Tom.", "Município Tom.",
  // Serviço
  "Cód. Serviço", "Cód. Trib. Municipal", "Cód. NBS",
  "Desc. Tributação Nac.", "Desc. Tributação Mun.", "Desc. NBS", "Discriminação",
  // Valores
  "Valor Serviço", "Desc. Incondicionado", "Desc. Condicionado",
  "DED/RED (%)", "Valor DED/RED",
  "Base de Cálculo", "Alíquota ISS (%)", "Tipo Ret. ISSQN", "Valor ISSQN",
  // PIS/COFINS
  "CST PIS/COFINS", "Base Cálc. PIS/COFINS",
  "Alíquota PIS (%)", "Alíquota COFINS (%)", "Valor PIS", "Valor COFINS",
  "Tipo Ret. PIS/COFINS",
  // Retenções
  "Retenção CP", "Retenção IRRF", "Retenção CSLL",
  // Totais
  "Valor Total Retenções", "Valor Líquido",
  // Metadados
  "URL",
];

function baixarCSV(records, di, df, completo) {
  const headers = completo ? HEADERS_COMPLETO : HEADERS_SIMPLES;
  const escape  = v => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const linhas  = [
    headers.join(";"),
    ...records.map(r => headers.map(h => escape(r[h])).join(";")),
  ];
  const bom  = "\uFEFF";
  const blob = new Blob([bom + linhas.join("\r\n")], { type: "text/csv;charset=utf-8;" });
  const url  = URL.createObjectURL(blob);
  const sufixo = completo ? "_completo" : "";
  const nome = `NFSe_${di}_a_${df}${sufixo}.csv`.replace(/\//g, "-");
  chrome.downloads.download({ url, filename: nome, saveAs: false });
}

// ------------------------------------------------------------------
// Utilitários
// ------------------------------------------------------------------

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
function fmtISO(d) { return d.toISOString().slice(0, 10); }
function isoParaBR(iso) { const [y, m, d] = iso.split("-"); return `${d}/${m}/${y}`; }
