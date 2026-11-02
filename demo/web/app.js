/* MAM 产品原型 · 前端（原生 JS，无构建） */
const state = {
  me: null,
  users: [],
  boot: null,
  tab: null,
  share: new URLSearchParams(location.search).get("share") || "",
  shipPreview: null,
  batchProject: "",
};

const ROLE_LABEL = { fan: "影迷", group: "观影团", channel: "渠道方", admin: "管理员" };
const VIS_LABEL = { public: "公开报名", admitted: "仅准入", private: "私密" };
const TABS = {
  fan: [["projects", "项目广场"]],
  group: [["projects", "项目广场"], ["mine", "我的申请"], ["feedback", "返图与流团"]],
  channel: [["projects", "我的项目"], ["review", "申请审核与发货"], ["feedback", "返图评分"], ["metrics", "数据"]],
  admin: [["certs", "认证审核"], ["projects", "项目"], ["metrics", "数据"]],
};

const $ = (sel) => document.querySelector(sel);

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    method: opts.method || "GET",
    headers: { "X-Demo-User": state.me ? state.me.id : 1, "Content-Type": "application/json" },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "请求失败");
  return data;
}

function stText(s) {
  return (state.boot.status_labels || {})[s] || s;
}
function stHtml(s) {
  return `<span class="st-${esc(s)}">${esc(stText(s))}</span>`;
}

/* ---------------------------------------------------------------- 启动 */

async function boot() {
  const data = await api("/api/bootstrap");
  state.boot = data;
  state.users = data.users;
  const saved = localStorage.getItem("mam-demo-user");
  const fromUrl = new URLSearchParams(location.search).get("user");
  state.me = data.users.find((u) => String(u.id) === (fromUrl || saved)) || data.users.find((u) => u.id === 2);
  const sel = $("#user-select");
  sel.innerHTML = data.users.map((u) =>
    `<option value="${u.id}" ${u.id === state.me.id ? "selected" : ""}>${esc(u.display)} · ${ROLE_LABEL[u.role]}</option>`
  ).join("");
  sel.onchange = () => {
    state.me = state.users.find((u) => String(u.id) === sel.value);
    localStorage.setItem("mam-demo-user", String(state.me.id));
    state.tab = TABS[state.me.role][0][0];
    state.shipPreview = null;
    render();
  };
  $("#role-badge").textContent = ROLE_LABEL[state.me.role];
  const tabParam = new URLSearchParams(location.search).get("tab");
  if (tabParam && TABS[state.me.role].some((t) => t[0] === tabParam)) state.tab = tabParam;
  render();
  const applyParam = new URLSearchParams(location.search).get("apply");
  if (applyParam && state.me.role === "group") {
    openApply(Number(applyParam)).catch((e) => toast(e.message, true));
  }
}

function render() {
  $("#role-badge").textContent = ROLE_LABEL[state.me.role];
  const tabs = TABS[state.me.role];
  if (!state.tab || !tabs.some((t) => t[0] === state.tab)) state.tab = tabs[0][0];
  $("#tabs").innerHTML = tabs.map(([k, label]) =>
    `<button data-tab="${k}" class="${k === state.tab ? "active" : ""}">${esc(label)}</button>`
  ).join("");
  const view = $("#view");
  view.innerHTML = '<div class="empty">加载中…</div>';
  const fn = {
    projects: renderProjects,
    mine: renderMine,
    review: renderReview,
    feedback: renderFeedback,
    certs: renderCerts,
    metrics: renderMetrics,
  }[state.tab];
  fn().catch((e) => { view.innerHTML = `<div class="err">${esc(e.message)}</div>`; });
}

/* ---------------------------------------------------------------- 项目 */

async function renderProjects() {
  const q = state.share ? `?share=${encodeURIComponent(state.share)}` : "";
  const data = await api(`/api/projects${q}`);
  const view = $("#view");
  const canShare = ["fan", "group"].includes(state.me.role);
  const shareBox = canShare && state.boot.private_projects.length ? `
    <div class="card">
      <h3>演示辅助：私密项目分享入口</h3>
      <div class="meta">私密项目不会出现在广场。粘贴分享凭证后可访问（对应「直通本项目」的分享模式）。</div>
      <div class="row" style="margin-top:10px">
        <input id="share-input" type="text" placeholder="分享凭证，例如 ${esc(state.boot.private_projects[0].share_token)}"
               value="${esc(state.share)}" style="max-width:320px">
        <button class="primary" data-action="open-share">打开分享链接</button>
      </div>
    </div>` : "";

  if (!data.projects.length) {
    view.innerHTML = shareBox + '<div class="card empty">当前身份下没有可见项目</div>';
    return;
  }
  view.innerHTML = shareBox + `<div class="grid">${data.projects.map((p) => projectCard(p)).join("")}</div>`;
}

