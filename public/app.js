const state = { data: null, currentUserId: localStorage.getItem('gpu-share-user') || 'user_alice' };
const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[char]));
const formatTime = (value) => new Date(value).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
const api = async (url, options = {}) => {
  const response = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || '请求失败');
  return payload;
};
const currentUser = () => state.data?.users.find((user) => user.id === state.currentUserId) || state.data?.users[0];
const showToast = (message) => {
  const toast = $('#toast');
  toast.textContent = message;
  toast.classList.remove('hidden');
  setTimeout(() => toast.classList.add('hidden'), 2600);
};
const setModal = (html) => {
  $('#modalContent').innerHTML = html;
  $('#modalBackdrop').classList.remove('hidden');
};
const closeModal = () => $('#modalBackdrop').classList.add('hidden');

function render() {
  const data = state.data;
  if (!data) return;
  const onlineNodes = data.nodes.filter((node) => node.status === 'online');
  const gpuTotal = data.nodes.reduce((sum, node) => sum + node.gpuSlots, 0);
  const gpuAvailable = data.nodes.reduce((sum, node) => sum + node.gpuAvailable, 0);
  const cpuTotal = data.nodes.reduce((sum, node) => sum + node.cpuSlots, 0);
  const cpuAvailable = data.nodes.reduce((sum, node) => sum + node.cpuAvailable, 0);
  const running = data.tasks.filter((task) => ['running', 'partial'].includes(task.status)).length;
  const metrics = [
    ['在线节点', onlineNodes.length, `来自 ${new Set(onlineNodes.map((node) => node.ownerId)).size} 位用户`],
    ['可用 GPU', gpuAvailable, `共 ${gpuTotal} 个共享槽位`],
    ['可用 CPU', cpuAvailable, `共 ${cpuTotal} 个共享槽位`],
    ['运行中任务', running, `${data.tasks.length} 个任务已提交`]
  ];
  $('#metrics').innerHTML = metrics.map(([label, value, foot]) => `<div class="metric"><div class="metric-label">${label}</div><div class="metric-value">${value}<small>${label.includes('节点') ? '台' : '个'}</small></div><div class="metric-foot">↗ ${foot}</div></div>`).join('');
  const platformName = (platform) => platform === 'win32' ? 'Windows' : platform === 'darwin' ? 'macOS' : 'Linux';
  $('#nodesTable').innerHTML = data.nodes.map((node) => {
    const isBusy = node.gpuUsed + node.cpuUsed > 0;
    const capacity = node.gpuSlots || node.cpuSlots;
    const used = node.gpuUsed + node.cpuUsed;
    const percent = capacity ? Math.round((used / capacity) * 100) : 0;
    return `<tr>
      <td><div class="node-name">${escapeHtml(node.name)}</div><div class="node-owner">由 ${escapeHtml(node.ownerName)} 分享</div></td>
      <td><span class="platform-tag">${platformName(node.platform)}</span></td>
      <td><div class="hardware">${escapeHtml(node.gpuName || 'CPU only')}<br>${escapeHtml(node.cpuModel)}</div></td>
      <td><div class="resource-meta"><div class="resource-bar"><i style="width:${percent}%"></i></div><span>${node.gpuSlots ? `${node.gpuAvailable}/${node.gpuSlots} GPU` : `${node.cpuAvailable}/${node.cpuSlots} CPU`}</span></div></td>
      <td><div class="status-badge ${node.status !== 'online' ? 'offline' : isBusy ? 'busy' : ''}"><i class="dot ${node.status !== 'online' ? 'offline' : isBusy ? 'busy' : 'online'}"></i>${node.status !== 'online' ? '离线' : isBusy ? '部分使用' : '在线'}</div></td>
    </tr>`;
  }).join('');
  $('#tasksList').innerHTML = data.tasks.length ? data.tasks.map(renderTask).join('') : '<div class="task-card"><div class="task-title">还没有任务</div><div class="task-subtitle">创建一个任务，调度器会从所有用户共享的设备中自动分配 worker。</div></div>';
  $('#eventsList').innerHTML = data.events.slice(0, 7).map((event) => `<div class="event"><div class="event-message">${escapeHtml(event.message)}</div><div class="event-time">${formatTime(event.at)} · ${event.type.toUpperCase()}</div></div>`).join('');
  $('#currentUserName').textContent = currentUser()?.name || '用户';
  $('.avatar').textContent = (currentUser()?.name || 'U').slice(0, 1).toUpperCase();
  $('#connectionText').textContent = '资源池已连接';
}

