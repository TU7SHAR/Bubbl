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

    // Calculate frame width dynamically from element size
    // (supports responsive: 300px desktop, 200px mobile)
    const frameWidth = this.element.offsetWidth;
    const stateLength = 80 * frameWidth; // 80 frames per state

    switch (stateName) {
      case "hover":
        startPosition = 0;
        endPosition = -stateLength;
        duration = 4;
        break;
      case "thinking":
        startPosition = -stateLength;
        endPosition = -stateLength * 2;
        duration = 6;
        break;
      case "idle":
        startPosition = -stateLength * 2;
        endPosition = -stateLength * 3;
        duration = 8;
        break;
      case "talking":
        startPosition = -stateLength * 3;
        endPosition = -stateLength * 4;
        duration = 4;
        break;
      case "rolling":
        startPosition = -stateLength * 4;
        endPosition = -stateLength * 5;
        duration = 5;
        break;
      default:
        startPosition = -stateLength * 2;
        endPosition = -stateLength * 3;
        duration = 8;
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
