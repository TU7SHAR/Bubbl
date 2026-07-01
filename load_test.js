import http from "k6/http";
import { check, sleep } from "k6";

export let options = {
  stages: [
    { duration: "30s", target: 10 },  // Warm up: 10 users
    { duration: "30s", target: 25 },  // Push: 25 users
    { duration: "30s", target: 50 },  // Stress: 50 users
    { duration: "30s", target: 100 }, // Max: 100 users
    { duration: "30s", target: 0 },   // Cool down
  ],
};

export default function () {
  // Test homepage (browsing)
  let res = http.get("http://168.144.123.62:8080/");
  check(res, { "homepage 200": (r) => r.status === 200 });

  // Test chat API (the real bottleneck)
  let chatRes = http.post(
    "http://168.144.123.62:8080/api/chat",
    JSON.stringify({ message: "hello", bot_id: 14, history: [] }),
    { headers: { "Content-Type": "application/json" } },
  );
  check(chatRes, { "chat 200": (r) => r.status === 200 });

  // Simulate real user: wait 10-20 seconds between messages
  sleep(Math.random() * 10 + 10);
}
