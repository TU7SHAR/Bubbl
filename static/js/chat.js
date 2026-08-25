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
    // CUSTOM_FIELDS may arrive as a real array (templates now emit `| tojson`)
    // or as a JSON string (session-stored value). Accept both — previously this
    // assumed a string, and a JSON.parse failure silently dropped every field.
    let fields = window.CUSTOM_FIELDS;
    if (typeof fields === "string") {
      fields = JSON.parse(fields);
    }
    if (!Array.isArray(fields)) return "";

    return fields
      .map((f) => {
        if (!f || typeof f.name !== "string" || !f.name.trim()) return "";
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

  // Wrapper holds both the message bubble and the edit button
  const wrapper = document.createElement("div");
  wrapper.className = "msg-user-wrapper";

  const userDiv = document.createElement("div");
  userDiv.className = "msg user";
  userDiv.innerText = msg;

  // Edit button (pencil icon) — shown on hover
  const editBtn = document.createElement("button");
  editBtn.className = "msg-edit-btn";
  editBtn.title = "Edit & regenerate";
  editBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>';
  editBtn.onclick = function() { startEditMessage(wrapper, userDiv, msg); };

  wrapper.appendChild(editBtn);
  wrapper.appendChild(userDiv);
  display.appendChild(wrapper);
  display.scrollTop = display.scrollHeight;
}

function startEditMessage(wrapper, userDiv, originalMsg) {
  // Don't allow edit while bot is responding
  const sendButton = document.getElementById("send-btn-icon");
  if (sendButton && sendButton.disabled) return;

  // Replace the message bubble with an editable input
  const editContainer = document.createElement("div");
  editContainer.className = "msg-edit-container";
  editContainer.innerHTML = `
    <textarea class="msg-edit-input" rows="2">${originalMsg}</textarea>
    <div class="msg-edit-actions">
      <button class="msg-edit-save" title="Send edited message">&#10003;</button>
      <button class="msg-edit-cancel" title="Cancel">&#10005;</button>
    </div>
  `;

  // Hide the original message and edit button
  userDiv.style.display = "none";
  const editBtn = wrapper.querySelector('.msg-edit-btn');
  if (editBtn) editBtn.style.display = "none";

  wrapper.appendChild(editContainer);

  const textarea = editContainer.querySelector('.msg-edit-input');
  textarea.focus();
  textarea.setSelectionRange(textarea.value.length, textarea.value.length);

  // Handle Enter key (without shift) to submit
  textarea.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submitEdit();
    }
  });

  editContainer.querySelector('.msg-edit-cancel').onclick = function() {
    editContainer.remove();
    userDiv.style.display = "";
    if (editBtn) editBtn.style.display = "";
  };

  editContainer.querySelector('.msg-edit-save').onclick = submitEdit;

  function submitEdit() {
    const newMsg = textarea.value.trim();
    if (!newMsg) return;

    // Remove the edit container, show the updated message
    editContainer.remove();
    userDiv.innerText = newMsg;
    userDiv.style.display = "";
    if (editBtn) editBtn.style.display = "";
    editBtn.onclick = function() { startEditMessage(wrapper, userDiv, newMsg); };

    // Remove all messages AFTER this wrapper (the bot response + any following messages)
    const display = document.getElementById("chat-display");
    let removeNext = false;
    const toRemove = [];
    for (let i = 0; i < display.children.length; i++) {
      const child = display.children[i];
      if (removeNext) {
        toRemove.push(child);
      }
      if (child === wrapper) {
        removeNext = true;
      }
    }
    toRemove.forEach(el => el.remove());

    // Update chatHistory — find this message's index and truncate after it
    const wrapperIndex = Array.from(display.children).indexOf(wrapper);
    // Count how many user messages precede this one (to find chatHistory index)
    let userMsgCount = 0;
    for (let i = 0; i < display.children.length; i++) {
      const child = display.children[i];
      if (child === wrapper) break;
      if (child.classList && child.classList.contains('msg-user-wrapper')) userMsgCount++;
    }
    // The chatHistory has alternating user/bot entries
    // Find the user entry at this position and truncate everything after
    let histIdx = 0;
    let uCount = 0;
    for (let i = 0; i < chatHistory.length; i++) {
      if (chatHistory[i].role === 'user') {
        if (uCount === userMsgCount) {
          histIdx = i;
          break;
        }
        uCount++;
      }
    }
    // Keep everything up to (but not including) this user message, then add the new one
    chatHistory = chatHistory.slice(0, histIdx);
    chatHistory.push({ role: "user", text: newMsg });

    // Decrement _botMsgIndex for removed bot messages
    _botMsgIndex = document.querySelectorAll('.msg-rating').length;

    // Regenerate the response
    saveChatState();
    setInputState(true);
    if (window.SpriteBot) SpriteBot.setState("thinking");
    showTypingIndicator();

    const payload = {
      message: newMsg,
      history: chatHistory,
      session_id: window._chatSessionId || null,
    };
    if (window.EMBEDDED_BOT_ID) payload.bot_id = window.EMBEDDED_BOT_ID;

    // Use WebSocket if available
    if (useWebSocket && socket && socket.connected) {
      streamingBotDiv = null;
      socket.emit('chat_message', payload);
    } else {
      // HTTP fallback
      fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      .then(res => res.json())
      .then(data => {
        removeTypingIndicator();
        if (data.error) {
          appendBotMessage("SYSTEM ERROR: " + data.error);
        } else if (data.response) {
          let replyText = data.response.replace("[SHOW_FORM]", "").trim();
          appendBotMessage(replyText);
          chatHistory.push({ role: "bot", text: replyText });
          saveChatState();
        }
        setInputState(false);
        if (window.SpriteBot) SpriteBot.setState("idle");
      })
      .catch(() => {
        removeTypingIndicator();
        appendBotMessage("Error connecting to server.");
        setInputState(false);
      });
    }
  }
}

