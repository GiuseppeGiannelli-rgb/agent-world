// The front-end of the sample target (spec 11 T09): list, add, tick, delete.
let todos = [];
let onlyOpen = false;

async function load() {
  const res = await fetch('/api/todos');
  todos = await res.json();
  render();
}

async function add(title) {
  const res = await fetch('/api/todos', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ title }) });
  if (res.ok) todos.push(await res.json());
  render();
}

async function toggle(todo) {
  const res = await fetch(`/api/todos/${todo.id}`, { method: 'PATCH', body: JSON.stringify({ done: !todo.done }) });
  Object.assign(todo, await res.json());
  render();
}

function render() {
  const shown = onlyOpen ? todos.filter((t) => !t.done) : todos;
  document.querySelector('#list').replaceChildren(...shown.map(item));
  document.querySelector('#empty').hidden = shown.length > 0;
}

function item(todo) {
  const li = document.createElement('li');
  li.textContent = todo.title;
  li.className = todo.done ? 'done' : '';
  li.onclick = () => toggle(todo);
  return li;
}

document.querySelector('#add').addEventListener('submit', (e) => {
  e.preventDefault();
  add(e.target.title.value);
  e.target.reset();
});
document.querySelector('#only-open').addEventListener('change', (e) => {
  onlyOpen = e.target.checked;
  render();
});
load();
