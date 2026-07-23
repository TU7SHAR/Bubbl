// ═══════════════════════════════════════════
// CHAT PERSISTENCE — Survives page navigation AND multiple tabs
// ═══════════════════════════════════════════
// Uses localStorage (shared across ALL tabs on the same origin) keyed by bot_id.
// This means:
//   - Admin on app.bubbl.ooo: chat persists across Dashboard/Leads/Billing tabs
//   - Embed iframe (origin = app.bubbl.ooo): chat persists across ALL pages on
//     any client website because every iframe shares the same localStorage.
//   - Lead captured once? Never asked again (until storage is cleared).
//   - Expires after 24 hours to prevent stale conversations.

const CHAT_EXPIRY_MS = 24 * 60 * 60 * 1000; // 24 hours

function _chatStorageKey() {
  const botId = window.EMBEDDED_BOT_ID || "platform";
  return "bubbl_chat_" + botId;
}

function saveChatState() {
  const display = document.getElementById("chat-display");
  const state = {
    history: chatHistory,
    leadCaptured: leadCaptured,
    leadId: window.BUBBL_LEAD_ID || null,
    messages: display ? display.innerHTML : "",
    chatOpen: !document.getElementById("chat-window-popup").classList.contains("hidden"),
    savedAt: Date.now(),
  };
  try {
    localStorage.setItem(_chatStorageKey(), JSON.stringify(state));
  } catch (e) { /* Storage full or unavailable */ }
}

function restoreChatState() {
  try {
    const raw = localStorage.getItem(_chatStorageKey());
    if (!raw) return false;

    const state = JSON.parse(raw);
    if (!state || !state.history || state.history.length === 0) return false;

    // Expire after 24 hours — start fresh conversation
    if (state.savedAt && (Date.now() - state.savedAt) > CHAT_EXPIRY_MS) {
      localStorage.removeItem(_chatStorageKey());
      return false;
    }

    // Restore JS state
    chatHistory = state.history || [];
    leadCaptured = state.leadCaptured || false;
    if (state.leadId) window.BUBBL_LEAD_ID = state.leadId;

    // Restore rendered messages
    const display = document.getElementById("chat-display");
    if (display && state.messages) {
      display.innerHTML = state.messages;
      display.scrollTop = display.scrollHeight;
    }

    // Don't auto-open chat on page load from localStorage
    // (prevents chat from popping open on every new tab)

    return true;
  } catch (e) {
    return false;
  }
}

// Apply a persisted chat state (from localStorage) into THIS tab.
// Used by cross-tab sync so every tab mirrors the full conversation.
function applyChatStateFromStorage(raw) {
  // Never clobber a reply we're actively streaming in THIS tab.
  if (streamingBotDiv) return;
  try {
    const state = JSON.parse(raw);
    if (!state) return;
    if (Array.isArray(state.history)) chatHistory = state.history;
    if (state.leadCaptured) leadCaptured = true;
    if (state.leadId) window.BUBBL_LEAD_ID = state.leadId;
    const display = document.getElementById("chat-display");
    if (display && typeof state.messages === "string") {
      display.innerHTML = state.messages;
      display.scrollTop = display.scrollHeight;
    }
  } catch (err) { /* ignore parse errors */ }
}

// Sync across tabs — the browser fires this in OTHER tabs when one tab writes
// to localStorage. Unlike the socket 'sync_chat' signal (which can arrive
// before the sender finishes its typing animation + save), this fires with the
// correct timing: only AFTER the sending tab has persisted the final reply.
// So we re-render the full conversation here, not just the lead state.
window.addEventListener("storage", function(e) {
  if (e.key === _chatStorageKey() && e.newValue) {
    applyChatStateFromStorage(e.newValue);
  }
});

// Restore on page load
document.addEventListener("DOMContentLoaded", function() {
  restoreChatState();
});

let chatHistory = [];
let leadCaptured = false;
let pendingMessage = "";