// ═══════════════════════════════════════════
// MARKDOWN RENDERER — Formats bot responses for readability
// ═══════════════════════════════════════════
function renderMarkdown(text) {
  /**
   * Lightweight markdown-to-HTML converter for bot messages.
   * Handles: tables, headers, bold, italic, lists, code blocks, blockquotes, hr.
   * XSS-safe: escapes HTML first, then applies formatting.
   */
  // 1. Escape HTML entities
  var html = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  // 2. Code blocks (``` ... ```) — must be before inline code
  html = html.replace(/```([\s\S]*?)```/g, function(m, code) {
    return '<pre><code>' + code.trim() + '</code></pre>';
  });

  // 3. Inline code (`...`)
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

  // 4. Tables (detect lines with | separators)
  html = html.replace(/((?:^|\n)\|.+\|(?:\n\|.+\|)+)/g, function(tableBlock) {
    var rows = tableBlock.trim().split('\n').filter(function(r) { return r.trim(); });
    if (rows.length < 2) return tableBlock;
    
    var tableHtml = '<table>';
    var headerDone = false;
    
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i].trim();
      // Skip separator rows (|---|---|)
      if (/^\|[\s\-:]+\|$/.test(row) || /^\|(\s*[-:]+\s*\|)+$/.test(row)) {
        headerDone = true;
        continue;
      }
      var cells = row.split('|').filter(function(c, idx, arr) { return idx > 0 && idx < arr.length - 1; });
      var tag = (!headerDone && i === 0) ? 'th' : 'td';
      tableHtml += '<tr>';
      for (var j = 0; j < cells.length; j++) {
        tableHtml += '<' + tag + '>' + cells[j].trim() + '</' + tag + '>';
      }
      tableHtml += '</tr>';
      if (tag === 'th') headerDone = true;
    }
    tableHtml += '</table>';
    return tableHtml;
  });

  // 5. Headers (### > ## > #)
  html = html.replace(/^####\s+(.+)$/gm, '<h4>$1</h4>');
  html = html.replace(/^###\s+(.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^##\s+(.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^#\s+(.+)$/gm, '<h1>$1</h1>');

  // 6. Bold (**text** or __text__)
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/__(.+?)__/g, '<strong>$1</strong>');

  // 7. Italic (*text* or _text_)
  html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  html = html.replace(/_([^_]+)_/g, '<em>$1</em>');

  // 8. Blockquotes (> text)
  html = html.replace(/^&gt;\s+(.+)$/gm, '<blockquote>$1</blockquote>');

  // 9. Horizontal rules (--- or ***)
  html = html.replace(/^(\-{3,}|\*{3,})$/gm, '<hr>');

  // 10. Unordered lists (- item or * item)
  html = html.replace(/((?:^|\n)[\-\*]\s.+)+/g, function(block) {
    var items = block.trim().split('\n');
    var listHtml = '<ul>';
    for (var i = 0; i < items.length; i++) {
      var item = items[i].replace(/^[\-\*]\s+/, '').trim();
      if (item) listHtml += '<li>' + item + '</li>';
    }
    listHtml += '</ul>';
    return listHtml;
  });

  // 11. Ordered lists (1. item, 2. item)
  html = html.replace(/((?:^|\n)\d+\.\s.+)+/g, function(block) {
    var items = block.trim().split('\n');
    var listHtml = '<ol>';
    for (var i = 0; i < items.length; i++) {
      var item = items[i].replace(/^\d+\.\s+/, '').trim();
      if (item) listHtml += '<li>' + item + '</li>';
    }
    listHtml += '</ol>';
    return listHtml;
  });

  // 12. Auto-linkify URLs and emails (same as linkify() but for already-escaped HTML)
  var urlRegex = /(?:https?:\/\/|www\.)[^\s&lt;&gt;&quot;&#39;]+[^\s&lt;&gt;&quot;&#39;.,;:!?\)]/gi;
  var emailRegex = /[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}/g;

  html = html.replace(emailRegex, function(match) {
    return '<a href="mailto:' + match + '" target="_blank" rel="noopener noreferrer" class="bubbl-inline-link">' + match + '</a>';
  });
  html = html.replace(urlRegex, function(match) {
    var href = match.replace(/&amp;/g, '&');
    if (href.indexOf("http") !== 0) href = "https://" + href;
    return '<a href="' + href + '" target="_blank" rel="noopener noreferrer" class="bubbl-inline-link">' + match + '</a>';
  });

  // 12b. Informal links WITHOUT protocol (e.g. "bubbl.ooo", "example.com/pricing").
  // Only matches a whitelist of common TLDs to avoid false positives (e.g. "e.g.", "1.5").
  // Splits on existing <a>...</a> segments so it never re-links text already inside an anchor
  // (URLs and emails were already converted above).
  var bareDomain = /\b((?:[a-zA-Z0-9\-]+\.)+(?:com|org|net|io|ooo|co|in|dev|app|ai|xyz|info|biz|me|gov|edu))(\/[^\s<]*)?/gi;
  html = html.split(/(<a\b[^>]*>[\s\S]*?<\/a>)/gi).map(function(seg) {
    if (seg.slice(0, 2).toLowerCase() === '<a') return seg;  // leave existing links untouched
    return seg.replace(bareDomain, function(m) {
      return '<a href="https://' + m + '" target="_blank" rel="noopener noreferrer" class="bubbl-inline-link">' + m + '</a>';
    });
  }).join('');

  // 13. Paragraphs — convert double newlines to <p> breaks
  html = html.replace(/\n{2,}/g, '</p><p>');
  // Single newlines within a paragraph → <br>
  html = html.replace(/\n/g, '<br>');
  // Wrap in <p> only if content is plain text (no block-level elements already present)
  var hasBlockElements = /<(table|ul|ol|pre|blockquote|h[1-4]|hr)/i.test(html);
  if (!hasBlockElements) {
    html = '<p>' + html + '</p>';
  }

  // Clean up empty paragraphs
  html = html.replace(/<p>\s*<\/p>/g, '');

  return html;
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
    // category:Label|URL   OR   category:Label|URL|#hexcolor (optional custom colour)
    const btnMatch = part.trim().match(/^(\w+):(.+?)\|([^|]+?)(?:\|(#[0-9a-fA-F]{3,8}))?$/);
    if (btnMatch) {
      buttons.push({
        category: btnMatch[1].toLowerCase(),
        label: btnMatch[2].trim(),
        url: btnMatch[3].trim(),
        color: btnMatch[4] ? btnMatch[4].trim() : null,
      });
    }
  }

  return { cleanText, buttons };
}

function renderButtons(buttons, container) {
  /**
   * Renders an array of button objects as styled pill buttons below a message.
   * Each button opens its URL in a new tab.
   * Uses custom colors from managed links (fetched on init) when available.
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

    // Apply custom color: first check if bot AI provided one, then check
    // the managed links color map (fetched from /admin/api/bot_link_colors)
    var customColor = btn.color || null;
    if (!customColor && window._botLinkColors && window._botLinkColors[btn.url]) {
      customColor = window._botLinkColors[btn.url].color;
    }
    if (customColor) {
      anchor.style.background = customColor;
      anchor.style.color = "#fff";
      anchor.style.border = "none";
    }

    anchor.innerHTML = btn.label + ' <span class="bubbl-btn-arrow">\u2197</span>';
    btnRow.appendChild(anchor);
  }

  container.appendChild(btnRow);
}

// Fetch managed link colors for the current bot (so buttons use admin-set colors)
(function() {
  var botId = window.EMBEDDED_BOT_ID;
  if (!botId) return;
  fetch('/admin/api/bot_link_colors/' + botId)
    .then(function(r) { return r.ok ? r.json() : {}; })
    .then(function(data) { window._botLinkColors = data; })
    .catch(function() { window._botLinkColors = {}; });
})();

// Track bot message count for rating purposes
var _botMsgIndex = 0;

function createRatingButtons(msgIndex) {
  var wrapper = document.createElement("div");
  wrapper.className = "msg-rating msg-rating--hidden";
  wrapper.setAttribute("data-msg-idx", msgIndex);
  wrapper.style.cssText = "display:flex; gap:6px; align-self:flex-start; margin-top:-4px; margin-bottom:4px; opacity:0; transition:opacity 0.15s;";
  wrapper.innerHTML =
    '<button class="rate-btn rate-up" data-idx="'+msgIndex+'" data-val="1" onclick="rateMsg(this)" title="Helpful">&#128077;</button>' +
    '<button class="rate-btn rate-down" data-idx="'+msgIndex+'" data-val="-1" onclick="rateMsg(this)" title="Not helpful">&#128078;</button>';
  return wrapper;
}

// Show rating buttons on hover/click of the bot message bubble
function attachRatingHover(botDiv, ratingWrapper) {
  var hideTimer = null;

  function show() {
    // Only show if not already rated
    if (!ratingWrapper.classList.contains('msg-rating--rated')) {
      if (hideTimer) clearTimeout(hideTimer);
      ratingWrapper.style.opacity = '1';
    }
  }

  function hide() {
    if (!ratingWrapper.classList.contains('msg-rating--rated')) {
      // Keep visible for 2 seconds after mouse leaves, giving time to click
      hideTimer = setTimeout(function() {
        ratingWrapper.style.opacity = '0';
      }, 2000);
    }
  }

  // Also keep visible when hovering over the rating buttons themselves
  ratingWrapper.addEventListener('mouseenter', function() {
    if (hideTimer) clearTimeout(hideTimer);
    ratingWrapper.style.opacity = '1';
  });

  ratingWrapper.addEventListener('mouseleave', hide);
  botDiv.addEventListener('mouseenter', show);
  botDiv.addEventListener('mouseleave', hide);

  botDiv.addEventListener('click', function() {
    if (!ratingWrapper.classList.contains('msg-rating--rated')) {
      ratingWrapper.style.opacity = ratingWrapper.style.opacity === '1' ? '0' : '1';
    }
  });
}

function rateMsg(btn) {
  var idx = parseInt(btn.getAttribute('data-idx'));
  var val = parseInt(btn.getAttribute('data-val'));
  var sessionId = window._chatSessionId || localStorage.getItem('bubbl_ws_session') || '';
  var wrapper = btn.parentElement;

  // Mark as rated — keep visible, dim unselected button
  wrapper.classList.add('msg-rating--rated');
  wrapper.style.opacity = '1';
  wrapper.querySelectorAll('.rate-btn').forEach(function(b) {
    b.style.opacity = '0.35';
    b.disabled = true;
  });
  btn.style.opacity = '1';
  btn.style.transform = 'scale(1.25)';
  btn.style.filter = val === 1 ? 'drop-shadow(0 0 4px rgba(16,185,129,0.5))' : 'drop-shadow(0 0 4px rgba(239,68,68,0.5))';

  fetch('/api/rate_message', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ session_id: sessionId, message_index: idx, rating: val })
  }).catch(function() {});
}

function appendBotMessage(msg) {
  const display = document.getElementById("chat-display");

  // Parse buttons from the message (if any)
  const { cleanText, buttons } = parseButtons(msg);

  // Render the text message with markdown formatting
  if (cleanText) {
    const botDiv = document.createElement("div");
    botDiv.className = "msg bot";
    botDiv.innerHTML = renderMarkdown(cleanText);
    display.appendChild(botDiv);

    // Add rating buttons (hidden until hover)
    const ratingWrapper = createRatingButtons(_botMsgIndex);
    display.appendChild(ratingWrapper);
    attachRatingHover(botDiv, ratingWrapper);
    _botMsgIndex++;
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

    // Accumulated raw stream text (used for live stripping of markdown syntax)
    let streamRawText = '';

    function processStreamQueue() {
      if (streamQueue.length === 0) {
        clearInterval(streamInterval);
        streamInterval = null;
        return;
      }
      if (!streamingBotDiv) return;

      // Render 2-3 characters at a time for natural typing speed
      const chars = streamQueue.splice(0, 2).join('');
      streamRawText += chars;

      // Live-strip markdown syntax so users don't see ** and ### during streaming.
      // The full renderMarkdown() runs on chat_complete for proper formatting.
      let displayText = streamRawText
        .replace(/\*\*(.+?)\*\*/g, '$1')     // **bold** → bold
        .replace(/\*([^*]+)\*/g, '$1')        // *italic* → italic
        .replace(/^#{1,4}\s+/gm, '')          // ### heading → heading
        .replace(/\[\[BUTTONS:.*?\]\]/gs, '') // hide button tags during stream
        .replace(/\[\[LEAD:.*?\]\]/gs, '');   // hide lead tags during stream

      streamingBotDiv.innerText = displayText;
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
        streamingBotDiv.style.whiteSpace = "pre-wrap";  // Preserve spaces during streaming (plain text)
        streamingBotDiv.innerText = "";
        streamRawText = '';  // Reset raw text accumulator
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
          // Switch from plain-text streaming to formatted HTML
          streamingBotDiv.style.whiteSpace = "";  // Remove pre-wrap for HTML
          if (typeof renderMarkdown === 'function') {
            streamingBotDiv.innerHTML = renderMarkdown(cleanText);
          } else if (typeof linkify === 'function') {
            streamingBotDiv.innerHTML = linkify(cleanText);
          } else {
            streamingBotDiv.innerText = cleanText;
          }
          if (buttons.length > 0) {
            const display = document.getElementById("chat-display");
            renderButtons(buttons, display);
          }
          // Save reference before nulling — needed for rating hover listeners
          const completedBotDiv = streamingBotDiv;
          streamingBotDiv = null;
          // Add rating buttons after streaming completes
          const display2 = document.getElementById("chat-display");
          const ratingWrapper = createRatingButtons(_botMsgIndex);
          display2.appendChild(ratingWrapper);
          attachRatingHover(completedBotDiv, ratingWrapper);
          _botMsgIndex++;
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


// ═══════════════════════════════════════════
// SHARE CONVERSATION — Dropdown with 2 options
// ═══════════════════════════════════════════

function toggleShareMenu() {
  var menu = document.getElementById('share-dropdown');
  if (!menu) return;

  if (menu.classList.contains('share-dropdown--open')) {
    menu.classList.remove('share-dropdown--open');
  } else {
    menu.classList.add('share-dropdown--open');
    // Close on outside click
    setTimeout(function() {
      document.addEventListener('click', closeShareMenuOutside);
    }, 10);
  }
}

function closeShareMenuOutside(e) {
  var menu = document.getElementById('share-dropdown');
  var btn = document.querySelector('.share-chat-btn');
  if (menu && !menu.contains(e.target) && btn && !btn.contains(e.target)) {
    menu.classList.remove('share-dropdown--open');
    document.removeEventListener('click', closeShareMenuOutside);
  }
}

function shareViaLink() {
  // Close the dropdown
  var menu = document.getElementById('share-dropdown');
  if (menu) menu.classList.remove('share-dropdown--open');

  if (!chatHistory || chatHistory.length === 0) {
    showShareToast("No messages to share yet.", "error");
    return;
  }

  var sessionId = window._chatSessionId || localStorage.getItem('bubbl_ws_session') || '';
  var botId = window.EMBEDDED_BOT_ID || '';
  var botName = document.querySelector('.chat-header-title')
    ? document.querySelector('.chat-header-title').innerText
    : 'Bubbl';

  if (!sessionId) {
    showShareToast("Start a conversation first.", "error");
    return;
  }

  // Show loading state
  showShareToast("Generating link...", "loading");

  fetch('/api/share_conversation', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      bot_id: botId,
      bot_name: botName
    })
  })
  .then(function(res) { return res.json(); })
  .then(function(data) {
    if (data.share_url) {
      // Copy link to clipboard
      copyToClipboard(data.share_url, "Link copied to clipboard!");
    } else {
      showShareToast(data.error || "Could not generate link.", "error");
    }
  })
  .catch(function() {
    showShareToast("Error connecting to server.", "error");
  });
}

function downloadChat() {
  // Close the dropdown
  var menu = document.getElementById('share-dropdown');
  if (menu) menu.classList.remove('share-dropdown--open');

  var sessionId = window._chatSessionId || localStorage.getItem('bubbl_ws_session') || '';
  var botId = window.EMBEDDED_BOT_ID || '';
  var botName = document.querySelector('.chat-header-title')
    ? document.querySelector('.chat-header-title').innerText
    : 'Bubbl';

  if (!sessionId) {
    showShareToast("Start a conversation first.", "error");
    return;
  }

  // Server-rendered transcript page — just open it and let it call window.print().
  var url = '/transcript/' + encodeURIComponent(sessionId) + '/print'
          + '?bot_id=' + encodeURIComponent(botId)
          + '&bot_name=' + encodeURIComponent(botName);

  var win = window.open(url, '_blank');
  if (win) {
    // The page calls window.print() itself once it has laid out.
    showShareToast("PDF ready — use Save as PDF!", "success");
  } else {
    showShareToast("Please allow pop-ups to download the chat.", "error");
  }
}

function copyToClipboard(text, successMsg) {
  successMsg = successMsg || "Copied to clipboard!";
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(function() {
      showShareToast(successMsg, "success");
    }).catch(function() {
      fallbackCopy(text, successMsg);
    });
  } else {
    fallbackCopy(text, successMsg);
  }
}