function projectCard(p) {
  const actions = [];
  if (state.me.role === "group") {
    actions.push(p.can_apply
      ? `<button class="primary" data-action="open-apply" data-id="${p.id}">填写申请表</button>`
      : `<button class="ghost" disabled>${esc(p.block_reason || "不可申请")}</button>`);
    actions.push(`<button class="ghost" data-action="open-detail" data-id="${p.id}">详情</button>`);
  } else if (state.me.role === "channel") {
    actions.push(`<button class="ghost" data-action="open-detail" data-id="${p.id}">详情</button>`);
    if (p.share_token) {
      actions.push(`<button class="ghost" data-action="copy-share" data-token="${esc(p.share_token)}">复制分享凭证</button>`);
    }
  } else {
    actions.push(`<button class="ghost" data-action="open-detail" data-id="${p.id}">详情</button>`);
  }
  return `<div class="card">
    <div class="spread">
      <h3>${esc(p.title)}</h3>
      <div class="row" style="gap:6px">
        <span class="badge">${esc(VIS_LABEL[p.visibility] || p.visibility)}</span>
        <span class="badge neutral">${esc(stText(p.status))}</span>
      </div>
    </div>
    <div class="meta">${esc(p.film)} · ${esc(p.channel_name)} <span class="tag">${esc(p.channel_tag)}</span></div>
    <div class="meta">报名 ${esc(p.start_at)} ~ ${esc(p.end_at)}</div>
    <div class="row" style="margin-top:10px">${actions.join("")}</div>
  </div>`;
}

async function openApply(id, existing) {
  const q = state.share ? `?share=${encodeURIComponent(state.share)}` : "";
  const p = await api(`/api/projects/${id}${q}`);
  const values = existing ? existing.form_values : Object.assign({}, p.prefill || {});
  const fields = p.form_schema.map((f) => fieldHtml(f, values[f.key])).join("");
  openModal(`
    <h3>${existing ? "修改并重新提交" : "填写申请表"} · ${esc(p.title)}</h3>
    <div class="meta">${esc(p.channel_name)} <span class="tag">${esc(VIS_LABEL[p.visibility])}</span></div>
    <form id="apply-form" style="margin-top:14px">${fields}
      <div class="err" id="form-err"></div>
      <div class="row" style="margin-top:12px">
        <button class="primary" type="submit">${existing ? "重新提交" : "提交申请"}</button>
        <button class="ghost" type="button" data-action="close-modal">取消</button>
      </div>
    </form>`);
  $("#apply-form").onsubmit = async (e) => {
    e.preventDefault();
    const values = readForm(e.target);
    try {
      if (existing) {
        await api(`/api/applications/${existing.id}/resubmit`, { method: "POST", body: { values } });
      } else {
        await api(`/api/projects/${p.id}/apply`, { method: "POST", body: { values, share: state.share || null } });
      }
      closeModal();
      toast(existing ? "已重新提交，等待审核" : "已提交，等待审核");
      render();
    } catch (err) {
      $("#form-err").textContent = err.message;
    }
  };
}

function fieldHtml(f, value) {
  const v = value == null ? "" : value;
  let input;
  if (f.type === "number") {
    input = `<input type="number" name="${esc(f.key)}" value="${esc(v)}" min="1">`;
  } else if (f.type === "datetime") {
    input = `<input type="datetime-local" name="${esc(f.key)}" value="${esc(String(v).replace(" ", "T"))}">`;
  } else {
    input = `<input type="text" name="${esc(f.key)}" value="${esc(v)}">`;
  }
  return `<label class="field"><span>${esc(f.label)}${f.required ? " *" : ""}</span>${input}</label>`;
}

