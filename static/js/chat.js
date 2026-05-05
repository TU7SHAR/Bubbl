let messageCount = 0;
let leadCaptureState = "idle"; // Can be: 'idle', 'asking_details', 'captured'
let interceptedMessage = ""; // Holds the message the user was trying to send

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

function removeTypingIndicator() {
  const typing = document.getElementById("typing");
  if (typing) typing.remove();
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

let chatHistory = [];

async function sendMessage() {
  const input = document.getElementById("user-input");
  const rawMsg = input.value.trim();
  if (!rawMsg) return;

  // 1. Update UI
  const display = document.getElementById("chat-display");
  const userDiv = document.createElement("div");
  userDiv.className = "msg user";
  userDiv.innerText = rawMsg;
  display.appendChild(userDiv);
  display.scrollTop = display.scrollHeight;

  // 2. Prepare Payload with History
  const payload = {
    message: rawMsg,
    history: chatHistory,
  };

  if (window.EMBEDDED_BOT_ID) {
    payload.bot_id = window.EMBEDDED_BOT_ID;
  }

  // 3. Save User message to memory
  chatHistory.push({ role: "user", text: rawMsg });

  // 4. Lock Input & Show Typing
  input.value = "";
  input.disabled = true;
  const sendButton = document.getElementById("send-btn-icon");
  if (sendButton) {
    sendButton.disabled = true;
    sendButton.style.opacity = "0.5";
  }

  if (window.SpriteBot) SpriteBot.setState("thinking");
  const typingDiv = document.createElement("div");
  typingDiv.id = "typing";
  typingDiv.className = "msg bot";
  typingDiv.innerText = "...";
  display.appendChild(typingDiv);
  display.scrollTop = display.scrollHeight;

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await response.json();

    if (document.getElementById("typing"))
      document.getElementById("typing").remove();

    const botDiv = document.createElement("div");
    botDiv.className = "msg bot";

    if (data.error) {
      botDiv.innerText = "SYSTEM ERROR: " + data.error;
      if (window.SpriteBot) SpriteBot.setState("idle");
    } else if (data.response) {
      botDiv.innerText = data.response;
      // Save Bot message to memory so it remembers for the next turn
      chatHistory.push({ role: "bot", text: data.response });

      if (window.SpriteBot) {
        SpriteBot.setState("talking");
        setTimeout(() => {
          if (SpriteBot.currentState === "talking") SpriteBot.setState("idle");
        }, 8000);
      }
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

// -----------------------------------------
// API CALL TO AI
// -----------------------------------------
async function sendToGemini(msg, botId) {
  messageCount++;
  setInputState(true);
  if (window.SpriteBot) SpriteBot.setState("thinking");
  showTypingIndicator();

  try {
    const payload = { message: msg };
    if (botId) payload.bot_id = botId;

    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await response.json();
    removeTypingIndicator();

    if (data.error) {
      if (window.SpriteBot) SpriteBot.setState("idle");
      appendBotMessage("SYSTEM ERROR: " + data.error);
    } else if (data.response) {
      if (window.SpriteBot) {
        SpriteBot.setState("talking");
        setTimeout(() => {
          if (SpriteBot.currentState === "talking") SpriteBot.setState("idle");
        }, 8000);
      }
      appendBotMessage(data.response);
    } else {
      if (window.SpriteBot) SpriteBot.setState("idle");
      appendBotMessage("SYSTEM ERROR: Unrecognized data format.");
    }
  } catch (error) {
    if (window.SpriteBot) SpriteBot.setState("idle");
    removeTypingIndicator();
    appendBotMessage("Error connecting to server.");
  } finally {
    setInputState(false);
  }
}
