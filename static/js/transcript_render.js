/**
 * TRANSCRIPT RENDERER — the single markdown/[[BUTTONS:]] renderer.
 *
 * Replaces two copy-paste siblings that had silently drifted apart:
 *   - _renderMarkdownForExport() in chat.js  (PDF export)
 *   - an inline <script> in shared_conversation.html  (public share page)
 *
 * The drift mattered:
 *   - the share page had no header or ordered-list support, so those rendered
 *     as raw markdown there but correctly in the PDF
 *   - the share page only accepted "-" bullets, not "*"
 *   - and, worst, the share page never stripped [[LEAD:...]], so captured
 *     lead data could be published on a public URL
 *
 * This module is the superset of both, and ALWAYS strips internal tags.
 *
 * Usage:
 *   BubblTranscript.render(text, { links: 'anchor' | 'text' })
 *   BubblTranscript.collectLinks(text)   -> [{label, url}]  (for a References list)
 */
(function (root) {
  'use strict';

  var ACCENT = '#E8722A';

  // Internal control tags that must never reach a rendered transcript.
  var LEAD_TAG = /\[\[LEAD:.*?\]\]/gs;
  var FORM_TAG = /\[SHOW_FORM\]/g;
  var BUTTONS_TAG = /\[\[BUTTONS:\s*(.*?)\]\]/gs;
  // one button: "kind:Label|https://url|#hexcolor"  (colour optional)
  var BUTTON_RE = /^(\w+):(.+?)\|([^|]+?)(?:\|(#[0-9a-fA-F]{3,8}))?$/;

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  /** Strip the control tags that should never be shown to anyone. */
  function stripInternalTags(text) {
    return String(text == null ? '' : text)
      .replace(LEAD_TAG, '')
      .replace(FORM_TAG, '')
      .trim();
  }

  /** Pull the button links out of a message, for a References section. */
  function collectLinks(text) {
    var out = [];
    var src = String(text == null ? '' : text);
    var m = src.match(BUTTONS_TAG);
    if (!m) return out;
    // BUTTONS_TAG is global; re-run with exec to get the capture group
    var re = new RegExp(BUTTONS_TAG.source, 'gs');
    var hit;
    while ((hit = re.exec(src)) !== null) {
      hit[1].split(/,\s*(?=[a-z]+:)/).forEach(function (part) {
        var b = part.trim().match(BUTTON_RE);
        if (b) out.push({ label: b[2].trim(), url: b[3].trim() });
      });
    }
    return out;
  }

  function renderTable(tableBlock) {
    var rows = tableBlock.trim().split('\n').filter(function (r) { return r.trim(); });
    if (rows.length < 2) return tableBlock;

    var html = '<table class="t-table">';
    var headerDone = false;
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i].trim();
      // separator row: |---|:--:|
      if (/^\|[\s\-:]+\|$/.test(row) || /^\|(\s*[-:]+\s*\|)+$/.test(row)) {
        headerDone = true;
        continue;
      }
      var cells = row.split('|').filter(function (c, idx, arr) {
        return idx > 0 && idx < arr.length - 1;
      });
      var tag = (!headerDone && i === 0) ? 'th' : 'td';
      html += '<tr>';
      for (var j = 0; j < cells.length; j++) {
        var cell = cells[j].trim().replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        html += '<' + tag + '>' + cell + '</' + tag + '>';
      }
      html += '</tr>';
      if (tag === 'th') headerDone = true;
    }
    return html + '</table>';
  }

  function renderButtons(raw, mode) {
    var parts = raw.split(/,\s*(?=[a-z]+:)/);
    var items = [];
    parts.forEach(function (part) {
      var b = part.trim().match(BUTTON_RE);
      if (b) items.push({ label: b[2].trim(), url: b[3].trim(), color: b[4] });
    });
    if (!items.length) return '';

    if (mode === 'text') {
      // Print/PDF: a URL is useless as a click target on paper, so show it.
      var t = '<div class="t-links">';
      items.forEach(function (it) {
        t += '<div class="t-link-row"><span class="t-link-label">' + escapeHtml(it.label) +
             '</span><span class="t-link-dash"> — </span>' +
             '<span class="t-link-url">' + escapeHtml(it.url) + '</span></div>';
      });
      return t + '</div>';
    }

    // Share page: real clickable pills.
    var a = '<div class="t-btn-row">';
    items.forEach(function (it) {
      var bg = it.color ? ' style="background:' + escapeHtml(it.color) + ';"' : '';
      a += '<a class="t-btn" href="' + escapeHtml(it.url) + '" target="_blank" rel="noopener nofollow"' +
           bg + '>' + escapeHtml(it.label) + ' &#8599;</a>';
    });
    return a + '</div>';
  }

  /**
   * Render one message body to HTML.
   * opts.links: 'anchor' (default) for clickable pills, 'text' for print.
   */
  function render(text, opts) {
    opts = opts || {};
    var mode = opts.links === 'text' ? 'text' : 'anchor';

    var html = escapeHtml(stripInternalTags(text));

    // fenced code first, so its contents are not treated as markdown
    html = html.replace(/```([\s\S]*?)```/g, function (m, code) {
      return '<pre class="t-pre">' + code.trim() + '</pre>';
    });
    html = html.replace(/`([^`]+)`/g, '<code class="t-code">$1</code>');

    html = html.replace(/((?:^|\n)\|.+\|(?:\n\|.+\|)+)/g, renderTable);

    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');

    // headers — longest marker first so #### doesn't match #
    html = html.replace(/^####\s+(.+)$/gm, '<h4 class="t-h">$1</h4>');
    html = html.replace(/^###\s+(.+)$/gm, '<h3 class="t-h">$1</h3>');
    html = html.replace(/^##\s+(.+)$/gm, '<h2 class="t-h">$1</h2>');
    html = html.replace(/^#\s+(.+)$/gm, '<h1 class="t-h">$1</h1>');

    // unordered list — accepts both - and * bullets
    html = html.replace(/((?:^|\n)[\-\*]\s.+)+/g, function (block) {
      var out = '<ul class="t-ul">';
      block.trim().split('\n').forEach(function (line) {
        var item = line.replace(/^[\-\*]\s+/, '').trim();
        if (item) out += '<li>' + item + '</li>';
      });
      return out + '</ul>';
    });

    // ordered list
    html = html.replace(/((?:^|\n)\d+\.\s.+)+/g, function (block) {
      var out = '<ol class="t-ol">';
      block.trim().split('\n').forEach(function (line) {
        var item = line.replace(/^\d+\.\s+/, '').trim();
        if (item) out += '<li>' + item + '</li>';
      });
      return out + '</ol>';
    });

    html = html.replace(BUTTONS_TAG, function (m, raw) {
      return renderButtons(raw, mode);
    });

    html = html.replace(/\n{2,}/g, '</p><p class="t-p">');
    html = html.replace(/\n/g, '<br>');
    return html;
  }

  /**
   * Render every element carrying data-transcript-md in place.
   * Reads the raw text from textContent, so the server can emit it escaped.
   */
  function hydrate(scope) {
    var root = scope || document;
    var mode = root.documentElement && root.documentElement.getAttribute('data-links');
    if (!mode) {
      var b = (root.querySelector ? root.querySelector('[data-links]') : null);
      mode = b ? b.getAttribute('data-links') : 'anchor';
    }
    var nodes = root.querySelectorAll('[data-transcript-md]');
    Array.prototype.forEach.call(nodes, function (el) {
      el.innerHTML = render(el.textContent, { links: mode });
    });
  }

  root.BubblTranscript = {
    render: render,
    collectLinks: collectLinks,
    stripInternalTags: stripInternalTags,
    escapeHtml: escapeHtml,
    hydrate: hydrate
  };
})(typeof window !== 'undefined' ? window : this);