function readForm(form) {
  const out = {};
  new FormData(form).forEach((v, k) => {
    let val = String(v).trim();
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(val)) val = val.replace("T", " ");
    out[k] = val;
  });
  return out;
}

async function openDetail(id) {
  const q = state.share ? `?share=${encodeURIComponent(state.share)}` : "";
  const p = await api(`/api/projects/${id}${q}`);
  const fields = p.form_schema.map((f) =>
    `<tr><td>${esc(f.label)}</td><td>${f.required ? "必填" : "选填"}</td></tr>`).join("");
  openModal(`
    <h3>${esc(p.title)}</h3>
    <div class="meta">${esc(p.film)} · ${esc(p.channel_name)} · ${esc(VIS_LABEL[p.visibility])}</div>
    <div class="meta">报名窗口：${esc(p.start_at)} ~ ${esc(p.end_at)}</div>
    ${p.block_reason ? `<div class="err">${esc(p.block_reason)}</div>` : ""}
    <h3 style="margin-top:16px">报名表字段</h3>
    <table><thead><tr><th>字段</th><th>要求</th></tr></thead><tbody>${fields}</tbody></table>
    <div class="row" style="margin-top:14px"><button class="ghost" data-action="close-modal">关闭</button></div>`);
}

/* ---------------------------------------------------------------- 我的申请 */

async function renderMine() {
  const { applications } = await api("/api/my/applications");
  const rows = applications.map((a) => {
    const acts = [];
    if (a.status === "rejected") {
      acts.push(`<button class="primary" data-action="resubmit" data-id="${a.id}">修改重提</button>`);
    }
    if (["approved", "shipped"].includes(a.status)) {
      acts.push(`<button class="ghost" data-action="feedback" data-id="${a.id}">提交返图</button>`);
      acts.push(`<button class="danger" data-action="cancel" data-id="${a.id}">流团</button>`);
    }
    return `<tr>
      <td>${esc(a.project_title)}<div class="hint">${esc(a.film)}</div></td>
      <td>${esc(a.form_values.session_time || "")}</td>
      <td>${a.qty}</td>
      <td>${stHtml(a.status)}<div class="hint">v${a.review_version}</div></td>
      <td>${esc(a.note || "")}</td>
      <td>${a.track_no ? esc(a.carrier + " " + a.track_no) : '<span class="hint">—</span>'}</td>
      <td>${acts.join(" ")}</td>
    </tr>`;
  }).join("");
  $("#view").innerHTML = `<div class="card">
    <h3>我的申请</h3>
    <div class="meta">驳回后可修改重提；已通过 / 已发货可提交返图或申请流团。</div>
    <table style="margin-top:12px"><thead><tr>
      <th>项目</th><th>场次</th><th>数量</th><th>状态</th><th>审核备注</th><th>物流</th><th>操作</th>
    </tr></thead><tbody>${rows || '<tr><td colspan="7" class="empty">还没有申请</td></tr>'}</tbody></table>
  </div>`;
}

async function openResubmit(id) {
  const { applications } = await api("/api/my/applications");
  const a = applications.find((x) => x.id === id);
  openApply(a.project_id, a);
}

/* ---------------------------------------------------------------- 审核 / 发货 */

