# NFS-e Scraping

Ferramenta para extração de notas fiscais de serviço do portal [NFS-e](https://www.nfse.gov.br) e geração de relatório Excel.

Disponível em duas formas:
- **App web** (Python + Streamlit) — para uso local com mais recursos
- **Extensão Chrome** — sem instalação, funciona em qualquer computador com Chrome

---

## Extensão Chrome

A forma mais simples de usar. Não requer Python nem nenhuma instalação além do Chrome.

### Pré-requisitos

- Google Chrome instalado
- Estar logado no portal NFS-e em alguma aba do Chrome

### Como instalar

1. Baixe ou clone este repositório
2. Abra o Chrome e acesse `chrome://extensions`
3. Ative o **Modo do desenvolvedor** (botão no canto superior direito)
4. Clique em **"Carregar sem compactação"**
5. Selecione a pasta `extensao` (a que contém o `manifest.json`)
6. Clique no ícone 🧩 na barra do Chrome e fixe a extensão **NFS-e Extrator**

### Como usar

1. Faça login no portal NFS-e no Chrome
2. Clique no ícone da extensão na barra do Chrome
3. Informe a **Data Inicial** e a **Data Final** (máximo 30 dias por consulta)
4. Clique em **Buscar e Baixar Excel**
5. Acompanhe o progresso no log — o download inicia automaticamente ao concluir
6. Abra o arquivo `.csv` gerado no Excel

---

## App Web (Python)

Interface mais completa com relatório Excel formatado e prévia dos dados na tela.

### Pré-requisitos

- Python 3.10 ou superior
- Google Chrome com sessão ativa no portal NFS-e

### Instalação

```bash
pip install -r requirements.txt
```

### Execução

**Windows** — clique duas vezes no arquivo `iniciar.bat`

**Mac/Linux** — execute no terminal:
```bash
streamlit run app.py
```

Acesse `http://localhost:8501` no browser.

### Como usar

1. Faça login no portal NFS-e no Chrome
2. Abra o app em `http://localhost:8501`
3. Informe o período desejado
4. Clique em **Buscar e Gerar Relatório**
5. Baixe o arquivo `.xlsx` ao concluir

---

## Estrutura do projeto

```
├── app.py              # Interface Streamlit
├── scraper.py          # Coleta de dados via requests + cookies do Chrome
├── report.py           # Geração de relatório Excel formatado
├── requirements.txt    # Dependências Python
├── iniciar.bat         # Script de execução para Windows
└── extensao/
    ├── manifest.json   # Configuração da extensão Chrome
    ├── popup.html      # Interface da extensão
    ├── popup.js        # Lógica de busca e download
    └── README.md       # Instruções da extensão
```

---

## Observações

- O portal NFS-e limita consultas a **30 dias por vez**
- A sessão do Chrome precisa estar ativa antes de iniciar a busca
- Certificados digitais (`.pfx`, `.p12`) estão no `.gitignore` e nunca são enviados ao repositório
