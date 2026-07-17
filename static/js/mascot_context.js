// ═══════════════════════════════════════════
// CONTEXTUAL MASCOT MESSAGES — BUBBL.OOO
// ═══════════════════════════════════════════
// Shows page-aware one-liners near the mascot that change based on
// what the user is currently doing. Makes the mascot feel alive and
// aware of the user's position in the product.
//
// Tied to sprite states:
//   idle → no message (or light contextual)
//   hover → sometimes a light line
//   thinking → processing messages
//   talking → completion messages
//   rolling → no text

const MascotContext = {
  element: null,
  currentMessage: "",
  hideTimer: null,
  shownMessages: new Set(), // Track shown messages to avoid repetition

  init() {
    // Create the message bubble element
    const container = document.getElementById("sprite-ask-container");
    if (!container) return;

    const bubble = document.createElement("div");
    bubble.id = "mascot-context-msg";
    bubble.className = "mascot-msg-bubble";
    container.insertBefore(bubble, container.firstChild);
    this.element = bubble;

    // Determine context and show initial message (after short delay)
    setTimeout(() => this._showPageMessage(), 800);
  },

  // Show a message with optional auto-hide
  show(text, duration) {
    if (!this.element) return;
    if (!text) return;

    this.element.textContent = text;
    this.element.classList.add("visible");
    this.currentMessage = text;

    clearTimeout(this.hideTimer);
    if (duration) {
      this.hideTimer = setTimeout(() => this.hide(), duration);
    }
  },

  hide() {
    if (!this.element) return;
    this.element.classList.remove("visible");
    this.currentMessage = "";
  },

  // Show a message only once per session
  showOnce(key, text, duration) {
    if (this.shownMessages.has(key)) return;
    this.shownMessages.add(key);
    this.show(text, duration);
  },

  // Determine message based on current page
  _showPageMessage() {
    const path = window.location.pathname;
    const hasSession = !!document.querySelector("[data-user-logged-in]") || 
                       path.includes("/dashboard") || path.includes("/admin") || 
                       path.includes("/leads") || path.includes("/conversations") ||
                       path.includes("/profile") || path.includes("/pricing");

    // --- DASHBOARD ---
    if (path === "/dashboard") {
      const botCards = document.querySelectorAll(".bot-card");
      if (botCards.length === 0) {
        this.show("Let's build your first agent.", 8000);
      } else {
        const greetings = ["Good to see you again.", "Welcome back.", "What are we building today?"];
        this.showOnce("dashboard_greet", greetings[Math.floor(Math.random() * greetings.length)], 6000);
      }
      return;
    }

    // --- CREATE PIPELINE ---
    if (path.includes("/create_pipeline")) {
      this.show("Give me a website and I'll start learning.", 7000);
      this._watchPipeline();
      return;
    }

    // --- EDIT BOT ---
    if (path.includes("/edit_bot")) {
      this.showOnce("edit_bot", "Add anything your agent should know.", 6000);
      return;
    }

    // --- LEADS ---
    if (path === "/leads") {
      const leadRows = document.querySelectorAll("table tbody tr, .lead-row");
      if (leadRows.length === 0) {
        this.show("Your captured leads will appear here.", 7000);
      } else if (leadRows.length === 1) {
        this.showOnce("first_lead", "You got your first lead! \ud83c\udf89", 6000);
      }
      return;
    }

    // --- CONVERSATIONS ---
    if (path === "/conversations") {
      this.showOnce("conversations", "Here's what your visitors are saying.", 6000);
      return;
    }

    // --- PRICING ---
    if (path === "/pricing") {
      this.showOnce("pricing", "Pick a plan that fits your needs.", 6000);
      return;
    }

    // --- PROFILE ---
    if (path === "/profile") {
      this.showOnce("profile", "Your account at a glance.", 5000);
      return;
    }

    // --- INTEGRATE ---
    if (path.includes("/integrate")) {
      this.show("Copy this code to your website. Done.", 7000);
      return;
    }

    // --- LOGIN/REGISTER (not logged in) ---
    if (path === "/login") {
      this.showOnce("login", "Welcome back.", 5000);
      return;
    }
    if (path === "/register") {
      this.showOnce("register", "Let's get you set up.", 5000);
      return;
    }
  },

  // Watch the pipeline page for state changes
  _watchPipeline() {
    // Listen for tab switches in the create pipeline
    const observer = new MutationObserver(() => {
      const activeTab = document.querySelector(".cb-tab.active");
      if (!activeTab) return;
      const tabText = activeTab.textContent.trim().toLowerCase();

      if (tabText.includes("knowledge")) {
        this.showOnce("kb_tab", "Add anything your agent should know.", 6000);
      } else if (tabText.includes("interface") || tabText.includes("ui")) {
        this.showOnce("ui_tab", "Now let's make your agent look like you.", 6000);
      } else if (tabText.includes("lead") || tabText.includes("settings")) {
        this.showOnce("lead_tab", "Choose when to ask for contact details.", 6000);
      }
    });

    const sidebar = document.querySelector(".cb-sidebar");
    if (sidebar) {
      observer.observe(sidebar, { subtree: true, attributes: true, attributeFilter: ["class"] });
    }
  },

  // Called externally when specific events happen
  onEvent(eventName) {
    switch (eventName) {
      case "scrape_started":
        this.show("Reading your website\u2026", null);
        break;
      case "scrape_done":
        this.show("Got it. I found your content.", 5000);
        break;
      case "scrape_failed":
        this.show("Hmm, I couldn't read that website.", 6000);
        break;
      case "file_uploading":
        this.show("Reading your file\u2026", null);
        break;
      case "file_done":
        this.show("Nice. I've added that to the knowledge base.", 5000);
        break;
      case "file_failed":
        this.show("I couldn't read that one.", 6000);
        break;
      case "bot_creating":
        this.show("Putting everything together\u2026", null);
        break;
      case "bot_created":
        this.show("Your agent is ready!", 4000);
        setTimeout(() => this.show("Go say hello.", 5000), 4500);
        break;
      case "qa_added":
        this.show("Perfect. I'll remember that answer.", 5000);
        break;
      case "thinking":
        this.show("Thinking\u2026", null);
        break;
      case "talking":
        this.show("", null);
        this.hide();
        break;
      case "idle":
        this.hide();
        break;
    }
  },
};

// --- CSS for the message bubble ---
(function() {
  const style = document.createElement("style");
  style.textContent = `
    .mascot-msg-bubble {
      position: absolute;
      bottom: 100%;
      right: 0;
      margin-bottom: 8px;
      background: #fff;
      color: #1a1008;
      font-size: 12px;
      font-weight: 500;
      font-family: 'Outfit', sans-serif;
      padding: 8px 14px;
      border-radius: 12px 12px 4px 12px;
      box-shadow: 0 4px 16px rgba(0,0,0,0.08), 0 1px 3px rgba(0,0,0,0.04);
      white-space: nowrap;
      opacity: 0;
      transform: translateY(6px) scale(0.95);
      transition: opacity 0.3s ease, transform 0.3s ease;
      pointer-events: none;
      z-index: 100;
      max-width: 240px;
      white-space: normal;
      line-height: 1.4;
    }
    .mascot-msg-bubble.visible {
      opacity: 1;
      transform: translateY(0) scale(1);
    }
    /* Hide on mobile — sprite is static there */
    @media (max-width: 768px) {
      .mascot-msg-bubble { display: none; }
    }
  `;
  document.head.appendChild(style);
})();

// Init on DOM ready
document.addEventListener("DOMContentLoaded", () => MascotContext.init());
window.MascotContext = MascotContext;
