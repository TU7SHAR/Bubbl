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

    // Each state = 80 frames × 120px = 9600px (element width 120px, bg-size 48000px)
    // Different states look best at different speeds
    switch (stateName) {
      case "hover":
        startPosition = 0;
        endPosition = -9600;
        duration = 3;
        break;
      case "thinking":
        startPosition = -9600;
        endPosition = -19200;
        duration = 5;
        break;
      case "idle":
        startPosition = -19200;
        endPosition = -28800;
        duration = 6;
        break;
      case "talking":
        startPosition = -28800;
        endPosition = -38400;
        duration = 3;
        break;
      case "rolling":
        startPosition = -38400;
        endPosition = -48000;
        duration = 4;
        break;
      default:
        startPosition = -19200;
        endPosition = -28800;
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
