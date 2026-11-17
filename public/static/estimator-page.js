// Connects the calculator screens to the FastAPI server: calculation, saving, exports, guest drafts.
(function () {
  var cfg = window.ESTIMATOR;
  var DRAFT_KEY = 'material-estimator:guest-draft';
  var RESUME = '/estimate/new?resume=guest';
  // How numbers are written inside coverage text, like the browser's own toLocaleString().
  var locale = /-IN$/i.test(navigator.language || '') ? 'en-IN' : 'en-US';
  var toast = document.getElementById('toast');
  var calcFailed = false;

  function status(kind, text) {
    toast.className = 'notice ' + kind;
    toast.textContent = text + ' ';
    var close = document.createElement('button');
    close.className = 'link-danger'; close.type = 'button'; close.textContent = 'Dismiss';
    close.onclick = function () { toast.hidden = true; };
    toast.appendChild(close);
    toast.hidden = false;
  }

  function post(url, body) {
    return fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      .then(function (r) {
        if (r.ok) return r;
        return r.json().catch(function () { return {}; }).then(function (j) {
          throw new Error(typeof j.detail === 'string' ? j.detail : 'HTTP ' + r.status);
        });
      });
  }

  var draft = null;
  if (cfg.resumeGuest) { try { draft = JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null'); } catch (e) { draft = null; } }

  window.mountEstimator(document.getElementById('root'), {
    products: cfg.products,
    steps: cfg.steps,
    initial: draft || cfg.initial,
    saveLabel: cfg.guest ? 'Sign up to save' : cfg.estimateId ? 'Save changes' : undefined,
    exitLabel: cfg.guest ? '← Home' : undefined,
    onExit: function () { location.href = cfg.guest ? '/' : '/dashboard'; },
    calc: function (state) {
      var body = { state: state, locale: locale };
      if (cfg.savedCatalogue) body.catalogue = cfg.products; // a reopened estimate uses its saved values
      return post('/api/calc', body).then(function (r) { return r.json(); });
    },
    onCalcError: function (e) { calcFailed = true; status('err', 'Could not calculate: ' + e.message); },
    onCalcOk: function () { if (calcFailed) { calcFailed = false; toast.hidden = true; } },
    onSave: function (snapshot) {
      if (cfg.guest) {
        try { localStorage.setItem(DRAFT_KEY, JSON.stringify(snapshot)); }
        catch (e) { status('err', 'Your browser blocked saving the draft. Sign up, then build the estimate again.'); return; }
        location.href = '/signup?next=' + encodeURIComponent(RESUME);
        return;
      }
      status('ok', 'Saving…');
      post('/api/estimates', { id: cfg.estimateId, snapshot: snapshot, locale: locale })
        .then(function () {
          if (draft) { try { localStorage.removeItem(DRAFT_KEY); } catch (e) { /* ignore */ } }
          location.href = '/dashboard';
        })
        .catch(function (e) { status('err', 'Could not save: ' + e.message); });
    },
    onExport: function (kind, snapshot) {
      status('ok', 'Preparing ' + (kind === 'pdf' ? 'PDF' : 'Excel') + '…');
      post('/api/export/' + kind, { snapshot: snapshot, locale: locale, estimate_id: cfg.estimateId })
        .then(function (r) {
          var cd = r.headers.get('Content-Disposition') || '';
          var name = (cd.match(/filename="([^"]+)"/) || [])[1] || ('material-list.' + kind);
          return r.blob().then(function (b) {
            var url = URL.createObjectURL(b);
            var a = document.createElement('a'); a.href = url; a.download = name;
            document.body.appendChild(a); a.click(); a.remove();
            setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
            toast.hidden = true;
          });
        })
        .catch(function (e) { status('err', 'Export failed: ' + e.message); });
    },
  });
  if (draft) status('ok', 'Welcome back: your guest estimate is restored. Press Save estimate to keep it.');
})();
