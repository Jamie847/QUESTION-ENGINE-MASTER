async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : "{}",
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json();
}

document.querySelectorAll(".stars").forEach((el) => {
  el.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-star]");
    if (!btn) return;
    const stars = Number(btn.dataset.star);
    const qid = el.dataset.qid;
    try {
      await postJSON(`/api/questions/${qid}/rating`, { stars });
      el.dataset.stars = String(stars);
      el.querySelectorAll("[data-star]").forEach((b) => {
        b.classList.toggle("on", Number(b.dataset.star) <= stars);
      });
    } catch (err) {
      alert("Could not save rating: " + err.message);
    }
  });
});

document.querySelectorAll(".promote").forEach((btn) => {
  btn.addEventListener("click", async () => {
    try {
      await postJSON(`/api/questions/${btn.dataset.qid}/promote`);
      btn.textContent = "Promoted";
      btn.disabled = true;
    } catch (err) {
      alert("Could not promote: " + err.message);
    }
  });
});

const runBtn = document.getElementById("run-btn");
if (runBtn) {
  runBtn.addEventListener("click", async () => {
    runBtn.disabled = true;
    const msg = document.getElementById("run-msg");
    try {
      await postJSON("/api/run");
      if (msg) msg.textContent = "Swarm started. This page will pick up the new digest.";
      pollUntilIdle();
    } catch (err) {
      runBtn.disabled = false;
      if (msg) msg.textContent = err.message;
    }
  });
}

if (document.querySelector("[data-poll]")) {
  pollUntilIdle();
}

function pollUntilIdle() {
  const started = Date.now();
  const tick = async () => {
    try {
      const st = await fetch("/api/status").then((r) => r.json());
      if (!st.running && Date.now() - started > 1500) {
        window.location.reload();
        return;
      }
    } catch (_) {
      /* keep polling */
    }
    if (Date.now() - started < 15 * 60 * 1000) {
      setTimeout(tick, 2500);
    }
  };
  setTimeout(tick, 2500);
}
