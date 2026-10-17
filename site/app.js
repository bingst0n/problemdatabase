/* AMC 10 Problem Database — client. Loads site/data/index.json, parses the
   search box for a contest reference, filters in the browser, renders LaTeX
   with KaTeX. No build step. */
(function () {
  'use strict';

  const CATEGORY_LABELS = {
    algebra: 'Algebra', geometry: 'Geometry', number_theory: 'Number Theory',
    combinatorics: 'Combinatorics', probability: 'Probability', other: 'Other',
    uncategorized: 'Uncategorized',
  };
  const CATEGORY_ORDER = ['algebra', 'geometry', 'number_theory', 'combinatorics', 'probability', 'other', 'uncategorized'];
  const PAGE_SIZE = 50;
  const KATEX_OPTS = {
    throwOnError: false,
    strict: 'ignore',
    macros: {
      '\\overarc': '\\overset{\\frown}{#1}',
      '\\emph': '\\textit{#1}',
    },
  };

  const state = {
    problems: [], byId: new Map(), contests: [], solutions: new Map(),
    lastQuery: '', results: [], shown: 0,
  };
  const filters = {
    yearFrom: -Infinity, yearTo: Infinity, versions: new Set(['A', 'B']),
    numFrom: 1, numTo: 25, difficulties: new Set(), categories: new Set(),
  };

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  function h(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') node.className = v;
      else if (k === 'html') node.innerHTML = v;
      else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? '' : v);
    }
    for (const c of children.flat()) {
      if (c == null || c === false) continue;
      node.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return node;
  }

  function renderMath(root) {
    if (typeof katex === 'undefined') return;
    for (const node of $$('.tex, .tex-display', root)) {
      if (node.dataset.rendered) continue;
      const tex = node.textContent;
      node.dataset.rendered = '1';
      try {
        katex.render(tex, node, Object.assign({}, KATEX_OPTS, { displayMode: node.classList.contains('tex-display') }));
      } catch (e) {
        // throwOnError:false only covers parse errors; anything else falls back to the raw LaTeX.
        node.textContent = tex;
        node.classList.add('tex-error');
        node.title = e.message;
      }
    }
    for (const a of $$('a[href^="http"]', root)) {
      a.target = '_blank';
      a.rel = 'noopener';
    }
  }

  // ------------------------------------------------------------------ data

  async function loadIndex() {
    const r = await fetch('data/index.json', { cache: 'no-cache' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const idx = await r.json();
    state.contests = idx.contests || [];
    state.problems = idx.problems || [];
    for (const p of state.problems) {
      const cats = (p.categories && p.categories.length ? p.categories : ['uncategorized']);
      p._cats = cats;
      p._search = [
        p.title, p.statement_text || '', cats.map(c => CATEGORY_LABELS[c] || c).join(' '),
        p.difficulty_label || '',
      ].join(' ').toLowerCase().replace(/[’']/g, '');
      p._contestName = contestName(p);
      state.byId.set(p.id, p);
    }
    $('#generated').textContent = idx.generated_at ? 'Data generated ' + idx.generated_at.slice(0, 10) + '.' : '';
  }

  // Plain-text preview of a statement: drop LaTeX commands so snippets read naturally.
  function snippetText(t) {
    return (t || '')
      .replace(/\\([$%&#_{}])/g, '$1')
      .replace(/\^\{?\\circ\}?/g, '°')
      .replace(/\\(?:left|right|,|;|!|quad|qquad)/g, '')
      .replace(/\\[a-zA-Z]+\s*/g, '')
      .replace(/[{}$]/g, '')
      .replace(/\s+([.,;:?)])/g, '$1')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function contestName(p) {
    return p.year + (p.fall ? ' Fall' : '') + ' AMC 10' + p.version;
  }

  async function loadSolutions(contestId) {
    if (state.solutions.has(contestId)) return state.solutions.get(contestId);
    const r = await fetch('data/solutions/' + contestId + '.json', { cache: 'no-cache' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    state.solutions.set(contestId, data);
    return data;
  }

  // ------------------------------------------------------------------ query parsing

  function parseQuery(q) {
    let s = ' ' + q.toLowerCase().replace(/[’']/g, '') + ' ';
    const ref = { year: null, fall: null, version: null, number: null };

    s = s.replace(/\b(19\d{2}|20\d{2})\b/, (m) => { ref.year = +m; return ' '; });
    s = s.replace(/\bfall\b/, () => { ref.fall = true; return ' '; });
    s = s.replace(/\b(spring|winter)\b/, () => { ref.fall = false; return ' '; });
    s = s.replace(/\bamc\s*10\s*([ab])\b/, (m, v) => { ref.version = v.toUpperCase(); return ' '; });
    if (!ref.version) s = s.replace(/\b10\s*([ab])\b/, (m, v) => { ref.version = v.toUpperCase(); return ' '; });
    s = s.replace(/\bamc\s*10\b/, ' ').replace(/\bamc\b/, ' ');
    s = s.replace(/(?:#|\bnumber|\bnum|\bproblem|\bprob|\bno\.?|\bp|\bq)\s*(\d{1,2})\b/, (m, n) => {
      ref.number = +n; return ' ';
    });
    if (ref.number == null && (ref.year != null || ref.version)) {
      s = s.replace(/\b(\d{1,2})\b/, (m, n) => {
        if (+n >= 1 && +n <= 25) { ref.number = +n; return ' '; }
        return m;
      });
    }
    if (!ref.version && ref.year != null) {
      s = s.replace(/\b([ab])\b/, (m, v) => { ref.version = v.toUpperCase(); return ' '; });
    }
    const terms = s.split(/[^a-z0-9]+/).filter(t => t.length >= 2);
    return { ref, terms };
  }

  function matches(p, parsed) {
    const { ref, terms } = parsed;
    if (ref.year != null && p.year !== ref.year) return false;
    if (ref.fall != null && p.fall !== ref.fall) return false;
    if (ref.version && p.version !== ref.version) return false;
    if (ref.number != null && p.number !== ref.number) return false;
    if (!filters.versions.has(p.version)) return false;
    if (p.year < filters.yearFrom || p.year > filters.yearTo) return false;
    if (p.number < filters.numFrom || p.number > filters.numTo) return false;
    if (filters.difficulties.size && !filters.difficulties.has(String(p.difficulty))) return false;
    if (filters.categories.size && !p._cats.some(c => filters.categories.has(c))) return false;
    for (const t of terms) if (!p._search.includes(t)) return false;
    return true;
  }

  function sortResults(a, b) {
    return b.year - a.year || (b.fall - a.fall) || a.version.localeCompare(b.version) || a.number - b.number;
  }

  function computeResults(q) {
    const parsed = parseQuery(q);
    const results = state.problems.filter(p => matches(p, parsed)).sort(sortResults);
    return { parsed, results };
  }

  // ------------------------------------------------------------------ filters UI

  function buildFilters() {
    const years = Array.from(new Set(state.contests.map(c => c.year))).sort((a, b) => a - b);
    const from = $('#year-from'), to = $('#year-to');
    for (const y of years) {
      from.append(h('option', { value: y }, y));
      to.append(h('option', { value: y }, y));
    }
    if (years.length) {
      from.value = years[0]; to.value = years[years.length - 1];
      filters.yearFrom = years[0]; filters.yearTo = years[years.length - 1];
    }

    const diffs = Array.from(new Set(state.problems.map(p => p.difficulty).filter(d => d != null))).sort((a, b) => a - b);
    const diffBox = $('#difficulty-filter');
    for (const d of diffs) {
      const label = (state.problems.find(p => p.difficulty === d) || {}).difficulty_label;
      diffBox.append(h('label', {}, h('input', { type: 'checkbox', 'data-filter': 'difficulty', value: String(d) }), ' ' + d + (label ? ' · ' + label : '')));
    }

    const present = new Set(state.problems.flatMap(p => p._cats));
    const catBox = $('#category-filter');
    for (const c of CATEGORY_ORDER) {
      if (!present.has(c)) continue;
      catBox.append(h('label', {}, h('input', { type: 'checkbox', 'data-filter': 'category', value: c }), ' ' + CATEGORY_LABELS[c]));
    }

    $('#filters').addEventListener('change', readFilters);
    $('#reset-filters').addEventListener('click', () => {
      for (const cb of $$('#filters input[type=checkbox]')) cb.checked = cb.dataset.filter === 'version';
      if (years.length) { from.value = years[0]; to.value = years[years.length - 1]; }
      $('#num-from').value = 1; $('#num-to').value = 25;
      readFilters();
    });
    $('#toggle-filters').addEventListener('click', (e) => {
      const panel = $('#filters');
      panel.hidden = !panel.hidden;
      e.currentTarget.setAttribute('aria-expanded', String(!panel.hidden));
    });
  }

  function readFilters() {
    const yf = +$('#year-from').value, yt = +$('#year-to').value;
    filters.yearFrom = Math.min(yf, yt); filters.yearTo = Math.max(yf, yt);
    const nf = +$('#num-from').value || 1, nt = +$('#num-to').value || 25;
    filters.numFrom = Math.min(nf, nt); filters.numTo = Math.max(nf, nt);
    filters.versions = new Set($$('input[data-filter=version]:checked').map(i => i.value));
    filters.difficulties = new Set($$('input[data-filter=difficulty]:checked').map(i => i.value));
    filters.categories = new Set($$('input[data-filter=category]:checked').map(i => i.value));
    updateFilterBadge();
    if ($('#problem').hidden) renderResults(state.lastQuery);
  }

  function updateFilterBadge() {
    const yearsAll = state.contests.length === 0 ||
      (filters.yearFrom <= Math.min(...state.contests.map(c => c.year)) && filters.yearTo >= Math.max(...state.contests.map(c => c.year)));
    const active = !yearsAll || filters.versions.size !== 2 || filters.numFrom !== 1 || filters.numTo !== 25 ||
      filters.difficulties.size || filters.categories.size;
    $('#toggle-filters').textContent = active ? 'Filters •' : 'Filters';
  }

  // ------------------------------------------------------------------ views

  function show(view) {
    $('#status').hidden = view !== 'status';
    $('#results').hidden = view !== 'results';
    $('#problem').hidden = view !== 'problem';
  }

  function tagNodes(p) {
    const tags = [];
    if (p.difficulty != null) tags.push(h('span', { class: 'tag diff' }, (p.difficulty_label ? p.difficulty_label + ' · ' : '') + p.difficulty));
    const guessed = p.category_source === 'guessed';
    for (const c of p._cats) {
      tags.push(h('span', { class: guessed ? 'tag guess' : 'tag', title: guessed ? 'Guessed from the statement; the wiki has no category for this problem' : null },
        (CATEGORY_LABELS[c] || c) + (guessed ? '?' : '')));
    }
    return tags;
  }

  function renderResults(q) {
    state.lastQuery = q;
    const { results } = computeResults(q);
    state.results = results;
    state.shown = 0;
    const box = $('#results');
    box.replaceChildren();
    const head = h('div', { class: 'results-head' },
      h('span', {}, results.length === 0 ? 'No problems match.' : results.length + (results.length === 1 ? ' problem' : ' problems')),
      q ? h('span', {}, 'for “' + q + '”') : null);
    box.append(head);
    appendMoreResults();
    show('results');
  }

  function appendMoreResults() {
    const box = $('#results');
    const old = $('.more', box);
    if (old) old.remove();
    const slice = state.results.slice(state.shown, state.shown + PAGE_SIZE);
    for (const p of slice) {
      box.append(h('a', { class: 'result', href: '#/problem/' + p.id },
        h('div', { class: 'result-title' }, p._contestName + ' · Problem ' + p.number),
        h('div', { class: 'snippet' }, snippetText(p.statement_text).slice(0, 260)),
        h('div', { class: 'tags' }, tagNodes(p))));
    }
    state.shown += slice.length;
    if (state.shown < state.results.length) {
      box.append(h('button', { class: 'more ghost', onclick: appendMoreResults },
        'Show more (' + (state.results.length - state.shown) + ' remaining)'));
    }
  }

  function renderProblem(id) {
    const p = state.byId.get(id);
    const art = $('#problem');
    art.replaceChildren();
    if (!p) {
      art.append(h('p', { class: 'status' }, 'No problem with id ', h('code', {}, id), '. ', h('a', { href: '#/' }, 'Back to all problems')));
      document.title = 'AMC 10 Problem Database';
      show('problem');
      return;
    }
    const siblings = state.problems.filter(x => x.contest_id === p.contest_id).sort((a, b) => a.number - b.number);
    const prev = siblings.filter(x => x.number < p.number).pop();   // nearest, so a missing page does not break the chain
    const next = siblings.find(x => x.number > p.number);

    const back = state.lastQuery ? '#/search/' + encodeURIComponent(state.lastQuery) : '#/';
    art.append(h('nav', { class: 'crumbs' }, h('a', { href: back }, '← Back to results')));

    art.append(h('header', { class: 'problem-head' },
      h('h1', {}, p._contestName + ' ', h('span', {}, '· Problem ' + p.number)),
      h('div', { class: 'tags' }, tagNodes(p)),
      h('a', { class: 'source', href: p.url, target: '_blank', rel: 'noopener' }, 'View on AoPS ↗')));

    const statement = h('section', { class: 'card statement', html: p.statement_html || '<p><em>No statement was extracted for this problem.</em></p>' });
    art.append(statement);

    const choices = h('section', { class: 'card choices' });
    let list = null;
    if (p.choices && p.choices.length) {
      list = h('ol', {}, p.choices.map(c => h('li', { 'data-label': c.label },
        h('span', { class: 'choice-label' }, '(' + c.label + ')'),
        h('span', { class: 'tex' }, c.tex))));
      choices.append(list);
    } else if (p.choices_tex) {
      choices.append(h('div', { class: 'tex-display' }, p.choices_tex));
      choices.append(h('p', { class: 'unparsed' }, 'The choices could not be split automatically; shown as one line.'));
    } else {
      choices.append(h('p', { class: 'unparsed' }, 'No answer choices were found on the wiki page.'));
    }
    const answerText = h('span', { class: 'answer-text' });
    const checkbox = h('input', { type: 'checkbox', id: 'show-answer' });
    checkbox.addEventListener('change', () => {
      const on = checkbox.checked;
      if (list) for (const li of $$('li', list)) li.classList.toggle('correct', on && li.dataset.label === p.answer);
      answerText.textContent = !on ? '' : (p.answer ? 'Answer: (' + p.answer + ')' : 'Answer not available');
    });
    choices.append(h('div', { class: 'answer-row' }, h('label', {}, checkbox, ' Show answer'), answerText));
    art.append(choices);

    const solBox = h('div', { class: 'solution-list', hidden: true });
    const count = p.solution_count || 0;
    const solBtn = h('button', { class: 'ghost', type: 'button' }, count ? 'Show solutions (' + count + ')' : 'Show solutions');
    let loaded = false;
    solBtn.addEventListener('click', async () => {
      if (!loaded) {
        solBtn.disabled = true;
        solBox.replaceChildren();
        try {
          const data = await loadSolutions(p.contest_id);
          const sols = data[p.id] || [];
          if (!sols.length) solBox.append(h('p', { class: 'unparsed' }, 'No solutions were extracted for this problem.'));
          for (const s of sols) {
            solBox.append(h('section', { class: 'solution' }, h('h3', {}, s.heading), h('div', { html: s.html })));
          }
          renderMath(solBox);
          loaded = true;
        } catch (e) {
          solBox.append(h('p', { class: 'unparsed' }, 'Could not load solutions (' + e.message + '). Click the button to retry.'));
        }
        solBtn.disabled = false;
        solBox.hidden = false;
      } else {
        solBox.hidden = !solBox.hidden;
      }
      solBtn.textContent = (solBox.hidden ? 'Show' : 'Hide') + ' solutions' + (count ? ' (' + count + ')' : '');
    });
    art.append(h('section', { class: 'card solutions' },
      h('div', { class: 'solutions-head' }, h('h2', { style: 'margin:0;font-size:1.05rem' }, 'Solutions'), solBtn), solBox));

    art.append(h('nav', { class: 'pager' },
      prev ? h('a', { href: '#/problem/' + prev.id }, '← Problem ' + prev.number) : h('span'),
      next ? h('a', { href: '#/problem/' + next.id }, 'Problem ' + next.number + ' →') : h('span')));

    renderMath(art);
    show('problem');
    window.scrollTo(0, 0);
    document.title = p._contestName + ' Problem ' + p.number + ' · AMC 10 Problem Database';
  }

  function showNoData(err) {
    const s = $('#status');
    s.className = 'status error';
    s.replaceChildren(
      h('p', {}, h('strong', {}, 'No problem data yet.'), ' ', h('code', {}, 'site/data/index.json'), ' could not be loaded (' + err.message + ').'),
      h('p', {}, 'Run the scraper, then reload this page:'),
      h('pre', {}, 'pip install -r scraper/requirements.txt\npython3 scraper/scrape.py'),
      h('p', {}, 'Serve the site over HTTP (not file://), e.g. ', h('code', {}, 'python3 -m http.server 8000 --directory site'), '.'));
    show('status');
  }

  // ------------------------------------------------------------------ routing

  function route() {
    let hash = location.hash || '';
    if (hash && !hash.startsWith('#/')) return;  // an in-content anchor, not a route: leave the view alone
    try {
      hash = decodeURIComponent(hash);
    } catch (e) {
      hash = '';  // malformed percent-escape: fall back to the full list rather than a blank page
    }
    let m;
    if ((m = hash.match(/^#\/problem\/(.+)$/))) {
      renderProblem(m[1]);
      return;
    }
    if ((m = hash.match(/^#\/search\/(.*)$/))) {
      $('#q').value = m[1];
      document.title = 'AMC 10 Problem Database';
      renderResults(m[1]);
      return;
    }
    $('#q').value = '';
    document.title = 'AMC 10 Problem Database';
    renderResults('');
  }

  function navigate(hash) {
    if (location.hash === hash) route();
    else location.hash = hash;
  }

  function onSubmit(e) {
    e.preventDefault();
    const q = $('#q').value.trim();
    const { parsed, results } = computeResults(q);
    if (results.length === 1 && parsed.ref.number != null) {
      state.lastQuery = q;
      navigate('#/problem/' + results[0].id);
    } else {
      navigate('#/search/' + encodeURIComponent(q));
    }
  }

  async function init() {
    $('#search-form').addEventListener('submit', onSubmit);
    document.addEventListener('keydown', (e) => {
      if (e.key === '/' && document.activeElement !== $('#q') && !/input|textarea|select/i.test(document.activeElement.tagName)) {
        e.preventDefault(); $('#q').focus();
      }
    });
    try {
      await loadIndex();
    } catch (err) {
      showNoData(err);
      return;
    }
    buildFilters();
    updateFilterBadge();
    window.addEventListener('hashchange', route);
    route();
  }

  init();
})();
