(function () {
  // 1. Find the bot ID (Checks for React/Next.js window variable FIRST, then fallback)
  const currentScript = document.currentScript;
  const botId =
    window.BOTFACTORY_ID ||
    (currentScript && currentScript.getAttribute("data-bot-id"));

  if (!botId) {
    console.error(
      "BotFactory Error: No Bot ID found. Please ensure window.BOTFACTORY_ID is set.",
    );
    return;
  }

  const hostUrl =
    window.CONFIG.HOST_URL || "https://chatbot-c53nl.ondigitalocean.app/";

  // 3. Build and inject the secure iframe
  const iframe = document.createElement("iframe");
  iframe.src = `${hostUrl}/embed/${botId}`;

  // Widget Styling
  iframe.style.position = "fixed";
  iframe.style.bottom = "0";
  iframe.style.right = "0";
  iframe.style.width = "450px";
  iframe.style.height = "800px";
  iframe.style.border = "none";
  iframe.style.backgroundColor = "transparent";
  iframe.allowTransparency = "true";
  iframe.style.zIndex = "2147483647";

  document.body.appendChild(iframe);
})();
