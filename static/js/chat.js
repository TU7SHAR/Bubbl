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
    alert("Name and email are required.");
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

    // 👇 ADDED LEAD ID CAPTURE HERE 👇
    if (data.lead_id) {
      window.BUBBL_LEAD_ID = data.lead_id;
    }
    // 👆 ---------------------------- 👆

    if (response.ok) {
      leadCaptured = true;
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
      alert(data.error || "There was an error saving your details.");
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

function appendBotMessage(msg) {
  const display = document.getElementById("chat-display");
  const botDiv = document.createElement("div");
  botDiv.className = "msg bot";
  botDiv.innerText = msg;
  display.appendChild(botDiv);
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
    input.disabled = disabled;
    if (!disabled) {
      input.value = "";
      input.focus();
    }
  }
  if (sendButton) {
    sendButton.disabled = disabled;
    sendButton.style.opacity = disabled ? "0.5" : "1";
  }
}

async function sendMessage() {
  const input = document.getElementById("user-input");
  const rawMsg = input.value.trim();
  if (!rawMsg) return;

  // Gatekeeper Failsafe
  if (window.LEAD_TIMING === "gatekeeper" && !leadCaptured) {
    pendingMessage = rawMsg;
    renderGatekeeperForm();
    return;
  }

  appendUserMessage(rawMsg);
  chatHistory.push({ role: "user", text: rawMsg });

  setInputState(true);
  if (window.SpriteBot) SpriteBot.setState("thinking");
  showTypingIndicator();

  const payload = { message: rawMsg, history: chatHistory };
  if (window.EMBEDDED_BOT_ID) payload.bot_id = window.EMBEDDED_BOT_ID;

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await response.json();

    // 👇 ADDED LEAD ID CAPTURE HERE 👇
    if (data.lead_id) {
      window.BUBBL_LEAD_ID = data.lead_id;
    }
    // 👆 ---------------------------- 👆

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
      } else {
        replyText = replyText.replace("[SHOW_FORM]", "").trim();
        appendBotMessage(replyText);
        chatHistory.push({ role: "bot", text: replyText });
        setInputState(false);
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
