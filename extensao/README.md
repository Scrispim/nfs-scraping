# NFS-e Extrator — Extensão Chrome

Extrai notas fiscais do portal NFS-e (nfse.gov.br) e gera um arquivo CSV pronto para abrir no Excel.

Funciona direto com a sessão já aberta no Chrome — sem instalar Python, sem configuração extra.

---

## Pré-requisitos

- Google Chrome instalado
- Estar logado no portal [nfse.gov.br](https://www.nfse.gov.br/EmissorNacional/Login) em alguma aba

---

## Como instalar

1. Abra o Chrome e acesse: `chrome://extensions`
2. Ative o **Modo do desenvolvedor** (botão no canto superior direito)
3. Clique em **"Carregar sem compactação"**
4. Selecione a pasta `extensao` (a pasta que contém o arquivo `manifest.json`)
5. A extensão aparecerá na lista — clique no ícone de quebra-cabeça 🧩 na barra do Chrome e fixe a extensão

---

## Como usar

1. Faça login no portal NFS-e no Chrome
2. Clique no ícone da extensão **NFS-e Extrator** na barra do Chrome
3. Informe a **Data Inicial** e a **Data Final** (máximo 30 dias por consulta)
4. Clique em **Buscar e Baixar Excel**
5. Aguarde — o log mostra o progresso página por página
6. Ao concluir, clique em **Baixar Excel** para salvar o arquivo `.csv`
7. Abra o arquivo no Excel normalmente

---

## Observações

- O portal limita consultas a **no máximo 30 dias** por vez
- O arquivo gerado é `.csv` com separador `;` e codificação UTF-8 — compatível com Excel
- Para abrir corretamente no Excel: arquivo → importar dados → delimitado por ponto e vírgula
- A extensão só funciona quando há uma sessão ativa no portal NFS-e

---

## Estrutura dos arquivos

```
extensao/
  manifest.json   — configuração da extensão
  popup.html      — interface visual
  popup.js        — lógica de busca e geração do arquivo
  README.md       — este arquivo
```