async function renderReview() {
  const { applications } = await api("/api/channel/applications");
  const approved = applications.filter((a) => a.status === "approved");
  const projects = [...new Map(approved.map((a) => [a.project_id, a.project_title])).entries()];

  const batchCard = `
    <div class="card">
      <h3>批量发货</h3>
      <div class="meta">导出 → 填写 → 上传 → <b>预览</b> → 确认。预览后任何一条申请变化，整批停止。</div>
      <div class="row" style="margin-top:10px">
        <select id="batch-project" style="max-width:320px">
          <option value="">选择有「已通过」申请的项目</option>
          ${projects.map(([pid, title]) => `<option value="${pid}" ${String(pid) === String(state.batchProject) ? "selected" : ""}>${esc(title)}</option>`).join("")}
        </select>
        <button class="primary" data-action="batch-load">载入待发货申请</button>
      </div>
      <div id="batch-body"></div>
    </div>`;

  const rows = applications.map((a) => {
    const acts = [];
    if (a.status === "pending") {
      acts.push(`<button class="ok" data-action="approve" data-id="${a.id}">通过</button>`);
      acts.push(`<button class="danger" data-action="reject" data-id="${a.id}">驳回</button>`);
    }
    if (a.status === "approved") {
      acts.push(`<button class="primary" data-action="ship-one" data-id="${a.id}">填单号发货</button>`);
    }
    return `<tr>
      <td>#${a.id}<div class="hint">${esc(a.project_title)}</div></td>
      <td>${esc(a.group_name)}</td>
      <td>${esc(a.form_values.session_time || "")}<div class="hint">${esc(a.form_values.cinema || "")}</div></td>
      <td>${a.qty}</td>
      <td>${stHtml(a.status)}</td>
      <td>${a.track_no ? esc(a.carrier + " " + a.track_no) : '<span class="hint">—</span>'}</td>
      <td>${acts.join(" ") || '<span class="hint">—</span>'}</td>
    </tr>`;
  }).join("");

  $("#view").innerHTML = batchCard + `<div class="card">
    <h3>申请审核</h3>
    <div class="meta">待审核优先，其次按提交时间正序。</div>
    <table style="margin-top:12px"><thead><tr>
      <th>申请</th><th>观影团</th><th>场次</th><th>数量</th><th>状态</th><th>物流</th><th>操作</th>
    </tr></thead><tbody>${rows || '<tr><td colspan="7" class="empty">暂无申请</td></tr>'}</tbody></table>
  </div>`;

  if (state.batchProject) await loadBatch(state.batchProject);
  if (state.shipPreview) renderPreview();
}

async function loadBatch(pid) {
  if (!pid) return;
  const { applications } = await api("/api/channel/applications");
  const list = applications.filter((a) => String(a.project_id) === String(pid) && a.status === "approved");
  const body = $("#batch-body");
  if (!body) return;
  if (!list.length) {
    body.innerHTML = '<div class="empty">该项目没有待发货的申请</div>';
    return;
  }
  body.innerHTML = `<table style="margin-top:12px"><thead><tr>
      <th>申请</th><th>观影团</th><th>数量</th><th>收件信息</th><th>快递单号</th>
    </tr></thead><tbody>${list.map((a) => `
      <tr>
        <td>#${a.id}</td>
        <td>${esc(a.group_name)}</td>
        <td>${a.qty}</td>
        <td>${esc(a.form_values.receiver || "")} ${esc(a.form_values.phone || "")}<div class="hint">${esc(a.form_values.address || "")}</div></td>
        <td><input type="text" class="track-input" data-id="${a.id}" placeholder="填写单号"></td>
      </tr>`).join("")}</tbody></table>
    <div class="row" style="margin-top:12px">
      <button class="primary" data-action="batch-preview" data-project="${pid}">预览</button>
      <span class="hint">未填单号的行会被跳过</span>
    </div>`;
}

async function previewBatch(pid) {
  const rows = [...document.querySelectorAll(".track-input")]
    .map((el) => ({ application_id: Number(el.dataset.id), track_no: el.value.trim() }))
    .filter((r) => r.track_no);
  try {
    const data = await api(`/api/projects/${pid}/ship/preview`, { method: "POST", body: { rows } });
    state.shipPreview = { ...data, projectId: pid };
    renderPreview();
  } catch (e) {
    toast(e.message, true);
  }
}

function renderPreview() {
  const body = $("#batch-body");
  if (!body || !state.shipPreview) return;
  const p = state.shipPreview;
  body.innerHTML += `<div class="card" style="margin-top:14px;background:#fffdf5">
    <h3>预览结果（快照 ${p.expires_in}s 内有效）</h3>
    <table><thead><tr><th>申请</th><th>观影团</th><th>数量</th><th>收件信息</th><th>单号</th></tr></thead>
    <tbody>${p.rows.map((r) => `<tr>
      <td>#${r.application_id}</td><td>${esc(r.group_name)}</td><td>${r.qty}</td>
      <td>${esc(r.receiver)} ${esc(r.phone)}<div class="hint">${esc(r.address)}</div></td>
      <td><code>${esc(r.track_no)}</code></td></tr>`).join("")}</tbody></table>
    <div class="row" style="margin-top:12px">
      <button class="ok" data-action="batch-confirm" data-project="${p.projectId}" data-token="${p.token}">确认发货（整批）</button>
      <button class="ghost" data-action="batch-discard">放弃预览</button>
    </div>
    <div class="hint" style="margin-top:8px">提示：预览后如果另一处修改了这些申请，确认会被拒绝并要求重新预览。</div>
  </div>`;
}