function renderTask(task) {
  const statusText = { running: 'RUNNING', partial: 'PARTIAL', queued: 'QUEUED', completed: 'COMPLETED', stopped: 'STOPPED' }[task.status] || task.status.toUpperCase();
  const assignmentOwners = [...new Set(task.assignments.map((assignment) => assignment.ownerName))];
  const owners = assignmentOwners.length ? assignmentOwners.join('、') : '等待可用资源';
  return `<div class="task-card">
    <div class="task-top"><div><div class="task-title">${escapeHtml(task.name)}</div><div class="task-subtitle">${escapeHtml(task.framework)} · ${task.resourceType.toUpperCase()} · ${escapeHtml(task.privacyMode)}</div></div><div class="task-status ${task.status}">${statusText}</div></div>
    <div class="progress-track"><i style="width:${task.progress || 0}%"></i></div>
    <div class="task-bottom"><div class="task-meta"><span><b>${task.allocatedWorkers}/${task.workers}</b> workers</span><span>设备来自 <b>${escapeHtml(owners)}</b></span></div>${['running', 'partial', 'queued'].includes(task.status) ? `<button class="stop-button" data-stop="${task.id}">停止任务</button>` : ''}</div>
  </div>`;
}

async function refresh() {
  try {
    state.data = await api('/api/state');
    if (!state.data.users.some((user) => user.id === state.currentUserId)) state.currentUserId = state.data.users[0]?.id;
    localStorage.setItem('gpu-share-user', state.currentUserId);
    render();
  } catch (error) {
    $('#connectionText').textContent = '服务未启动';
    showToast(error.message);
  }
}

function openTaskModal() {
  const users = state.data.users.map((user) => `<option value="${user.id}" ${user.id === state.currentUserId ? 'selected' : ''}>${escapeHtml(user.name)}</option>`).join('');
  setModal(`<div class="eyebrow">NEW COMPUTE JOB</div><h2>创建计算任务</h2>
    <form class="form-grid" id="taskForm">
      <div class="field"><label>任务名称</label><input name="name" value="联邦训练实验 ${new Date().getHours()}:${String(new Date().getMinutes()).padStart(2, '0')}" required></div>
      <div class="form-row"><div class="field"><label>任务拥有者</label><select name="requesterId">${users}</select></div><div class="field"><label>框架</label><select name="framework"><option>PyTorch</option><option>TensorFlow</option><option>JAX</option><option>SecretFlow</option></select></div></div>
      <div class="form-row"><div class="field"><label>资源类型</label><select name="resourceType"><option value="gpu">GPU</option><option value="cpu">CPU</option></select></div><div class="field"><label>Worker 数量</label><input name="workers" type="number" min="1" max="64" value="2" required></div></div>
      <div class="form-row"><div class="field"><label>隐私模式</label><select name="privacyMode"><option value="secure-aggregate">SPU / 安全聚合</option><option value="tee">TEE 执行</option><option value="trusted">可信节点明文</option></select></div><div class="field"><label>演示时长（秒）</label><input name="durationSeconds" type="number" min="10" max="3600" value="45"></div></div>
      <div class="field"><label>训练命令</label><input name="command" value="python train.py --epochs 10"></div>
      <div class="modal-note">调度器会从所有在线用户共享的设备中分配 worker。资源不足时任务保持排队，节点上线或其他任务结束后自动重试。</div>
      <button class="primary-button form-submit">提交任务</button>
    </form>`);
  $('#taskForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await api('/api/tasks', { method: 'POST', body: JSON.stringify(Object.fromEntries(form.entries())) });
      closeModal(); await refresh(); showToast('任务已提交，正在跨节点分配资源');
    } catch (error) { showToast(error.message); }
  });
}

