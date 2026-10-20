// The sample target of the demo (spec 11 T09): the Reverse Engineering team
// deconstructs it when a demo mission has no target of its own. Never run.
const express = require('express');

const app = express();
const PORT = 3000;
const MAX_TITLE = 120;
let nextId = 1;
const todos = [];

app.use(express.json());
app.use(express.static('public'));

function validTitle(title) {
  return typeof title === 'string' && title.trim().length > 0 && title.length <= MAX_TITLE;
}

function findTodo(id) {
  return todos.find((t) => t.id === Number(id));
}

app.get('/api/todos', listTodos);

function listTodos(req, res) {
  const open = req.query.done === 'false';
  res.json(open ? todos.filter((t) => !t.done) : todos);
}

app.post('/api/todos', (req, res) => {
  if (!validTitle(req.body.title)) return res.status(400).json({ error: 'title is required, at most 120 characters' });
  const todo = { id: nextId++, title: req.body.title.trim(), done: false, createdAt: new Date().toISOString() };
  todos.push(todo);
  res.status(201).json(todo);
});

app.patch('/api/todos/:id', (req, res) => {
  const todo = findTodo(req.params.id);
  if (!todo) return res.status(404).json({ error: 'not found' });
  if ('title' in req.body && !validTitle(req.body.title)) return res.status(400).json({ error: 'invalid title' });
  Object.assign(todo, { title: req.body.title ?? todo.title, done: Boolean(req.body.done ?? todo.done) });
  res.json(todo);
});

app.delete('/api/todos/:id', (req, res) => {
  const todo = findTodo(req.params.id);
  if (!todo) return res.status(404).json({ error: 'not found' });
  todos.splice(todos.indexOf(todo), 1);
  res.status(204).end();
});

module.exports = { app, validTitle };
