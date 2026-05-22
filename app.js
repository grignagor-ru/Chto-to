const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
}

let apiUrl = window.API_URL || localStorage.getItem('ff_api_url') || '';

const state = {
  todos: [],
  timer: {
    workMinutes: Number(localStorage.getItem('ff_work_minutes')) || 25,
    breakMinutes: Number(localStorage.getItem('ff_break_minutes')) || 5,
    mode: localStorage.getItem('ff_mode') || 'work',
    secondsLeft: Number(localStorage.getItem('ff_seconds_left')) || 25 * 60,
    running: false,
  },
  focusCount: Number(localStorage.getItem('ff_focus_count')) || 0,
  history: JSON.parse(localStorage.getItem('ff_history') || '[]'),
};

let intervalId = null;

const el = {
  todoInput: document.getElementById('todo-input'),
  addTodoBtn: document.getElementById('add-todo-btn'),
  todoList: document.getElementById('todo-list'),
  doneCount: document.getElementById('done-count'),
  timerLabel: document.getElementById('timer-label'),
  timerValue: document.getElementById('timer-value'),
  focusCount: document.getElementById('focus-count'),
  startBtn: document.getElementById('start-btn'),
  pauseBtn: document.getElementById('pause-btn'),
  resetBtn: document.getElementById('reset-btn'),
  workInput: document.getElementById('work-minutes'),
  breakInput: document.getElementById('break-minutes'),
  weekFocus: document.getElementById('week-focus'),
  weekDone: document.getElementById('week-done'),
  reminderAt: document.getElementById('reminder-at'),
  reminderText: document.getElementById('reminder-text'),
  setReminderBtn: document.getElementById('set-reminder-btn'),
  apiUrlInput: document.getElementById('api-url'),
  saveApiBtn: document.getElementById('save-api-btn'),
};

function getUserId() {
  return tg?.initDataUnsafe?.user?.id || 'guest';
}

