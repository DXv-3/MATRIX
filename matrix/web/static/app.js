const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function apiToken() {
  return localStorage.getItem("matrix_token") || "";
}

function authHeaders() {
  const token = apiToken();
  const h = { "Content-Type": "application/json" };
  if (token) h.Authorization = `Bearer ${token}`;
  return h;
}

function previewUrl(assetId) {
  const base = `/api/assets/${assetId}/preview`;
  const token = apiToken();
  return token ? `${base}?token=${encodeURIComponent(token)}` : base;
}

async function revealInFinder(assetId) {
  await api(`/api/assets/${assetId}/reveal`, { method: "POST" });
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { ...authHeaders(), ...opts.headers },
    ...opts,
  });
  const text = await res.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }
  if (res.status === 401) {
    const token = prompt("MATRIX API token (Bearer):", localStorage.getItem("matrix_token") || "");
    if (token) {
      localStorage.setItem("matrix_token", token.trim());
      return api(path, opts);
    }
  }
  if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
  return data;
}

function formatBytes(n) {
  if (!n) return "—";
  const u = ["B", "KB", "MB", "GB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(1)} ${u[i]}`;
}

function log(el, msg) {
  const ts = new Date().toLocaleTimeString();
  el.textContent = `[${ts}] ${typeof msg === "string" ? msg : JSON.stringify(msg, null, 2)}\n` + el.textContent;
}

// Tabs
$$(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$(".tab").forEach((t) => t.classList.remove("active"));
    $$(".panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $(`#panel-${btn.dataset.tab}`).classList.add("active");
  });
});

// SSE
function connectEvents() {
  const token = localStorage.getItem("matrix_token");
  const url = token ? `/api/events?token=${encodeURIComponent(token)}` : "/api/events";
  const es = new EventSource(url);
  const pill = $("#liveStatus");
  const logEl = $("#eventLog");

  es.onopen = () => {
    pill.textContent = "Live";
    pill.classList.add("live");
  };
  es.onerror = () => {
    pill.textContent = "Offline";
    pill.classList.remove("live");
  };
  es.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      log(logEl, `${msg.type}: ${JSON.stringify(msg.payload)}`);
      if (msg.type.endsWith(".done")) {
        loadReport();
        if (msg.type.startsWith("dedup") || msg.type.startsWith("pipeline")) {
          loadReview();
        }
      }
    } catch (_) {}
  };
}

async function loadReport() {
  const r = await api("/api/report");
  $("#catalogPath").textContent = r.catalog || "—";
  const grid = $("#statsGrid");
  const stats = [
    ["Assets", r.assets],
    ["Duplicate groups", r.duplicate_groups],
    ["Lineage groups", r.lineage_groups],
    ["Pending review", r.pending_review],
    ["Quarantine moves", r.quarantine_moves],
  ];
  grid.innerHTML = stats
    .map(
      ([label, value]) =>
        `<div class="stat"><div class="value">${value ?? 0}</div><div class="label">${label}</div></div>`
    )
    .join("");

  const cfg = await api("/api/config");
  if (cfg.scan_roots?.length && !$("#scanRoot").value) {
    $("#scanRoot").value = cfg.scan_roots[0];
  }
}

async function loadReview() {
  const box = $("#reviewQueue");
  box.innerHTML = '<p class="empty">Loading…</p>';
  const data = await api("/api/groups/pending");
  if (!data.items?.length) {
    box.innerHTML = '<p class="empty">No pending duplicate groups.</p>';
    return;
  }
  const dry = $("#dryRun").checked;
  box.innerHTML = data.items
    .map((item) => {
      const g = item.group;
      const members = item.members
        .map((m) => {
          const master = m.is_master ? "master" : "";
          const name = m.filename || m.path.split("/").pop() || m.path;
          return `
          <div class="member ${master}" data-aid="${m.id}">
            <div class="member-preview">
              <img src="${previewUrl(m.id)}" alt="${name}" loading="lazy"
                onload="this.classList.add('loaded')"
                onerror="this.classList.add('failed'); this.closest('.member-preview')?.classList.add('no-preview')" />
              <span class="preview-fallback">No preview</span>
            </div>
            <div><strong>${m.is_master ? "MASTER" : "copy"}</strong> · ${m.file_type}</div>
            <div class="member-meta">${formatBytes(m.size_bytes)} · conf ${(m.confidence ?? 0).toFixed(2)}</div>
            <div class="path" title="${m.path}">${name}</div>
            <button type="button" class="btn btn-sm" data-reveal="${m.id}">Show in Finder</button>
          </div>`;
        })
        .join("");
      return `
      <article class="review-group" data-gid="${g.id}">
        <h3>Group #${g.id} · ${g.group_type} · confidence ${g.confidence}</h3>
        <div class="members">${members}</div>
        <div class="group-actions">
          <button class="btn" data-action="KEEP_ALL">Keep all</button>
          <button class="btn danger btn-delete-glow" data-action="DELETE_DUPLICATES" type="button">
            <span class="btn-delete-label">Delete duplicates</span>
          </button>
          <button class="btn" data-action="SKIP">Skip</button>
          <button class="btn" data-action="MANUAL">Manual</button>
        </div>
      </article>`;
    })
    .join("");

  box.querySelectorAll("[data-reveal]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const aid = parseInt(btn.dataset.reveal, 10);
      btn.disabled = true;
      try {
        await revealInFinder(aid);
      } catch (e) {
        alert(e.message);
      } finally {
        btn.disabled = false;
      }
    });
  });

  box.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const gid = parseInt(btn.closest(".review-group").dataset.gid, 10);
      btn.disabled = true;
      try {
        const res = await api("/api/approve", {
          method: "POST",
          body: JSON.stringify({
            group_id: gid,
            action: btn.dataset.action,
            dry_run: dry,
          }),
        });
        log($("#eventLog"), res);
        loadReview();
        loadReport();
      } catch (e) {
        alert(e.message);
      } finally {
        btn.disabled = false;
      }
    });
  });
}

