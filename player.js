// Мини-плеер. Нужен music/playlist.js (const PLAYLIST = [...]) выше этого скрипта.
(function () {
  var audio = new Audio();
  audio.preload = 'auto';
  audio.volume = 0.3;

  var idx = 0;
  var playing = false;

  function $(id) { return document.getElementById(id); }
  function trackFile(i) { return PLAYLIST[i]; }
  function title(i) {
    var f = trackFile(i).split('/').pop();
    return decodeURIComponent(f).replace(/\.(mp3|flac|ogg|m4a|wav)$/i, '');
  }
  function trackUrl(i) {
    var f = trackFile(i);
    return (/^https?:\/\//i.test(f)) ? f : 'music/' + encodeURIComponent(f);
  }
  function fmt(s) {
    s = Math.max(0, Math.floor(s || 0));
    return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
  }
  function setPlaying(v) {
    playing = v;
    $('plPlay').textContent = v ? '⏸' : '▶';
    $('player').classList.toggle('playing', v);
    try { sessionStorage.setItem('pl_on', v ? '1' : '0'); } catch (e) {}
  }
  function tryPlay() {
    var p = audio.play();
    if (p && p.then) {
      p.then(function () { setPlaying(true); }).catch(function () { waitGesture(); });
    } else {
      setPlaying(true);
    }
  }
  function waitGesture() {
    var kick = function () {
      audio.play().then(function () { setPlaying(true); }).catch(function () {});
      document.removeEventListener('pointerdown', kick);
      document.removeEventListener('keydown', kick);
    };
    document.addEventListener('pointerdown', kick);
    document.addEventListener('keydown', kick);
  }
  function load(i, autoplay) {
    idx = ((i % PLAYLIST.length) + PLAYLIST.length) % PLAYLIST.length;
    audio.src = trackUrl(idx);
    $('plTitle').textContent = title(idx);
    $('plSeek').value = 0;
    $('plDur').textContent = '0:00';
    setPlaying(false);
    if (autoplay) tryPlay();
  }

  // всегда начинаем заново: первый трек с начала
  try {
    sessionStorage.removeItem('pl_i');
    sessionStorage.removeItem('pl_t');
  } catch (e) {}
  idx = 0;
  function save() {
    try {
      sessionStorage.setItem('pl_i', idx);
      sessionStorage.setItem('pl_t', audio.currentTime);
    } catch (e) {}
  }
  audio.src = trackUrl(idx);
  $('plTitle').textContent = title(idx);
  $('plVol').value = 30;
  // при каждом входе/переходе играем заново с первого трека
  tryPlay();

  $('plPlay').addEventListener('click', function (e) {
    e.stopPropagation();
    if (playing) { audio.pause(); setPlaying(false); }
    else tryPlay();
  });
  $('plPrev').addEventListener('click', function (e) {
    e.stopPropagation(); load(idx - 1, true);
  });
  $('plNext').addEventListener('click', function (e) {
    e.stopPropagation(); load(idx + 1, true);
  });
  audio.addEventListener('ended', function () { load(idx + 1, true); });
  audio.addEventListener('loadedmetadata', function () {
    $('plDur').textContent = fmt(audio.duration);
  });
  audio.addEventListener('timeupdate', function () {
    if (!seeking && audio.duration) $('plSeek').value = Math.floor(audio.currentTime / audio.duration * 1000);
    $('plCur').textContent = fmt(audio.currentTime);
    if (playing) save();
  });
  // пока тянешь ползунок - обновления времени его не отбивают назад
  var seeking = false;
  $('plSeek').addEventListener('pointerdown', function () { seeking = true; });
  window.addEventListener('pointerup', function () { seeking = false; });
  $('plSeek').addEventListener('input', function (e) {
    if (audio.duration) audio.currentTime = (e.target.value / 1000) * audio.duration;
  });
  $('plVol').addEventListener('input', function (e) {
    audio.volume = e.target.value / 100;
  });
  window.addEventListener('pagehide', save);
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') save();
  });
  window.addEventListener('beforeunload', save);
})();