async function api(path, method = 'GET', data) {
  if (!apiUrl) return null;
  try {
    const res = await fetch(`${apiUrl}${path}`, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: data ? JSON.stringify(data) : undefined,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (e) {
    console.warn('API unavailable:', e.message);
    return null;
  }
}

function saveLocalState() {
  localStorage.setItem('ff_todos', JSON.stringify(state.todos));
  localStorage.setItem('ff_work_minutes', String(state.timer.workMinutes));
  localStorage.setItem('ff_break_minutes', String(state.timer.breakMinutes));
  localStorage.setItem('ff_mode', state.timer.mode);
  localStorage.setItem('ff_seconds_left', String(state.timer.secondsLeft));
  localStorage.setItem('ff_focus_count', String(state.focusCount));
  localStorage.setItem('ff_history', JSON.stringify(state.history.slice(-200)));
}

async function syncStateRemote() {
  await api('/state', 'POST', {
    user_id: String(getUserId()),
    todos: state.todos,
    focus_count: state.focusCount,
    history: state.history.slice(-200),
    timer: state.timer,
  });
}

function loadLocalState() {
  const todos = localStorage.getItem('ff_todos');
  if (todos) state.todos = JSON.parse(todos);
}

async function loadRemoteState() {
  const remote = await api(`/state/${getUserId()}`);
  if (!remote) return;
  if (Array.isArray(remote.todos)) state.todos = remote.todos;
  if (typeof remote.focus_count === 'number') state.focusCount = remote.focus_count;
  if (Array.isArray(remote.history)) state.history = remote.history;
  if (remote.timer) state.timer = { ...state.timer, ...remote.timer, running: false };
}

function formatTime(totalSeconds) {
  const m = String(Math.floor(totalSeconds / 60)).padStart(2, '0');
  const s = String(totalSeconds % 60).padStart(2, '0');
  return `${m}:${s}`;
}

function getWeekStats() {
  const weekAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;
  const weekItems = state.history.filter((h) => new Date(h.at).getTime() >= weekAgo);
  const weekFocus = weekItems.filter((h) => h.type === 'focus').length;
  const weekDone = weekItems.filter((h) => h.type === 'todo_done').length;
  return { weekFocus, weekDone };
}

function renderTodos() {
  el.todoList.innerHTML = '';
  state.todos.forEach((todo) => {
    const li = document.createElement('li');
    li.className = `todo-item ${todo.done ? 'done' : ''}`;

    const text = document.createElement('span');
    text.textContent = todo.text;
    text.onclick = async () => {
      todo.done = !todo.done;
      if (todo.done) state.history.push({ type: 'todo_done', at: new Date().toISOString(), text: todo.text });
      persistAndRender();
      await syncStateRemote();
    };

    const del = document.createElement('button');
    del.textContent = '✕';
    del.className = 'danger';
    del.onclick = async () => {
      state.todos = state.todos.filter((t) => t.id !== todo.id);
      persistAndRender();
      await syncStateRemote();
    };

    li.append(text, del);
    el.todoList.appendChild(li);
  });
}

function renderTimer() {
  el.timerLabel.textContent = state.timer.mode === 'work' ? 'Фокус' : 'Перерыв';
  el.timerValue.textContent = formatTime(state.timer.secondsLeft);
  el.workInput.value = state.timer.workMinutes;
  el.breakInput.value = state.timer.breakMinutes;
  el.focusCount.textContent = state.focusCount;

  const { weekFocus, weekDone } = getWeekStats();
  el.weekFocus.textContent = weekFocus;
  el.weekDone.textContent = weekDone;
}

function persistAndRender() {
  saveLocalState();
  renderTodos();
  renderTimer();
  el.doneCount.textContent = state.todos.filter((t) => t.done).length;
}

function switchMode() {
  state.timer.mode = state.timer.mode === 'work' ? 'break' : 'work';
  state.timer.secondsLeft = (state.timer.mode === 'work' ? state.timer.workMinutes : state.timer.breakMinutes) * 60;
}

function tick() {
  if (!state.timer.running) return;
  if (state.timer.secondsLeft > 0) {
    state.timer.secondsLeft -= 1;
    persistAndRender();
    return;
  }

  if (state.timer.mode === 'work') {
    state.focusCount += 1;
    state.history.push({ type: 'focus', at: new Date().toISOString() });
  }

  switchMode();
  persistAndRender();
  syncStateRemote();
}

function startTimer() {
  if (state.timer.running) return;
  state.timer.running = true;
  intervalId = setInterval(tick, 1000);
}

function pauseTimer() {
  state.timer.running = false;
  if (intervalId) clearInterval(intervalId);
}

function resetTimer() {
  pauseTimer();
  state.timer.mode = 'work';
  state.timer.secondsLeft = state.timer.workMinutes * 60;
  persistAndRender();
}

async function setReminder() {
  const at = el.reminderAt.value;
  const text = el.reminderText.value.trim();
  if (!at || !text) return;
  await api('/reminder', 'POST', {
    user_id: String(getUserId()),
    remind_at: new Date(at).toISOString(),
    text,
  });
  alert('Напоминание отправлено на сервер. Бот пришлёт сообщение в нужное время.');
  el.reminderText.value = '';
}

function bindEvents() {
  el.addTodoBtn.onclick = async () => {
    const text = el.todoInput.value.trim();
    if (!text) return;
    state.todos.push({ id: crypto.randomUUID(), text, done: false });
    el.todoInput.value = '';
    persistAndRender();
    await syncStateRemote();
  };

  el.startBtn.onclick = startTimer;
  el.pauseBtn.onclick = pauseTimer;
  el.resetBtn.onclick = resetTimer;

  el.workInput.onchange = () => {
    state.timer.workMinutes = Math.max(1, Number(el.workInput.value) || 25);
    if (state.timer.mode === 'work') state.timer.secondsLeft = state.timer.workMinutes * 60;
    persistAndRender();
    syncStateRemote();
  };

  el.breakInput.onchange = () => {
    state.timer.breakMinutes = Math.max(1, Number(el.breakInput.value) || 5);
    if (state.timer.mode === 'break') state.timer.secondsLeft = state.timer.breakMinutes * 60;
    persistAndRender();
    syncStateRemote();
  };

  el.setReminderBtn.onclick = setReminder;

  el.saveApiBtn.onclick = () => {
    apiUrl = el.apiUrlInput.value.trim();
    localStorage.setItem('ff_api_url', apiUrl);
    alert('Сохранено. API URL применён сразу.');
  };
}

(async function init() {
  loadLocalState();
  el.apiUrlInput.value = apiUrl;
  await loadRemoteState();
  bindEvents();
  persistAndRender();
})();
