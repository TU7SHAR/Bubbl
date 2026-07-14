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

    if (!this.element || !this.container) return;

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

    if (this.currentTween) this.currentTween.kill();

    let startPosition, endPosition, duration;

    // Each state = 80 frames × 400px = 32000px (element is 400px wide)
    switch (stateName) {
      case "hover":
        startPosition = 0;
        endPosition = -32000;
        duration = 3;
        break;
      case "thinking":
        startPosition = -32000;
        endPosition = -64000;
        duration = 5;
        break;
      case "idle":
        startPosition = -64000;
        endPosition = -96000;
        duration = 6;
        break;
      case "talking":
        startPosition = -96000;
        endPosition = -128000;
        duration = 3;
        break;
      case "rolling":
        startPosition = -128000;
        endPosition = -160000;
        duration = 4;
        break;
      default:
        startPosition = -64000;
        endPosition = -96000;
        duration = 6;
    }

    gsap.set(this.element, { backgroundPositionX: `${startPosition}px` });
    this.currentTween = gsap.to(this.element, {
      backgroundPositionX: `${endPosition}px`,
      duration: duration,
      ease: "steps(80)",
      repeat: -1,
    });
  },
};
window.SpriteBot = SpriteBot;
document.addEventListener("DOMContentLoaded", () => SpriteBot.init());
