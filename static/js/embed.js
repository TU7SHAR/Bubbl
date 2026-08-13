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

  /**
   * 3. Detect whether the HOST page is dark or light.
   *
   * The iframe can only see the visitor's OS preference, which is often the
   * opposite of the site it's sitting on — a light card on a dark site looks
   * broken. So we sample the host page's real background here and pass the
   * answer along as ?theme=.
   */
  function isPainted(color) {
    if (!color || color === "transparent") return false;
    const p = color.match(/[\d.]+/g);
    if (!p || p.length < 3) return false;
    // rgba(0,0,0,0) and friends are see-through — keep walking up
    if (p.length >= 4 && parseFloat(p[3]) === 0) return false;
    return true;
  }

  function prefersDark() {
    return !!(
      window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: dark)").matches
    );
  }

  function detectHostTheme() {
    try {
      // Walk up from <body> to the first element with a painted background
      let el = document.body;
      let bg = null;
      while (el) {
        const c = window.getComputedStyle(el).backgroundColor;
        if (isPainted(c)) {
          bg = c;
          break;
        }
        el = el.parentElement;
      }

      // Nothing painted anywhere → defer to the visitor's OS preference
      if (!bg) return prefersDark() ? "dark" : "light";

      const p = bg.match(/[\d.]+/g);
      // Perceived luminance (sRGB coefficients)
      const lum = (0.2126 * +p[0] + 0.7152 * +p[1] + 0.0722 * +p[2]) / 255;
      return lum < 0.5 ? "dark" : "light";
    } catch (e) {
      return "light";
    }
  }

  // 4. Build the secure iframe
  const iframe = document.createElement("iframe");

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
  iframe.setAttribute("title", "Chat widget");

  /**
   * 5. Listen for messages from inside the iframe.
   *
   * When the promo advert renders (domain lock, unknown bot, rate limit) it
   * only needs a small card — but the iframe is 450x800 and would swallow
   * every click across that whole corner of the host page. The promo measures
   * itself and asks us to shrink to fit, or to disappear if dismissed.
   */
  window.addEventListener("message", function (event) {
    if (event.origin !== hostUrl) return; // Only trust our own iframe
    const data = event.data || {};

    if (data.type === "bubbl:promo") {
      const w = parseInt(data.width, 10);
      const h = parseInt(data.height, 10);
      if (w > 0 && h > 0) {
        iframe.style.width = Math.min(w, 450) + "px";
        iframe.style.height = Math.min(h, 800) + "px";
      }
    } else if (data.type === "bubbl:promo-dismiss") {
      if (iframe.parentNode) iframe.parentNode.removeChild(iframe);
    }
  });

  // 6. SAFELY inject the iframe (Wait for the body to exist)
  const injectWidget = () => {
    // Theme is detected here, not earlier — <body> must exist to be sampled
    iframe.src =
      hostUrl + "/embed/" + encodeURIComponent(botId) + "?theme=" + detectHostTheme();
    document.body.appendChild(iframe);
  };

  if (document.body) {
    injectWidget();
  } else {
    window.addEventListener("DOMContentLoaded", injectWidget);
  }
})();
