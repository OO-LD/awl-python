// The explainer, stepped through one beat at a time.
//
// Adapted from tutorial-player.js in OO-LD/oold-schema, which does the same job
// for the tutorial episodes. The video half is left out: this cut has stills and
// no render yet, so there is nothing to toggle between. What is kept is the part
// that was worked out there and is easy to get wrong.
//
// Beats come from assets/explainer/manifest.json, written by the docs build from
// the same list the renderer uses. If the manifest is missing the figures stay
// as a plain column, which reads fine, rather than leaving dead controls.
(function () {
  var MANIFEST = 'assets/explainer/manifest.json';

  // Asset URLs resolve against the site root, not the current page. The site is
  // additionally served under a version prefix once mike publishes it, so
  // neither a page-relative nor a root-absolute path works. The theme publishes
  // the way back in its config.
  function base() {
    var el = document.getElementById('__config');
    try {
      var b = JSON.parse(el.textContent).base;
      if (b) return b.replace(/\/+$/, '') + '/';
    } catch (e) { /* fall through */ }
    return '';
  }

  function setup(root, beats) {
    var img = root.querySelector('.awl-shot__slide');
    var scene = root.querySelector('.awl-shot__scene');
    var caption = root.querySelector('.awl-shot__caption');
    var prev = root.querySelector('.awl-shot__prev');
    var next = root.querySelector('.awl-shot__next');
    var i = 0;

    function apply() {
      i = (i + beats.length) % beats.length;
      var beat = beats[i];
      img.src = base() + 'assets/explainer/' + beat.name + '.png';
      img.alt = 'Beat ' + (i + 1) + ': ' + beat.name.replace(/^\d+-/, '').replace(/-/g, ' ');
      scene.textContent = beat.scene;
      caption.textContent = i + 1 + ' / ' + beats.length + '  ' + beat.time;
    }

    prev.addEventListener('click', function () { i -= 1; apply(); });
    next.addEventListener('click', function () { i += 1; apply(); });
    root.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowLeft') { i -= 1; apply(); }
      if (e.key === 'ArrowRight') { i += 1; apply(); }
    });
    root.classList.add('awl-shot--ready');
    apply();
  }

  function start() {
    var root = document.querySelector('.awl-shot');
    if (!root) return;
    // The dev server answers an unknown path with its 404 page at status 200,
    // so a wrong URL yields HTML rather than an error. Check the content type
    // and say so, instead of silently ending up with no beats.
    fetch(base() + MANIFEST)
      .then(function (r) {
        var ct = r.headers.get('content-type') || '';
        if (!r.ok || ct.indexOf('json') === -1) {
          throw new Error('manifest not JSON (' + r.status + ' ' + ct + ')');
        }
        return r.json();
      })
      .then(function (beats) {
        if (beats && beats.length) setup(root, beats);
      })
      .catch(function (err) {
        console.warn('explainer: ' + err.message + '; the stills stay a plain column');
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