// Helper to generate dynamic custom fields from JSON
function getCustomFieldsHTML(prefix) {
  if (
    !window.CUSTOM_FIELDS ||
    window.CUSTOM_FIELDS === "[]" ||
    window.CUSTOM_FIELDS === ""
  )
    return "";

  try {
    const fields = JSON.parse(window.CUSTOM_FIELDS);
    return fields
      .map((f) => {
        if (!f.name.trim()) return "";
        const isReq = f.required ? "required" : "";
        const star = f.required ? "* " : "";
        const safeId = f.name.replace(/[^a-zA-Z0-9]/g, ""); // Removes spaces/symbols for HTML IDs

        return `
                <input 
                    type="${f.type}" 
                    id="${prefix}-custom-${safeId}" 
                    data-name="${f.name}" 
                    data-required="${f.required}"
                    class="lead-input dynamic-custom-field" 
                    placeholder="${star}${f.name}">
            `;
      })
      .join("");
  } catch (e) {
    console.error("Error parsing custom fields:", e);
    return "";
  }
}

function toggleChat() {
  const chatPopup = document.getElementById("chat-window-popup");
  const spriteContainer = document.getElementById("sprite-ask-container");

  if (chatPopup.classList.contains("hidden")) {
    // 1. Make it physically present first
    chatPopup.classList.remove("hidden");
    if (spriteContainer) spriteContainer.classList.add("chat-open");

    // 2. Animate it in smoothly
    gsap.fromTo(
      chatPopup,
      { opacity: 0, scale: 0.8, y: 30 },
      { opacity: 1, scale: 1, y: 0, duration: 0.4, ease: "back.out(1.2)" },
    );

    if (window.LEAD_TIMING === "gatekeeper" && !leadCaptured) {
      renderGatekeeperForm();
    }
    saveChatState();
  } else {
    // 1. Animate it out smoothly
    gsap.to(chatPopup, {
      opacity: 0,
      scale: 0.8,
      y: 30,
      duration: 0.3,
      ease: "power2.in",
      onComplete: () => {
        // 2. Hide it fully ONLY after the animation finishes
        chatPopup.classList.add("hidden");
        if (spriteContainer) spriteContainer.classList.remove("chat-open");
        saveChatState();
      },
    });
  }
}

function renderGatekeeperForm() {
  if (document.getElementById("gatekeeper-overlay")) return;

  const display = document.getElementById("chat-window-popup");
  const overlay = document.createElement("div");
  overlay.id = "gatekeeper-overlay";
  overlay.className = "lead-overlay-container";

  overlay.innerHTML = `
        <div class="lead-form-card" id="gk-form-wrapper">
            <h3 style="margin-top:0; color:#111827; text-align:center; font-family:'Bricolage Grotesque', sans-serif;">Welcome!</h3>
            <p style="font-size:13px; color:#6b7280; text-align:center; margin-bottom:20px;">Please share your details to continue</p>
            <input type="text" id="gk-name" class="lead-input" placeholder="* Your full name">
            <input type="email" id="gk-email" class="lead-input" placeholder="* Email address">
            <input type="text" id="gk-phone" class="lead-input" placeholder="Mobile number (Optional)">
            
            ${getCustomFieldsHTML("gk")} <!-- Injects custom fields here -->
            
            <button id="gk-btn" class="lead-submit-btn" onclick="submitLeadForm('gk')">Continue</button>
        </div>
    `;
  display.appendChild(overlay);
}

function renderInChatForm() {
  if (document.getElementById("in-chat-form-wrapper")) return;

  const display = document.getElementById("chat-display");
  const formDiv = document.createElement("div");
  formDiv.id = "in-chat-form-wrapper";
  formDiv.className = "in-chat-form-container";

  formDiv.innerHTML = `
        <input type="text" id="ic-name" class="lead-input" placeholder="* Name">
        <input type="email" id="ic-email" class="lead-input" placeholder="* Email">
        <input type="text" id="ic-phone" class="lead-input" placeholder="Phone (Optional)">
        
        ${getCustomFieldsHTML("ic")} <!-- Injects custom fields here -->
        
        <button id="ic-btn" class="lead-submit-btn" onclick="submitLeadForm('ic')">Submit</button>
    `;
  display.appendChild(formDiv);
  display.scrollTop = display.scrollHeight;

  setInputState(true);
}

