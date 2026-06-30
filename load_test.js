import http from "k6/http";
import { check, sleep } from "k6";

export let options = {
  stages: [
    { duration: "30s", target: 20 }, // Ramp up to 20 users
    { duration: "1m", target: 50 }, // Hold at 50 users
    { duration: "30s", target: 1000 }, // Spike to 100
    { duration: "30s", target: 0 }, // Ramp down
  ],
};

export default function () {
  // Test homepage
  let res = http.get("https://coral-app-jbybo.ondigitalocean.app/");
  check(res, { "homepage 200": (r) => r.status === 200 });

  // Test chat API
  let chatRes = http.post(
    "https://coral-app-jbybo.ondigitalocean.app/api/chat",
    JSON.stringify({ message: "hello", bot_id: 12, history: [] }),
    { headers: { "Content-Type": "application/json" } },
  );
  check(chatRes, { "chat 200": (r) => r.status === 200 });

  sleep(1);
}
