const SpriteBot = {
  element: null,
  container: null,
  currentTween: null,

  currentState: "idle",
  isBusy: false,
  isHovering: false,
  mouseTimer: null,

  init() {
    this.element = document.querySelector("#bot-sprite");
    this.container = document.querySelector("#sprite-ask-container");
    this.headerSprite = document.querySelector("#chat-header-sprite");

    if (!this.element || !this.container) return;

    // On real mobile devices the sprite is a single static image (the animated
    // filmstrip is too large for mobile browsers to decode). Skip animation.
    // Exception: the embed widget runs in a ~450px iframe (which would look
    // like "mobile" by width) but is usually on a desktop host — so it should
    // still animate. Detect the embed via window.EMBEDDED_BOT_ID.
    const isEmbed = !!window.EMBEDDED_BOT_ID;
    this.isMobile =
      !isEmbed &&
      window.matchMedia &&
      window.matchMedia("(max-width: 768px)").matches;
    if (this.isMobile) return;

    this.setState("idle");

    // --- Global Mouse Movement Tracker ---
    document.addEventListener("mousemove", () => {
      if (this.isBusy) return;
      if (this.isHovering) return;
      if (this.currentState !== "rolling") {
        this.setState("rolling");
      }

      clearTimeout(this.mouseTimer);
      this.mouseTimer = setTimeout(() => {
        if (
          !this.isBusy &&
          this.currentState === "rolling" &&
          !this.isHovering
        ) {
          this.setState("idle");
        }
      }, 1500);
    });

    this.container.addEventListener("mouseenter", () => {
      this.isHovering = true;
      if (!this.isBusy) this.setState("hover");
    });

    this.container.addEventListener("mouseleave", () => {
      this.isHovering = false;
      if (!this.isBusy) this.setState("idle");
    });
  },

  setState(stateName) {
    if (!this.element) return;
    if (this.currentState === stateName) return;

    this.currentState = stateName;
    this.isBusy = stateName === "thinking" || stateName === "talking";

    // Update chat header state indicator
    const stateEl = document.getElementById("chat-state-indicator");
    if (stateEl) {
      stateEl.className = "chat-header-state";
      switch (stateName) {
        case "thinking":
          stateEl.textContent = "Thinking\u2026";
          stateEl.classList.add("state-thinking");
          break;
        case "talking":
          stateEl.textContent = "Responding";
          stateEl.classList.add("state-talking");
          break;
        default:
          stateEl.textContent = "Online";
          break;
      }
    }

    // Notify contextual message system
    if (window.MascotContext) {
      window.MascotContext.onEvent(stateName);
    }

    if (this.currentTween) this.currentTween.kill();

    let startPosition, endPosition, duration;

    // Calculate frame width dynamically from element size
    // (supports responsive: 300px desktop, 200px mobile)
    const frameWidth = this.element.offsetWidth;
    const stateLength = 80 * frameWidth; // 80 frames per state

    switch (stateName) {
      case "hover":
        startPosition = 0;
        endPosition = -stateLength;
        duration = 6;
        break;
      case "thinking":
        startPosition = -stateLength;
        endPosition = -stateLength * 2;
        duration = 8;
        break;
      case "idle":
        startPosition = -stateLength * 2;
        endPosition = -stateLength * 3;
        duration = 10;
        break;
      case "talking":
        startPosition = -stateLength * 3;
        endPosition = -stateLength * 4;
        duration = 6;
        break;
      case "rolling":
        startPosition = -stateLength * 4;
        endPosition = -stateLength * 5;
        duration = 7;
        break;
      default:
        startPosition = -stateLength * 2;
        endPosition = -stateLength * 3;
        duration = 10;
    }

    gsap.set(this.element, { backgroundPositionX: `${startPosition}px` });
    this.currentTween = gsap.to(this.element, {
      backgroundPositionX: `${endPosition}px`,
      duration: duration,
      ease: "steps(80)",
      repeat: -1,
    });

    // Sync header sprite (smaller, inside chat window)
    if (this.headerSprite) {
      const headerFrameWidth = this.headerSprite.offsetWidth || 70;
      const headerStateLength = 80 * headerFrameWidth;
      const hStart = (startPosition / frameWidth) * headerFrameWidth;
      const hEnd = (endPosition / frameWidth) * headerFrameWidth;
      gsap.set(this.headerSprite, { backgroundPositionX: `${hStart}px` });
      gsap.to(this.headerSprite, {
        backgroundPositionX: `${hEnd}px`,
        duration: duration,
        ease: "steps(80)",
        repeat: -1,
      });
    }
  },
};
window.SpriteBot = SpriteBot;
document.addEventListener("DOMContentLoaded", () => SpriteBot.init());
