(function () {
  // 1. Find the bot ID
  const currentScript = document.currentScript;
  const botId =
    window.BOTFACTORY_ID ||
    (currentScript && currentScript.getAttribute("data-bot-id"));

  if (!botId) {
    console.error("BotFactory Error: No Bot ID found.");
    return;
  }

  // 2. Auto-detect the host URL
  let hostUrl = "http://168.144.123.62:8080"; // Fallback
  if (currentScript && currentScript.src) {
    const urlObj = new URL(currentScript.src);
    hostUrl = urlObj.origin;
  }

  // 3. Build the secure iframe
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

  // 4. SAFELY inject the iframe (Wait for the body to exist)
  const injectWidget = () => {
    document.body.appendChild(iframe);
  };

  if (document.body) {
    injectWidget();
  } else {
    window.addEventListener("DOMContentLoaded", injectWidget);
  }
})();