/* ---------------------------------------------------------------- 返图 / 评分 */

async function renderFeedback() {
  const view = $("#view");
  if (state.me.role === "group") {
    const { applications } = await api("/api/my/applications");
    const list = applications.filter((a) => ["approved", "shipped", "feedback", "completed"].includes(a.status));
    view.innerHTML = `<div class="card">
      <h3>返图与流团</h3>
      <div class="meta">已通过 / 已发货的申请可提交返图；活动办不了可申请流团（需备注）。</div>
      <table style="margin-top:12px"><thead><tr>
        <th>项目</th><th>状态</th><th>返图</th><th>评分</th><th>操作</th></tr></thead><tbody>
        ${list.map((a) => `<tr>
          <td>${esc(a.project_title)}<div class="hint">${esc(a.form_values.session_time || "")}</div></td>
          <td>${stHtml(a.status)}</td>
          <td>${a.feedback ? esc(a.feedback.photos || "已提交") : '<span class="hint">—</span>'}</td>
          <td>${a.score ? "★".repeat(a.score) + `<div class="hint">${esc(a.comment || "")}</div>` : '<span class="hint">—</span>'}</td>
          <td>${["approved", "shipped"].includes(a.status)
            ? `<button class="primary" data-action="feedback" data-id="${a.id}">提交返图</button>
               <button class="danger" data-action="cancel" data-id="${a.id}">流团</button>`
            : '<span class="hint">—</span>'}</td>
        </tr>`).join("") || '<tr><td colspan="5" class="empty">暂无记录</td></tr>'}
      </tbody></table></div>`;
    return;
  }
  const { applications } = await api("/api/channel/applications");
  const list = applications.filter((a) => a.status === "feedback");
  view.innerHTML = `<div class="card">
    <h3>返图评分</h3>
    <div class="meta">评分后申请归档为「已完成」，并计入团体历史评分。</div>
    <table style="margin-top:12px"><thead><tr>
      <th>申请</th><th>观影团</th><th>返图</th><th>操作</th></tr></thead><tbody>
      ${list.map((a) => `<tr>
        <td>#${a.id}<div class="hint">${esc(a.project_title)}</div></td>
        <td>${esc(a.group_name)}</td>
        <td>${esc((a.feedback && a.feedback.photos) || "—")}</td>
        <td><button class="primary" data-action="score" data-id="${a.id}">评分</button></td>
      </tr>`).join("") || '<tr><td colspan="4" class="empty">没有待评分的返图</td></tr>'}
    </tbody></table></div>`;
}

async function openFeedback(id) {
  const { applications } = await api("/api/my/applications");
  const a = applications.find((x) => x.id === id);
  const p = await api(`/api/projects/${a.project_id}${state.share ? "?share=" + encodeURIComponent(state.share) : ""}`);
  const fields = p.result_schema.map((f) => fieldHtml(f, (a.feedback || {})[f.key])).join("");
  openModal(`<h3>提交返图 · ${esc(a.project_title)}</h3>
    <form id="feedback-form">${fields}
      <div class="err" id="form-err"></div>
      <div class="row" style="margin-top:12px">
        <button class="primary" type="submit">提交</button>
        <button class="ghost" type="button" data-action="close-modal">取消</button>
      </div>
    </form>`);
  $("#feedback-form").onsubmit = async (e) => {
    e.preventDefault();
    try {
      await api(`/api/applications/${id}/feedback`, { method: "POST", body: { values: readForm(e.target) } });
      closeModal(); toast("返图已提交"); render();
    } catch (err) { $("#form-err").textContent = err.message; }
  };
}

/* ---------------------------------------------------------------- 管理端 */

