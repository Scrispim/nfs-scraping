// Faz o clique no ícone da extensão abrir o painel lateral (fixo do lado
// direito da janela) em vez do popup tradicional, que fecha sozinho ao
// perder o foco.
chrome.sidePanel
  .setPanelBehavior({ openPanelOnActionClick: true })
  .catch((error) => console.error(error));
