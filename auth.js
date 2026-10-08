// Вход/регистрация. Локальное демо: аккаунты хранятся в ЭТОМ браузере.
// Без сервера сделать общий вход для всех нельзя - честно предупреждаем в коде.
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var mode = 'login';

  // счетчик визитов для админки
  try {
    localStorage.setItem('sb_visits', String((parseInt(localStorage.getItem('sb_visits') || '0', 10) || 0) + 1));
  } catch (e) {}

  // ВНИМАНИЕ (демо-режим по просьбе владельца): пароли хранятся ОТКРЫТЫМ
  // текстом и видны в админке/базе. Так делать нельзя на настоящих сайтах -
  // при взломе или XSS все пароли сразу чужие. Здесь - только локальное демо.
  function users() {
    try { return JSON.parse(localStorage.getItem('sb_users') || '{}'); }
    catch (e) { return {}; }
  }
  function saveUsers(u) {
    localStorage.setItem('sb_users', JSON.stringify(u));
  }
  function refresh() {
    var name = null;
    try { name = localStorage.getItem('sb_session'); } catch (e) {}
    if (name) {
      $('authBtn').hidden = true;
      $('userChip').hidden = false;
      $('userName').textContent = name;
    } else {
      $('authBtn').hidden = false;
      $('userChip').hidden = true;
    }
  }
  function setTab(t) {
    mode = t;
    var tabs = document.querySelectorAll('.auth-tabs button');
    tabs.forEach(function (b) { b.classList.toggle('active', b.dataset.t === t); });
    $('authGo').textContent = t === 'login' ? 'Войти' : 'Создать аккаунт';
    $('authErr').textContent = '';
  }

  $('authBtn').addEventListener('click', function () {
    $('authModal').hidden = false;
    setTab('login');
  });
  $('authClose').addEventListener('click', function () {
    $('authModal').hidden = true;
  });
  $('authModal').addEventListener('click', function (e) {
    if (e.target === $('authModal')) $('authModal').hidden = true;
  });
  document.querySelectorAll('.auth-tabs button').forEach(function (b) {
    b.addEventListener('click', function () { setTab(b.dataset.t); });
  });
  $('authGo').addEventListener('click', function () {
    var name = $('authName').value.trim();
    var pass = $('authPass').value;
    if (name.length < 2) { $('authErr').textContent = 'Имя - минимум 2 буквы'; return; }
    if (pass.length < 4) { $('authErr').textContent = 'Пароль - минимум 4 символа'; return; }
    var db = users();
    if (mode === 'reg') {
      if (db[name]) { $('authErr').textContent = 'Такое имя уже занято'; return; }
      db[name] = { pass: pass };
      saveUsers(db);
      try { localStorage.setItem('sb_session', name); } catch (e) {}
      $('authModal').hidden = true;
      $('authPass').value = '';
      refresh();
    } else {
      if (!db[name]) { $('authErr').textContent = 'Нет такого аккаунта - зарегистрируйся'; return; }
      if (!db[name].pass) { $('authErr').textContent = 'Аккаунт старого формата - зарегистрируйся заново'; return; }
      if (pass !== db[name].pass) { $('authErr').textContent = 'Неверный пароль'; return; }
      try { localStorage.setItem('sb_session', name); } catch (e) {}
      $('authModal').hidden = true;
      $('authPass').value = '';
      refresh();
    }
  });
  $('authPass').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') $('authGo').click();
  });
  $('logoutBtn').addEventListener('click', function () {
    try { localStorage.removeItem('sb_session'); } catch (e) {}
    refresh();
  });

  refresh();
})();