async function loadLineage() {
  const box = $("#lineageList");
  const data = await api("/api/lineage?limit=80");
  if (!data.items?.length) {
    box.innerHTML = '<p class="empty">No lineage groups yet. Run dedup after scan.</p>';
    return;
  }
  box.innerHTML = data.items
    .map((item) => {
      const lg = item.lineage_group;
      const rows = item.assets
        .map((a) => `<li>${a.lineage_role || "?"} · ${a.filename} <span class="path">${a.path}</span></li>`)
        .join("");
      return `<div class="roll"><h3>Roll ${lg.roll_number} · Frame ${lg.frame_number}</h3><ul>${rows}</ul></div>`;
    })
    .join("");
}

async function loadAssets() {
  const data = await api("/api/assets?limit=50");
  const tbody = $("#assetsTable tbody");
  tbody.innerHTML = data.items
    .map(
      (a) => `<tr>
      <td>${a.id}</td>
      <td><img class="thumb" src="${previewUrl(a.id)}" alt="" onerror="this.remove()" /></td>
      <td>${a.filename} <button type="button" class="btn btn-sm" data-reveal-asset="${a.id}">Finder</button></td>
      <td>${a.file_type}</td>
      <td>${a.review_status}</td>
      <td>${a.confidence != null ? a.confidence.toFixed(2) : "—"}</td>
    </tr>`
    )
    .join("");
  tbody.querySelectorAll("[data-reveal-asset]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await revealInFinder(parseInt(btn.dataset.revealAsset, 10));
      } catch (e) {
        alert(e.message);
      }
    });
  });
}

$("#btnRefreshReport").addEventListener("click", loadReport);
$("#btnRunDedup").addEventListener("click", async () => {
  const el = $("#eventLog");
  try {
    log(el, await api("/api/dedup", { method: "POST" }));
    loadReport();
    loadReview();
  } catch (e) {
    log(el, e.message);
  }
});
$("#btnOpenReview").addEventListener("click", () => {
  $$('.tab[data-tab="review"]')[0].click();
  loadReview();
});

$("#btnScan").addEventListener("click", async () => {
  const el = $("#scanResult");
  const root = $("#scanRoot").value.trim();
  if (!root) return alert("Enter scan root path");
  try {
    log(el, await api("/api/scan", {
      method: "POST",
      body: JSON.stringify({ root, workers: +$("#scanWorkers").value }),
    }));
    loadReport();
  } catch (e) {
    log(el, e.message);
  }
});

$("#btnPipeline").addEventListener("click", async () => {
  const el = $("#scanResult");
  const root = $("#scanRoot").value.trim();
  if (!root) return alert("Enter scan root path");
  try {
    log(el, await api("/api/pipeline", {
      method: "POST",
      body: JSON.stringify({ root, workers: +$("#scanWorkers").value }),
    }));
    loadReport();
    loadReview();
    loadLineage();
  } catch (e) {
    log(el, e.message);
  }
});

$("#btnReloadGroups").addEventListener("click", loadReview);
$("#btnReloadLineage").addEventListener("click", loadLineage);
$("#btnReloadAssets").addEventListener("click", loadAssets);

function bootstrapTokenFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const token = params.get("token") || hash.get("token");
  if (token) {
    localStorage.setItem("matrix_token", token.trim());
    history.replaceState(null, "", window.location.pathname);
  }
}

bootstrapTokenFromUrl();
loadReport();
loadReview();
connectEvents();