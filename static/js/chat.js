let messageCount = 0;
let leadCaptured = false;

async function submitLeadForm() {
  const name = document.getElementById("lead-name").value.trim();
  const email = document.getElementById("lead-email").value.trim();
  const phone = document.getElementById("lead-phone").value.trim();
  const botId = window.EMBEDDED_BOT_ID;

  if (!name || !email) {
    alert("Name and email are required.");
    return;
  }

  const payload = { bot_id: botId, name: name, email: email, phone: phone };

  try {
    const response = await fetch("/api/lead", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (response.ok) {
      leadCaptured = true;
      document.getElementById("lead-capture-box").remove();
      document.getElementById("user-input").disabled = false;

      const sendButton = document.getElementById("send-btn-icon");
      if (sendButton) {
        sendButton.disabled = false;
        sendButton.style.opacity = "1";
      }

      const display = document.getElementById("chat-display");
      const botDiv = document.createElement("div");
      botDiv.className = "msg bot";
      botDiv.innerText = "Thanks! How can I help you today?";
      display.appendChild(botDiv);
      display.scrollTop = display.scrollHeight;
    }
  } catch (error) {
    console.error(error);
  }
}

function triggerLeadCapture() {
  const display = document.getElementById("chat-display");

  const formBox = document.createElement("div");
  formBox.id = "lead-capture-box";
  formBox.className = "msg bot";
  formBox.innerHTML = `
    <p style="margin-top:0;">Before we continue, please provide your details:</p>
    <input type="text" id="lead-name" placeholder="Name" style="width:100%; margin-bottom:8px; padding:6px; border-radius:4px; border:1px solid #ccc;">
    <input type="email" id="lead-email" placeholder="Email" style="width:100%; margin-bottom:8px; padding:6px; border-radius:4px; border:1px solid #ccc;">
    <input type="text" id="lead-phone" placeholder="Phone (Optional)" style="width:100%; margin-bottom:8px; padding:6px; border-radius:4px; border:1px solid #ccc;">
    <button onclick="submitLeadForm()" style="width:100%; padding:8px; background:var(--theme-color, #E8722A); color:#fff; border:none; border-radius:4px; cursor:pointer;">Submit</button>
  `;

  display.appendChild(formBox);
  display.scrollTop = display.scrollHeight;

  document.getElementById("user-input").disabled = true;
  const sendButton = document.getElementById("send-btn-icon");
  if (sendButton) {
    sendButton.disabled = true;
    sendButton.style.opacity = "0.5";
  }
}

function toggleChat() {
  const chatPopup = document.getElementById("chat-window-popup");
  const spriteContainer = document.getElementById("sprite-ask-container");

  if (chatPopup.classList.contains("hidden")) {
    chatPopup.classList.remove("hidden");
    if (spriteContainer) spriteContainer.classList.add("chat-open");
  } else {
    chatPopup.classList.add("hidden");
    if (spriteContainer) spriteContainer.classList.remove("chat-open");
  }
}

async function sendMessage() {
  if (window.LEAD_TIMING === "start" && !leadCaptured && messageCount === 0) {
    triggerLeadCapture();
    return;
  }
  if (window.LEAD_TIMING === "middle" && !leadCaptured && messageCount === 2) {
    triggerLeadCapture();
    return;
  }

  const input = document.getElementById("user-input");
  const display = document.getElementById("chat-display");
  const sendButton = document.getElementById("send-btn-icon");

  const msg = input.value.trim();

  if (!msg) return;

  messageCount++;

  input.disabled = true;
  if (sendButton) {
    sendButton.disabled = true;
    sendButton.style.opacity = "0.5";
  }

  if (window.SpriteBot) SpriteBot.setState("thinking");

  const userDiv = document.createElement("div");
  userDiv.className = "msg user";
  userDiv.innerText = msg;
  display.appendChild(userDiv);
  input.value = "";

  const typingDiv = document.createElement("div");
  typingDiv.id = "typing";
  typingDiv.className = "msg bot";
  typingDiv.innerText = "...";
  display.appendChild(typingDiv);
  display.scrollTop = display.scrollHeight;

  try {
    const payload = { message: msg };

    if (window.EMBEDDED_BOT_ID) {
      payload.bot_id = window.EMBEDDED_BOT_ID;
    }

    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await response.json();

    if (document.getElementById("typing")) {
      document.getElementById("typing").remove();
    }

    const botDiv = document.createElement("div");
    botDiv.className = "msg bot";

    if (data.error) {
      if (window.SpriteBot) SpriteBot.setState("idle");
      botDiv.innerText = "SYSTEM ERROR: " + data.error;
    } else if (data.response) {
      if (window.SpriteBot) {
        SpriteBot.setState("talking");
        setTimeout(() => {
          if (SpriteBot.currentState === "talking") {
            SpriteBot.setState("idle");
          }
        }, 8000);
      }
      botDiv.innerText = data.response;
    } else {
      if (window.SpriteBot) SpriteBot.setState("idle");
      botDiv.innerText = "SYSTEM ERROR: Unrecognized data format.";
    }

    display.appendChild(botDiv);
  } catch (error) {
    if (window.SpriteBot) SpriteBot.setState("idle");
    if (document.getElementById("typing")) {
      document.getElementById("typing").innerText =
        "Error connecting to server.";
    }
  } finally {
    input.disabled = false;
    if (sendButton) {
      sendButton.disabled = false;
      sendButton.style.opacity = "1";
    }
    input.focus();
    display.scrollTop = display.scrollHeight;
  }
}