function openNodeModal() {
  const users = state.data.users.map((user) => `<option value="${user.id}" ${user.id === state.currentUserId ? 'selected' : ''}>${escapeHtml(user.name)}</option>`).join('');
  setModal(`<div class="eyebrow">SHARE DEVICE</div><h2>分享一台设备</h2>
    <form class="form-grid" id="nodeForm">
      <div class="field"><label>节点名称</label><input name="name" value="${escapeHtml(currentUser().name)} 的新节点" required></div>
      <div class="form-row"><div class="field"><label>设备拥有者</label><select name="ownerId">${users}</select></div><div class="field"><label>平台</label><select name="platform"><option value="win32">Windows</option><option value="linux">Linux</option><option value="darwin">macOS</option></select></div></div>
      <div class="form-row"><div class="field"><label>CPU 共享槽位</label><input name="cpuSlots" type="number" min="0" max="256" value="8"></div><div class="field"><label>GPU 共享槽位</label><input name="gpuSlots" type="number" min="0" max="16" value="1"></div></div>
      <div class="form-row"><div class="field"><label>GPU 型号</label><input name="gpuName" value="NVIDIA RTX 4090"></div><div class="field"><label>显存 / 内存 GB</label><input name="memoryGb" type="number" min="0" value="24"></div></div>
      <div class="field"><label>CPU 型号</label><input name="cpuModel" value="Generic CPU"></div>
      <div class="modal-note">真实设备推荐使用项目内的 Node Agent 注册。这里的表单用于快速演示多用户资源进入共享池。</div>
      <button class="primary-button form-submit">加入共享池</button>
    </form>`);
  $('#nodeForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await api('/api/nodes', { method: 'POST', body: JSON.stringify({ ...Object.fromEntries(form.entries()), agentManaged: false }) });
      closeModal(); await refresh(); showToast('设备已加入共享池');
    } catch (error) { showToast(error.message); }
  });
}

$('#openTaskModal').addEventListener('click', openTaskModal);
$('#openNodeModal').addEventListener('click', openNodeModal);
$('#closeModal').addEventListener('click', closeModal);
$('#modalBackdrop').addEventListener('click', (event) => { if (event.target.id === 'modalBackdrop') closeModal(); });
$('#resetDemo').addEventListener('click', async () => { await api('/api/reset-demo', { method: 'POST' }); await refresh(); showToast('演示数据已重置'); });
$('#userButton').addEventListener('click', () => {
  const name = window.prompt('输入一个用户名称，可用于模拟多用户共享：', currentUser()?.name || '');
  if (!name?.trim()) return;
  api('/api/users', { method: 'POST', body: JSON.stringify({ name: name.trim() }) }).then((user) => {
    state.currentUserId = user.id; localStorage.setItem('gpu-share-user', user.id); refresh(); showToast(`已切换到 ${user.name}`);
  }).catch((error) => showToast(error.message));
});
$('#copyAgentCommand').addEventListener('click', async () => {
  const command = 'npm run agent -- --server http://localhost:4317 --owner Alice --name "我的共享节点"';
  await navigator.clipboard?.writeText(command);
  showToast('接入命令已复制');
});
$('#tasksList').addEventListener('click', async (event) => {
  const taskId = event.target.dataset.stop;
  if (!taskId) return;
  await api(`/api/tasks/${taskId}/stop`, { method: 'POST' }); await refresh(); showToast('任务已停止，资源已释放');
});

refresh();
setInterval(refresh, 2500);