async function renderCerts() {
  const { certs } = await api("/api/admin/certs");
  const rows = certs.map((c) => {
    const acts = c.status === "pending"
      ? `<button class="ok" data-action="cert-ok" data-id="${c.id}">通过</button>
         <button class="danger" data-action="cert-no" data-id="${c.id}">驳回</button>`
      : `<span class="hint">已处理</span>`;
    return `<tr><td>#${c.id}</td><td>${esc(c.name)}</td>
      <td>${c.type === "group" ? "观影团" : "渠道方"}</td>
      <td>${esc(c.payload)}</td><td>${stHtml(c.status)}</td><td>${acts}</td></tr>`;
  }).join("");
  $("#view").innerHTML = `<div class="card">
    <h3>认证审核</h3>
    <div class="meta">认证通过即授予角色，取消认证即回收（演示中只改状态）。</div>
    <table style="margin-top:12px"><thead><tr><th>#</th><th>名称</th><th>类型</th><th>材料</th><th>状态</th><th>操作</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`;
}

async function renderMetrics() {
  const m = await api("/api/metrics");
  $("#view").innerHTML = `<div class="card">
    <h3>业务概览</h3>
    <div class="meta">数字随演示操作实时变化。真实口径见 docs/06-数据口径与待补.md。</div>
    <div class="funnel" style="margin-top:14px">
      ${Object.entries(m.funnel).map(([k, v]) => `<div><b>${v}</b><span class="hint">${esc(k)}</span></div>`).join("")}
    </div>
    <h3 style="margin-top:18px">结构</h3>
    <table><tbody>
      <tr><td>渠道方</td><td>${m.channels}</td></tr>
      <tr><td>观影团</td><td>${m.groups}</td></tr>
      <tr><td>准入关系</td><td>${m.admissions}</td></tr>
      <tr><td>已发布项目</td><td>${m.projects_published}</td></tr>
      <tr><td>申请总数</td><td>${m.applications}</td></tr>
    </tbody></table></div>`;
}

/* ---------------------------------------------------------------- 交互 */

document.addEventListener("click", async (e) => {
  const el = e.target.closest("[data-tab],[data-action]");
  if (!el) return;
  const tab = el.dataset.tab;
  if (tab) { state.tab = tab; state.shipPreview = null; render(); return; }

  const action = el.dataset.action;
  const id = Number(el.dataset.id || 0);
  try {
    switch (action) {
      case "close-modal": closeModal(); break;
      case "open-apply": await openApply(id); break;
      case "open-detail": await openDetail(id); break;
      case "open-share": {
        state.share = $("#share-input").value.trim();
        history.replaceState(null, "", state.share ? `?share=${encodeURIComponent(state.share)}` : "/");
        render(); break;
      }
      case "copy-share":
        await navigator.clipboard.writeText(el.dataset.token).catch(() => {});
        toast("凭证已复制：" + el.dataset.token); break;
      case "resubmit": await openResubmit(id); break;
      case "feedback": await openFeedback(id); break;
      case "cancel": await openCancel(id); break;
      case "approve": await review(id, "approve"); break;
      case "reject": await review(id, "reject"); break;
      case "ship-one": await openShipOne(id); break;
      case "score": await openScore(id); break;
      case "batch-load":
        state.batchProject = $("#batch-project").value;
        state.shipPreview = null;
        await loadBatch(state.batchProject); break;
      case "batch-preview": await previewBatch(Number(el.dataset.project)); break;
      case "batch-discard": state.shipPreview = null; await loadBatch(state.batchProject); break;
      case "batch-confirm": await confirmBatch(Number(el.dataset.project), el.dataset.token); break;
      case "cert-ok": await certReview(id, "approve"); break;
      case "cert-no": await certReview(id, "reject"); break;
    }
  } catch (err) {
    toast(err.message, true);
  }
});

async function review(id, action) {
  if (action === "reject") {
    openModal(`<h3>驳回申请 #${id}</h3>
      <label class="field"><span>驳回原因（会展示给观影团）</span>
      <input type="text" id="reject-note" value="成团证明不清晰，请重新上传"></label>
      <div class="row"><button class="danger" data-action="do-reject" data-id="${id}">确认驳回</button>
      <button class="ghost" data-action="close-modal">取消</button></div>`);
    return;
  }
  await api(`/api/applications/${id}/review`, { method: "POST", body: { action } });
  toast("已通过"); render();
}

document.addEventListener("click", async (e) => {
  const el = e.target.closest('[data-action="do-reject"]');
  if (!el) return;
  const note = $("#reject-note").value.trim();
  await api(`/api/applications/${el.dataset.id}/review`, { method: "POST", body: { action: "reject", note } });
  closeModal(); toast("已驳回"); render();
});

