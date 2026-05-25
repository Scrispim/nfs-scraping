const BASE = "https://www.nfse.gov.br/EmissorNacional/Notas/Emitidas";
const DELAY_MS = 500;

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

// --- Botão Buscar ---
document.getElementById("btnBuscar").addEventListener("click", async () => {
  const di = document.getElementById("dataInicio").value;
  const df = document.getElementById("dataFim").value;
  if (!di || !df) { alert("Preencha as datas."); return; }

  const diaBR = isoParaBR(di);
  const dfBR  = isoParaBR(df);

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
      const rows = await extrairPagina(diaBR, dfBR, pg);
      dadosColetados.push(...rows);
      addLog(`📄 Página ${String(pg).padStart(4)} — ${rows.length} registro(s)  (total: ${dadosColetados.length})`);
      if (pg < totalPag) await sleep(DELAY_MS);
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
  baixarCSV(dadosColetados, di, df);
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

async function extrairPagina(di, df, pg) {
  const html = await fetchPagina(di, df, pg);
  const doc  = new DOMParser().parseFromString(html, "text/html");
  const rows = [];
  doc.querySelectorAll("table tbody tr").forEach(tr => {
    const cells = tr.querySelectorAll("td");
    if (cells.length < 5) return;
    rows.push({
      "Geração":            cells[0].innerText.trim(),
      "Emitida Para":       cells[1].innerText.trim().replace(/\s+/g, " "),
      "Competência":        cells[2].innerText.trim(),
      "Município Emissor":  cells[3].innerText.trim(),
      "Preço Serviço (R$)": cells[4].innerText.trim(),
      "Situação":           cells[5] ? cells[5].innerText.trim() : "",
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
// Gera CSV e baixa
// ------------------------------------------------------------------

function baixarCSV(records, di, df) {
  const headers = ["Geração", "Emitida Para", "Competência", "Município Emissor", "Preço Serviço (R$)", "Situação"];
  const escape  = v => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const linhas  = [
    headers.join(";"),
    ...records.map(r => headers.map(h => escape(r[h])).join(";")),
  ];
  const bom  = "\uFEFF"; // BOM para o Excel reconhecer UTF-8
  const blob = new Blob([bom + linhas.join("\r\n")], { type: "text/csv;charset=utf-8;" });
  const url  = URL.createObjectURL(blob);
  const nome = `NFSe_${di}_a_${df}.csv`.replace(/\//g, "-");
  chrome.downloads.download({ url, filename: nome, saveAs: false });
}

// ------------------------------------------------------------------
// Utilitários
// ------------------------------------------------------------------

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
function fmtISO(d) { return d.toISOString().slice(0, 10); }
function isoParaBR(iso) { const [y, m, d] = iso.split("-"); return `${d}/${m}/${y}`; }