function fallbackCopy(text, successMsg) {
  var textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.select();
  try {
    document.execCommand('copy');
    showShareToast(successMsg || "Copied!", "success");
  } catch (e) {
    showShareToast("Could not copy. Please try again.", "error");
  }
  document.body.removeChild(textarea);
}

function showShareToast(message, type) {
  type = type || "success";
  // Remove existing toast
  var existing = document.getElementById('share-toast');
  if (existing) existing.remove();

  var icons = {
    success: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
    error: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
    loading: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="share-toast-spin"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>'
  };

  var toast = document.createElement('div');
  toast.id = 'share-toast';
  toast.className = 'share-toast share-toast--' + type;
  toast.innerHTML = (icons[type] || '') + '<span>' + message + '</span>';

  var chatPopup = document.getElementById('chat-window-popup');
  if (chatPopup) {
    chatPopup.appendChild(toast);
  } else {
    document.body.appendChild(toast);
  }

  // Animate in
  setTimeout(function() { toast.classList.add('share-toast--visible'); }, 10);

  // Auto-remove after 3s (don't auto-remove loading)
  if (type !== 'loading') {
    setTimeout(function() {
      toast.classList.remove('share-toast--visible');
      setTimeout(function() { toast.remove(); }, 300);
    }, 3000);
  }
}

