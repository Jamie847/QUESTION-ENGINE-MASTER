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
      const why = (el.querySelector(".why") && el.querySelector(".why").value) || "";
      await postJSON(`/api/questions/${qid}/rating`, { stars, why });
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
      btn.textContent = "Saved";
      btn.disabled = true;
    } catch (err) {
      alert("Could not promote: " + err.message);
    }
  });
});

const runButtons = document.querySelectorAll("[data-run-btn]");
const runMsgs = document.querySelectorAll("[data-run-msg]");

function setRunMessage(text) {
  runMsgs.forEach((el) => {
    el.textContent = text;
  });
}

function setRunDisabled(disabled) {
  runButtons.forEach((btn) => {
    if (btn.dataset.ceiling === "1") return;
    btn.disabled = disabled;
  });
}

runButtons.forEach((runBtn) => {
  if (runBtn.disabled && runBtn.textContent.toLowerCase().includes("ceiling")) {
    runBtn.dataset.ceiling = "1";
  }
  runBtn.addEventListener("click", async () => {
    setRunDisabled(true);
    try {
      await postJSON("/api/run");
      setRunMessage("reading sources");
      pollUntilIdle();
    } catch (err) {
      setRunDisabled(false);
      setRunMessage(err.message);
    }
  });
});

const issueBtn = document.getElementById("issue-btn");
if (issueBtn) {
  issueBtn.addEventListener("click", async () => {
    issueBtn.disabled = true;
    const msg = document.getElementById("issue-msg");
    try {
      await postJSON("/api/issues");
      if (msg) msg.textContent = "Draft started. This page will pick up the new issue.";
      pollIssueUntilIdle();
    } catch (err) {
      issueBtn.disabled = false;
      if (msg) msg.textContent = err.message;
    }
  });
}

if (document.querySelector("[data-poll]")) {
  pollUntilIdle();
}

document.querySelectorAll("[data-bank-filter]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const key = btn.dataset.bankFilter;
    document.querySelectorAll("[data-bank-filter]").forEach((other) => {
      other.classList.toggle("on", other === btn);
    });
    const all = document.getElementById("bank-all");
    if (all) all.hidden = key !== "all";
    document.querySelectorAll("[data-bank-pane]").forEach((pane) => {
      pane.hidden = pane.dataset.bankPane !== key;
    });
  });
});

function pollIssueUntilIdle() {
  const started = Date.now();
  const tick = async () => {
    try {
      const st = await fetch("/api/issues/status").then((r) => r.json());
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

function pollUntilIdle() {
  const started = Date.now();
  const tick = async () => {
    try {
      const st = await fetch("/api/status").then((r) => r.json());
      if (st.running) {
        setRunDisabled(true);
        setRunMessage(st.stage_words || st.stage || "reading sources");
      }
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