async function openShipOne(id) {
  openModal(`<h3>发货 · 申请 #${id}</h3>
    <label class="field"><span>快递公司</span><input type="text" id="carrier" value="示例快递"></label>
    <label class="field"><span>快递单号</span><input type="text" id="track" placeholder="至少 4 位"></label>
    <div class="err" id="form-err"></div>
    <div class="row"><button class="primary" data-action="do-ship" data-id="${id}">确认发货</button>
    <button class="ghost" data-action="close-modal">取消</button></div>`);
}

document.addEventListener("click", async (e) => {
  const el = e.target.closest('[data-action="do-ship"]');
  if (!el) return;
  try {
    await api(`/api/applications/${el.dataset.id}/ship`, {
      method: "POST",
      body: { carrier: $("#carrier").value, track_no: $("#track").value },
    });
    closeModal(); toast("已发货"); render();
  } catch (err) { $("#form-err").textContent = err.message; }
});

async function confirmBatch(pid, token) {
  const data = await api(`/api/projects/${pid}/ship/confirm`, { method: "POST", body: { token } });
  state.shipPreview = null;
  toast(`已整批发货 ${data.shipped} 单`);
  render();
}

async function openCancel(id) {
  openModal(`<h3>申请流团 · #${id}</h3>
    <div class="meta">流团后不能再提交返图，备注会展示给渠道方。</div>
    <label class="field"><span>流团原因 *</span><input type="text" id="cancel-note" placeholder="例如：影城临时取消场次"></label>
    <div class="err" id="form-err"></div>
    <div class="row"><button class="danger" data-action="do-cancel" data-id="${id}">确认流团</button>
    <button class="ghost" data-action="close-modal">取消</button></div>`);
}

document.addEventListener("click", async (e) => {
  const el = e.target.closest('[data-action="do-cancel"]');
  if (!el) return;
  try {
    await api(`/api/applications/${el.dataset.id}/cancel`, {
      method: "POST", body: { note: $("#cancel-note").value.trim() },
    });
    closeModal(); toast("已流团"); render();
  } catch (err) { $("#form-err").textContent = err.message; }
});

async function openScore(id) {
  openModal(`<h3>评分 · 申请 #${id}</h3>
    <label class="field"><span>评分（1-5）</span><input type="number" id="score" min="1" max="5" value="5"></label>
    <label class="field"><span>评论（选填）</span><input type="text" id="comment" placeholder="例如：返图清晰，物料露出完整"></label>
    <div class="err" id="form-err"></div>
    <div class="row"><button class="primary" data-action="do-score" data-id="${id}">提交评分</button>
    <button class="ghost" data-action="close-modal">取消</button></div>`);
}

document.addEventListener("click", async (e) => {
  const el = e.target.closest('[data-action="do-score"]');
  if (!el) return;
  try {
    await api(`/api/applications/${el.dataset.id}/score`, {
      method: "POST", body: { score: Number($("#score").value), comment: $("#comment").value.trim() },
    });
    closeModal(); toast("评分已提交"); render();
  } catch (err) { $("#form-err").textContent = err.message; }
});

async function certReview(id, action) {
  await api(`/api/admin/certs/${id}/review`, { method: "POST", body: { action } });
  toast(action === "approve" ? "已通过" : "已驳回");
  render();
}

/* ---------------------------------------------------------------- 通用 */

function openModal(html) {
  const m = $("#modal");
  m.innerHTML = `<div class="sheet">${html}</div>`;
  m.classList.remove("hidden");
}
function closeModal() {
  const m = $("#modal");
  m.classList.add("hidden");
  m.innerHTML = "";
}
function toast(msg, isErr) {
  const t = document.createElement("div");
  t.textContent = msg;
  t.style.cssText = `position:fixed;left:50%;bottom:32px;transform:translateX(-50%);
    background:${isErr ? "#b91c1c" : "#111827"};color:#fff;padding:9px 16px;border-radius:8px;
    font-size:13px;z-index:99;box-shadow:0 6px 20px rgba(0,0,0,.18)`;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2400);
}

boot().catch((e) => {
  document.body.innerHTML = `<pre style="padding:24px;color:#b91c1c">启动失败：${esc(e.message)}\n请确认通过 python3 app.py 启动服务，而不是直接打开 HTML 文件。</pre>`;
});
