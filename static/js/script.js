/* ═══ GLOBAL MODAL (replaces all alert() calls) ═══ */
window.showModal = function(message, type) {
  type = type || 'info'; // 'info', 'error', 'success'
  var colors = { info: '#E8722A', error: '#dc2626', success: '#059669' };
  var icons = {
    info: '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="' + colors[type] + '" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    error: '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#dc2626" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
    success: '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>'
  };
  var existing = document.getElementById('global-modal-overlay');
  if (existing) existing.remove();
  var overlay = document.createElement('div');
  overlay.id = 'global-modal-overlay';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:99999;display:flex;align-items:center;justify-content:center;padding:20px;';
  overlay.innerHTML = '<div style="background:#fff;border-radius:16px;padding:32px 28px 24px;max-width:380px;width:100%;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,0.15);">' +
    '<div style="width:48px;height:48px;margin:0 auto 16px;background:' + (type==='error'?'#fef2f2':type==='success'?'#ecfdf5':'#fff7ed') + ';border-radius:50%;display:flex;align-items:center;justify-content:center;">' + icons[type] + '</div>' +
    '<p style="margin:0 0 20px;font-size:14px;color:#333;line-height:1.5;">' + message + '</p>' +
    '<button onclick="document.getElementById(\'global-modal-overlay\').remove()" style="padding:10px 28px;background:' + colors[type] + ';color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;">OK</button>' +
    '</div>';
  document.body.appendChild(overlay);
  overlay.addEventListener('click', function(e) { if (e.target === overlay) overlay.remove(); });
};

window.addEventListener("pageshow", function () {
  document.querySelectorAll('button[type="submit"]').forEach((btn) => {
    btn.disabled = false;
    btn.classList.remove("btn-disabled");
  });
});

document.addEventListener("DOMContentLoaded", () => {
  const allForms = document.querySelectorAll("form");

  allForms.forEach((form) => {
    // Skip botPipelineForm — it has its own AJAX submit handler
    if (form.id === "botPipelineForm") return;

    form.addEventListener("submit", function () {
      const submitBtn = this.querySelector('button[type="submit"]');

      if (submitBtn && !submitBtn.disabled) {
        submitBtn.disabled = true;
        submitBtn.classList.add("btn-disabled");

        const oldText = submitBtn.innerText.toUpperCase();

        if (oldText.includes("DELETE") || oldText.includes("BOT")) {
          submitBtn.innerText = "DELETING...";
        } else if (oldText.includes("CREATE") || oldText.includes("BOT")) {
          submitBtn.innerText = "CREATING...";
        } else if (oldText.includes("INITIALIZE")) {
          submitBtn.innerText = "INITIALIZING...";
        } else if (oldText.includes("LOGIN") || oldText.includes("SIGN IN")) {
          submitBtn.innerText = "AUTHENTICATING...";
        } else if (
          oldText.includes("REGISTER") ||
          oldText.includes("SIGN UP")
        ) {
          submitBtn.innerText = "CREATING ACCOUNT...";
        } else if (oldText.includes("UPLOAD") || oldText.includes("TRAIN")) {
          submitBtn.innerText = "UPLOADING...";
        } else if (oldText.includes("DECRYPT") || oldText.includes("UNLOCK")) {
          submitBtn.innerText = "DECRYPTING...";
        } else if (oldText.includes("INVITE") || oldText.includes("SEND")) {
          submitBtn.innerText = "SENDING...";
        } else {
          submitBtn.innerText = "PROCESSING...";
        }
      }
    });
  });
});

function copyDecryptionKey(key, event) {
  event.preventDefault();
  const btn = event.target;
  const originalText = btn.innerText;

  const triggerSuccessAnimation = () => {
    btn.innerText = "COPIED!";
    const originalBg = btn.style.background;
    btn.style.background = "#28a745";

    setTimeout(() => {
      btn.innerText = originalText;
      btn.style.background = originalBg;
    }, 2000);
  };

  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard
      .writeText(key)
      .then(triggerSuccessAnimation)
      .catch((err) => console.error("Copy failed", err));
  } else {
    let textArea = document.createElement("textarea");
    textArea.value = key;
    document.body.appendChild(textArea);
    textArea.select();
    try {
      document.execCommand("copy");
      triggerSuccessAnimation();
    } catch (err) {
      console.error("Fallback copy failed", err);
    }
    document.body.removeChild(textArea);
  }
}

async function startScraping(event) {
  event.preventDefault();

  const urlInput = document.getElementById("scrape_url");
  const deepCrawlInput = document.getElementById("use_deep_crawl");
  const btnScrape = document.getElementById("btn-scrape");
  const progressDiv = document.getElementById("scrape-progress");
  const statusText = document.getElementById("scrape-status-text");

  if (!urlInput || !btnScrape || !progressDiv) {
    console.warn("Scraper elements not found on this page.");
    return;
  }

  const targetUrl = urlInput.value.trim();
  const useDeepCrawl = deepCrawlInput ? deepCrawlInput.checked : false;

  if (!targetUrl) return;

  urlInput.disabled = true;
  if (deepCrawlInput) deepCrawlInput.disabled = true;
  btnScrape.disabled = true;
  btnScrape.innerText = "STARTING...";
  progressDiv.style.display = "block";

  if (statusText) {
    statusText.innerText = "SENDING TO ENGINE...";
    statusText.style.color = "var(--text-dark)";
  }

  try {
    const startResponse = await fetch("/admin/api/scrape/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: targetUrl, use_spider: useDeepCrawl }),
    });

    const startData = await startResponse.json();

    if (startData.error) throw new Error(startData.error);

    const jobId = startData.job_id;
    if (statusText) statusText.innerText = "SCRAPING IN PROGRESS...";

    const pollInterval = setInterval(async () => {
      try {
        const cacheBuster = new Date().getTime();
        const statusResponse = await fetch(
          `/admin/api/scrape/status/${jobId}?t=${cacheBuster}`,
        );
        const statusData = await statusResponse.json();

        if (statusData.status === "completed") {
          clearInterval(pollInterval);
          if (statusText) {
            statusText.innerText = "SUCCESS! KNOWLEDGE INGESTED.";
            statusText.style.color = "#28a745";
          }
          setTimeout(() => window.location.reload(), 1500);
        } else if (statusData.status === "failed") {
          clearInterval(pollInterval);
          throw new Error(statusData.error || "Scraping failed.");
        }
      } catch (pollError) {
        clearInterval(pollInterval);
        handleScrapeError(pollError.message);
      }
    }, 3000);
  } catch (error) {
    handleScrapeError(error.message);
  }

  function handleScrapeError(msg) {
    if (statusText) {
      statusText.innerText = "SCRAPE FAILED";
      statusText.style.color = "#d93025";
    }
    showModal("Error: " + msg, "error");
    urlInput.disabled = false;
    if (deepCrawlInput) deepCrawlInput.disabled = false;
    btnScrape.disabled = false;
    btnScrape.innerText = "Start Scraping";
  }
}