async function submitLeadForm(prefix) {
  const name = document.getElementById(`${prefix}-name`).value.trim();
  const email = document.getElementById(`${prefix}-email`).value.trim();
  const phone = document.getElementById(`${prefix}-phone`).value.trim();
  const botId = window.EMBEDDED_BOT_ID;

  if (!name || !email) {
    showModal("Name and email are required.", "error");
    return;
  }

  // Gather Custom Data dynamically
  let customData = {};
  const wrapperId =
    prefix === "gk" ? "gk-form-wrapper" : "in-chat-form-wrapper";
  const wrapper = document.getElementById(wrapperId);

  if (wrapper) {
    wrapper.querySelectorAll(".dynamic-custom-field").forEach((input) => {
      if (input.value.trim()) {
        customData[input.dataset.name] = input.value.trim();
      }
    });
  }

  const payload = {
    bot_id: botId,
    name: name,
    email: email,
    phone: phone,
    custom_data: customData,
  };

  const btn = document.getElementById(`${prefix}-btn`);
  btn.innerText = "Saving...";
  btn.disabled = true;

  try {
    const response = await fetch("/api/lead", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await response.json();

    if (data.lead_id) {
      window.BUBBL_LEAD_ID = data.lead_id;
      // --- FUNNEL EVENT: Lead Captured ---
      if (typeof BubblAnalytics !== 'undefined') BubblAnalytics.trackLeadCaptured(window.EMBEDDED_BOT_ID || 'unknown');
    }

    if (response.ok) {
      leadCaptured = true;
      saveChatState();
      if (prefix === "gk") {
        document.getElementById("gatekeeper-overlay").remove();
        if (pendingMessage) {
          const input = document.getElementById("user-input");
          input.value = pendingMessage;
          pendingMessage = "";
          sendMessage();
        }
      } else {
        document.getElementById("in-chat-form-wrapper").remove();
        appendBotMessage("Thank you! Your details have been received.");
        setInputState(false);
      }
    } else {
      showModal(data.error || "There was an error saving your details.", "error");
      btn.innerText = "Submit";
      btn.disabled = false;
    }
  } catch (error) {
    console.error("Submission Error:", error);
    btn.innerText = "Submit";
    btn.disabled = false;
  }
}

function appendUserMessage(msg) {
  const display = document.getElementById("chat-display");
  const userDiv = document.createElement("div");
  userDiv.className = "msg user";
  userDiv.innerText = msg;
  display.appendChild(userDiv);
  display.scrollTop = display.scrollHeight;
}

// ═══════════════════════════════════════════
// AUTO-LINKIFY — Detect URLs and emails in bot text and make them clickable
// ═══════════════════════════════════════════
function linkify(text) {
  /**
   * Takes plain text and returns HTML with URLs/emails wrapped in <a href> tags.
   * - URLs: http(s)://... or www.something.tld (auto-prefixed with https://)
   * - Emails: user@domain.tld → mailto: links
   * Safe: escapes HTML entities first to prevent XSS, then adds only <a> tags.
   */
  // 1. Escape HTML entities so user/bot text can't inject arbitrary tags
  var escaped = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");

  // 2. URL regex — matches http(s)://... and www.something...
  //    Stops at whitespace, quotes, or trailing punctuation like ) . , ; that aren't part of the URL
  var urlRegex = /(?:https?:\/\/|www\.)[^\s<>"']+[^\s<>"'.,;:!?\)]/gi;

  // 3. Email regex — simple but covers standard addresses
  var emailRegex = /[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}/g;

  // Replace emails first (so URLs containing @ don't get double-matched)
  escaped = escaped.replace(emailRegex, function(match) {
    return '<a href="mailto:' + match + '" target="_blank" rel="noopener noreferrer" class="bubbl-inline-link">' + match + '</a>';
  });

  // Replace URLs
  escaped = escaped.replace(urlRegex, function(match) {
    var href = match;
    if (href.indexOf("http") !== 0) href = "https://" + href;
    return '<a href="' + href + '" target="_blank" rel="noopener noreferrer" class="bubbl-inline-link">' + match + '</a>';
  });

  return escaped;
}

function parseButtons(text) {
  /**
   * Extracts [[BUTTONS: category:Label|URL, ...]] from bot response.
   * Returns { cleanText, buttons[] } where buttons have { category, label, url }.
   */
  const match = text.match(/\[\[BUTTONS:\s*(.*?)\]\]/s);
  if (!match) return { cleanText: text, buttons: [] };

  const cleanText = text.replace(/\s*\[\[BUTTONS:.*?\]\]\s*/s, "").trim();
  const raw = match[1].trim();
  const buttons = [];

  // Split by comma, but be careful of URLs containing commas (unlikely but safe)
  const parts = raw.split(/,\s*(?=[a-z]+:)/);
  for (const part of parts) {
    const btnMatch = part.trim().match(/^(\w+):(.+?)\|(.+)$/);
    if (btnMatch) {
      buttons.push({
        category: btnMatch[1].toLowerCase(),
        label: btnMatch[2].trim(),
        url: btnMatch[3].trim(),
      });
    }
  }

  return { cleanText, buttons };
}

function renderButtons(buttons, container) {
  /**
   * Renders an array of button objects as styled pill buttons below a message.
   * Each button opens its URL in a new tab.
   */
  if (!buttons || buttons.length === 0) return;

  const btnRow = document.createElement("div");
  btnRow.className = "bubbl-btn-row";

  for (const btn of buttons) {
    const anchor = document.createElement("a");
    anchor.href = btn.url;
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
    anchor.className = "bubbl-btn bubbl-btn--" + btn.category;
    anchor.innerHTML = btn.label + ' <span class="bubbl-btn-arrow">\u2197</span>';
    btnRow.appendChild(anchor);
  }

  container.appendChild(btnRow);
}

function appendBotMessage(msg) {
  const display = document.getElementById("chat-display");

  // Parse buttons from the message (if any)
  const { cleanText, buttons } = parseButtons(msg);

  // Render the text message with auto-linked URLs/emails
  if (cleanText) {
    const botDiv = document.createElement("div");
    botDiv.className = "msg bot";
    botDiv.innerHTML = linkify(cleanText);
    display.appendChild(botDiv);
  }

  // Render buttons below the message (separate container for flex layout)
  if (buttons.length > 0) {
    renderButtons(buttons, display);
  }

  display.scrollTop = display.scrollHeight;
}

function showTypingIndicator() {
  const display = document.getElementById("chat-display");
  const typingDiv = document.createElement("div");
  typingDiv.id = "typing";
  typingDiv.className = "msg bot";
  typingDiv.innerText = "...";
  display.appendChild(typingDiv);
  display.scrollTop = display.scrollHeight;
}

function removeTypingIndicator() {
  const typing = document.getElementById("typing");
  if (typing) typing.remove();
}

function setInputState(disabled) {
  const input = document.getElementById("user-input");
  const sendButton = document.getElementById("send-btn-icon");

  if (input) {
    // Input field stays enabled (user can type next message while bot responds)
    // Only the send button is disabled
    input.disabled = false;
    if (!disabled) {
      input.focus();
    }
  }
  if (sendButton) {
    sendButton.disabled = disabled;
    sendButton.style.opacity = disabled ? "0.5" : "1";
    sendButton.style.cursor = disabled ? "not-allowed" : "pointer";
  }
}

// ═══════════════════════════════════════════
// WEBSOCKET CONNECTION — Real-time streaming
// ═══════════════════════════════════════════
// Connects via Socket.IO for streaming AI responses chunk-by-chunk.
// Falls back to HTTP POST (/api/chat) if WebSocket is unavailable.

let socket = null;
let useWebSocket = false;
let streamingBotDiv = null; // Reference to the bot message being streamed

function initWebSocket() {
  // Only init if socket.io client is loaded (base.html includes it)
  if (typeof io === 'undefined') {
    console.log("[chat] socket.io not loaded, using HTTP fallback");
    useWebSocket = false;
    return;
  }

  try {
    socket = io({
      transports: ['websocket', 'polling'],  // True WebSocket with polling fallback
      reconnection: true,
      reconnectionAttempts: 5,
      reconnectionDelay: 2000,
    });

    socket.on('connect', function() {
      console.log("[chat] WebSocket connected:", socket.id);
      useWebSocket = true;
      
      // Join the chat room for multi-tab sync
      var sessionId = window._chatSessionId || localStorage.getItem('bubbl_ws_session') || null;
      if (!sessionId) {
        sessionId = 'ws_' + Math.random().toString(36).substr(2, 9);
        localStorage.setItem('bubbl_ws_session', sessionId);
      }
      window._chatSessionId = sessionId;
      socket.emit('join_chat', { session_id: sessionId });
    });

    socket.on('room_joined', function(data) {
      console.log("[chat] Multi-tab room joined:", data.session_id);
    });

    // --- SYNC: Another tab sent a message — reload from localStorage ---
    // Note: this can arrive before the sender has persisted its reply, so it
    // may render a partial state. The native 'storage' event (above) corrects
    // it once the sender actually saves the final reply.
    socket.on('sync_chat', function(data) {
      console.log("[chat] Syncing from other tab...");
      var raw = localStorage.getItem(_chatStorageKey());
      if (raw) applyChatStateFromStorage(raw);
    });

    socket.on('disconnect', function() {
      console.log("[chat] WebSocket disconnected");
      useWebSocket = false;
    });

    socket.on('connect_error', function(err) {
      console.log("[chat] WebSocket connection failed, using HTTP fallback");
      useWebSocket = false;
    });

    // --- STREAMING: Receive chunks as the AI generates them ---
    // Characters are queued and rendered with a typing delay for smooth animation
    let streamQueue = [];
    let streamInterval = null;

    function processStreamQueue() {
      if (streamQueue.length === 0) {
        clearInterval(streamInterval);
        streamInterval = null;
        return;
      }
      if (!streamingBotDiv) return;

      // Render 2-3 characters at a time for natural typing speed
      const chars = streamQueue.splice(0, 2).join('');
      streamingBotDiv.innerText += chars;
      const display = document.getElementById("chat-display");
      display.scrollTop = display.scrollHeight;
    }

    socket.on('chat_chunk', function(data) {
      if (!streamingBotDiv) {
        // First chunk — remove typing indicator and create the bot message
        removeTypingIndicator();
        const display = document.getElementById("chat-display");
        streamingBotDiv = document.createElement("div");
        streamingBotDiv.className = "msg bot";
        streamingBotDiv.innerText = "";
        display.appendChild(streamingBotDiv);

        if (window.SpriteBot) SpriteBot.setState("talking");
      }
      // Queue characters for smooth rendering
      for (const char of data.text) {
        streamQueue.push(char);
      }
      // Start the rendering interval if not already running
      if (!streamInterval) {
        streamInterval = setInterval(processStreamQueue, 20); // 20ms per 2 chars = ~100 chars/sec
      }
    });

    // --- COMPLETE: Final event after all chunks are sent ---
    socket.on('chat_complete', function(data) {
      // Wait for the typing queue to finish before finalizing
      function finalize() {
        if (streamQueue.length > 0) {
          setTimeout(finalize, 50);
          return;
        }
        if (streamInterval) {
          clearInterval(streamInterval);
          streamInterval = null;
        }

        const fullResponse = data.response || "";
        const leadId = data.lead_id;

        // Handle lead capture
        if (leadId) {
          window.BUBBL_LEAD_ID = leadId;
          if (typeof BubblAnalytics !== 'undefined') BubblAnalytics.trackLeadCaptured(window.EMBEDDED_BOT_ID || 'unknown');
        }

        // Keep the streaming div as the final message (don't remove + re-render)
        // Just update its text with the clean response (without [[LEAD:...]] tags)
        let replyText = fullResponse.replace("[SHOW_FORM]", "").trim();
        
        if (streamingBotDiv) {
          // Check for buttons — if present, replace with parsed version
          const { cleanText, buttons } = parseButtons(replyText);
          // Use innerHTML with linkify to make URLs/emails clickable
          streamingBotDiv.innerHTML = linkify(cleanText);
          if (buttons.length > 0) {
            const display = document.getElementById("chat-display");
            renderButtons(buttons, display);
          }
          streamingBotDiv = null;
        } else {
          removeTypingIndicator();
          appendBotMessage(replyText);
        }

        // Handle [SHOW_FORM]
        if (fullResponse.includes("[SHOW_FORM]") && !leadCaptured) {
          renderInChatForm();
        }

        chatHistory.push({ role: "bot", text: replyText });
        setInputState(false);
        saveChatState();

        if (window.SpriteBot) {
          SpriteBot.setState("talking");
          setTimeout(() => {
            if (SpriteBot.currentState === "talking") SpriteBot.setState("idle");
          }, 8000);
        }
      }
      finalize();
    });

    // --- ERROR ---
    socket.on('chat_error', function(data) {
      removeTypingIndicator();
      streamingBotDiv = null;
      if (window.SpriteBot) SpriteBot.setState("idle");
      appendBotMessage("SYSTEM ERROR: " + (data.error || "Unknown error"));
      setInputState(false);
    });

  } catch (e) {
    console.log("[chat] WebSocket init failed:", e);
    useWebSocket = false;
  }
}

// Initialize WebSocket on page load
document.addEventListener("DOMContentLoaded", function() {
  initWebSocket();
});


async function sendMessage() {
  const input = document.getElementById("user-input");
  const sendButton = document.getElementById("send-btn-icon");
  const rawMsg = input.value.trim();
  if (!rawMsg) return;
  
  // Don't send if bot is still responding
  if (sendButton && sendButton.disabled) return;

  // Gatekeeper Failsafe
  if (window.LEAD_TIMING === "gatekeeper" && !leadCaptured) {
    pendingMessage = rawMsg;
    renderGatekeeperForm();
    return;
  }

  appendUserMessage(rawMsg);
  chatHistory.push({ role: "user", text: rawMsg });
  input.value = ""; // Clear input immediately after sending
  saveChatState();

  setInputState(true);
  if (window.SpriteBot) SpriteBot.setState("thinking");
  showTypingIndicator();

  const payload = {
    message: rawMsg,
    history: chatHistory,
    session_id: window._chatSessionId || null,
  };
  if (window.EMBEDDED_BOT_ID) payload.bot_id = window.EMBEDDED_BOT_ID;

  // --- USE WEBSOCKET (streaming) if available ---
  if (useWebSocket && socket && socket.connected) {
    streamingBotDiv = null; // Reset streaming state
    payload.session_id = window._chatSessionId || null;
    socket.emit('chat_message', payload);
    return; // Response comes via chat_chunk + chat_complete events
  }

  // --- FALLBACK: HTTP POST (for embed widget or when WS is down) ---
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await response.json();

    if (data.lead_id) {
      window.BUBBL_LEAD_ID = data.lead_id;
      if (typeof BubblAnalytics !== 'undefined') BubblAnalytics.trackLeadCaptured(window.EMBEDDED_BOT_ID || 'unknown');
    }

    removeTypingIndicator();

    if (data.error) {
      if (window.SpriteBot) SpriteBot.setState("idle");
      appendBotMessage("SYSTEM ERROR: " + data.error);
    } else if (data.response) {
      let replyText = data.response;

      if (replyText.includes("[SHOW_FORM]") && !leadCaptured) {
        replyText = replyText.replace("[SHOW_FORM]", "").trim();
        if (replyText) {
          appendBotMessage(replyText);
          chatHistory.push({ role: "bot", text: replyText });
        }
        renderInChatForm();
        saveChatState();
      } else {
        replyText = replyText.replace("[SHOW_FORM]", "").trim();
        appendBotMessage(replyText);
        chatHistory.push({ role: "bot", text: replyText });
        setInputState(false);
        saveChatState();
      }

      if (window.SpriteBot) {
        SpriteBot.setState("talking");
        setTimeout(() => {
          if (SpriteBot.currentState === "talking") SpriteBot.setState("idle");
        }, 8000);
      }
    }
  } catch (error) {
    if (window.SpriteBot) SpriteBot.setState("idle");
    removeTypingIndicator();
    appendBotMessage("Error connecting to server.");
    setInputState(false);
  }
}
