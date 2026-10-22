/* libtini documentation: contents column, function finder, C highlighting
 * and links from code to the reference. The pages read fully without it. */
(function () {
  "use strict";
  var script = document.currentScript;
  var base = script ? script.src.replace(/assets\/site\.js(?:[?#].*)?$/, "") : "";

  var NAV = [
    ["Start", [
      ["index.html", "Overview"],
      ["start.html", "Getting started"],
      ["concepts.html", "How libtini works"],
      ["examples.html", "Examples"]
    ]],
    ["Guides", [
      ["guides/loop.html", "Game loop and timing"],
      ["guides/drawing.html", "Drawing and publishing"],
      ["guides/sound.html", "Music, effects and speech"],
      ["guides/input.html", "Keyboard and joystick"],
      ["guides/assets.html", "Art, fonts, maps and packs"],
      ["guides/saves.html", "Saved games"],
      ["guides/memory.html", "Memory and layouts"]
    ]],
    ["API", [
      ["api/index.html", "All functions"],
      ["api/errors.html", "Types and errors", "errors"],
      ["api/memory.html", "Memory", "memory"],
      ["api/timing.html", "Timing", "timing"],
      ["api/graphics.html", "Graphics", "graphics"],
      ["api/scene.html", "Sprite scenes", "scene"],
      ["api/audio.html", "Audio", "audio"],
      ["api/speech.html", "Speech", "speech"],
      ["api/input.html", "Input", "input"],
      ["api/storage.html", "Storage", "storage"],
      ["api/amem.html", "Optional AMEM", "amem"]
    ]],
    ["Reference", [
      ["reference/build.html", "Builds and game manifests"],
      ["reference/tools.html", "Tools"],
      ["reference/formats.html", "Data formats"],
      ["reference/machine.html", "Machine contract"],
      ["reference/browser.html", "Browser player"],
      ["reference/testing.html", "Checks and status"]
    ]]
  ];

  /* Every public name and the page that defines it. A value without '#'
   * links to the anchor with the symbol's own name. */
  var PAGES = {
    "api/errors.html": "ti_error ti_handle ti_error_keep ti_error_first ti_error_clear TI_OK TI_E_ARGUMENT TI_E_STATE TI_E_RANGE TI_E_NOMEM TI_E_HANDLE TI_E_UNAVAILABLE TI_E_TIMING TI_E_BUSY TI_E_IO TI_E_FORMAT TI_E_FULL TI_INVALID_HANDLE",
    "api/memory.html": "ti_init ti_shutdown ti_near_move ti_near_fill ti_res_alloc ti_res_free ti_res_read ti_res_write ti_res_fill ti_res_copy TI_RESOURCE_SLOTS TI_BANK_BYTES TI_TRANSFER_BYTES",
    "api/timing.html": "ti_tick_source ti_time_sample ti_time_begin ti_time_poll ti_time_note_gap ti_steps_begin ti_steps_reset ti_steps_due TI_STEPS_GAP TI_TIME_ELAPSED_VALID TI_TIME_GAP",
    "api/graphics.html": "ti_surface ti_rect ti_gfx_stats ti_sprite ti_tileset ti_tilemap ti_animation ti_bitmap_font ti_gfx_surface_create ti_gfx_surface_free ti_gfx_clear ti_gfx_rect ti_gfx_line ti_gfx_text ti_gfx_text_opaque ti_digits ti_gfx_text_font ti_gfx_blit ti_gfx_sprite ti_gfx_map ti_gfx_animation_frame ti_gfx_begin ti_gfx_palette ti_gfx_end ti_gfx_budget ti_gfx_present ti_gfx_present_rows TI_GFX_WIDTH TI_GFX_HEIGHT TI_GFX_OPAQUE TI_GFX_CLOCK_VALID TI_GFX_OVERRUN TI_GFX_EDGE_GAP",
    "api/scene.html": "ti_image ti_scene_config TI_SCENE_STORAGE ti_scene_begin ti_scene_frame ti_scene_add ti_scene_forget ti_scene_invalidate ti_scene_draw",
    "api/audio.html": "ti_audio_config ti_music_event ti_audio_init ti_audio_shutdown ti_audio_update ti_audio_ticks ti_audio_voices ti_audio_clock_valid ti_audio_source_hz ti_audio_tick_divisor ti_audio_mark_gap ti_audio_resume_clock ti_audio_reserve ti_audio_effect_voice ti_music_start ti_song_start ti_music_stop ti_audio_effect ti_audio_envelope ti_audio_envelope_stop TI_AUDIO_MOCKINGBOARD TI_AUDIO_PHASOR TI_AUDIO_TICKS_PER_SECOND",
    "api/speech.html": "ti_phrase ti_speech_bank ti_speech_bind ti_speech_say ti_speech_number ti_speech_busy ti_speech_stop ti_speech_voice TI_SPEECH_QUEUE TI_SPEECH_INTERRUPT",
    "api/input.html": "ti_joystick ti_input_poll ti_input_key ti_input_buttons ti_input_held ti_joystick_read ti_stick_read ti_stick_recalibrate ti_mouse_read ti_input_reset TI_STICK_UP TI_STICK_DOWN TI_STICK_LEFT TI_STICK_RIGHT TI_STICK_ABSENT",
    "api/storage.html": "ti_file_read ti_file_write ti_file_last_error ti_pack_load",
    "api/amem.html": "ti_amem_enable ti_amem_disable ti_amem_available ti_amem_last_error"
  };
  var CONSTANT_ANCHORS = {
    TI_GFX_WIDTH: "constants", TI_GFX_HEIGHT: "constants", TI_GFX_OPAQUE: "constants",
    TI_GFX_CLOCK_VALID: "constants", TI_GFX_OVERRUN: "constants", TI_GFX_EDGE_GAP: "constants",
    TI_RESOURCE_SLOTS: "constants", TI_BANK_BYTES: "constants", TI_TRANSFER_BYTES: "constants",
    TI_TIME_ELAPSED_VALID: "ti_time_sample", TI_TIME_GAP: "ti_time_sample", TI_STEPS_GAP: "ti_steps_begin",
    TI_AUDIO_MOCKINGBOARD: "constants", TI_AUDIO_PHASOR: "constants", TI_AUDIO_TICKS_PER_SECOND: "constants",
    TI_SPEECH_QUEUE: "constants", TI_SPEECH_INTERRUPT: "constants",
    TI_STICK_UP: "ti_stick_read", TI_STICK_DOWN: "ti_stick_read", TI_STICK_LEFT: "ti_stick_read",
    TI_STICK_RIGHT: "ti_stick_read", TI_STICK_ABSENT: "ti_stick_read"
  };
  var SYMBOLS = {};
  Object.keys(PAGES).forEach(function (page) {
    PAGES[page].split(" ").forEach(function (name) {
      SYMBOLS[name] = page + "#" + (CONSTANT_ANCHORS[name] || name);
    });
  });

  function url(path) { return base + path; }
  function here() {
    var h = location.href.split("#")[0].split("?")[0];
    return /\/$/.test(h) ? h + "index.html" : h;
  }
  function el(tag, attrs, text) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (text) e.textContent = text;
    return e;
  }

  function buildNav() {
    var side = document.getElementById("side");
    if (!side) return;
    var top = side.querySelector(".side-top") || side;
    var toggle = el("button", {"class": "nav-toggle", type: "button", "aria-expanded": "false", "aria-controls": "nav-body"}, "Contents");
    top.appendChild(toggle);
    var body = el("div", {"class": "nav-body", id: "nav-body"});
    var find = el("div", {"class": "find", role: "search"});
    var input = el("input", {type: "search", placeholder: "Find a function or type", "aria-label": "Find a function or type", autocomplete: "off", spellcheck: "false"});
    var results = el("ul");
    find.appendChild(input); find.appendChild(results);
    body.appendChild(find);
    var nav = el("nav", {"class": "site-nav", "aria-label": "Documentation"});
    var current = here();
    NAV.forEach(function (group) {
      nav.appendChild(el("h2", {}, group[0]));
      var ul = el("ul");
      group[1].forEach(function (item) {
        var li = el("li"), a = el("a", {href: url(item[0])});
        if (item[2]) {
          var mark = el("span", {"class": "mark", "aria-hidden": "true"});
          mark.style.background = "var(--m-" + item[2] + ")";
          a.appendChild(mark);
          a.style.setProperty("--nav-mark", "var(--m-" + item[2] + ")");
        }
        a.appendChild(document.createTextNode(item[1]));
        if (a.href === current) a.setAttribute("aria-current", "page");
        li.appendChild(a); ul.appendChild(li);
      });
      nav.appendChild(ul);
    });
    body.appendChild(nav);
    side.appendChild(body);
    toggle.addEventListener("click", function () {
      var open = side.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });

    var names = Object.keys(SYMBOLS).sort();
    function show() {
      var q = input.value.trim().toLowerCase();
      results.textContent = "";
      if (!q) return;
      var hits = names.filter(function (n) { return n.toLowerCase().indexOf(q) >= 0; });
      hits.sort(function (a, b) {
        var pa = a.toLowerCase().indexOf(q) === 0 ? 0 : 1, pb = b.toLowerCase().indexOf(q) === 0 ? 0 : 1;
        return pa - pb || a.length - b.length || (a < b ? -1 : 1);
      });
      hits.slice(0, 12).forEach(function (n) {
        var li = el("li"), a = el("a", {href: url(SYMBOLS[n])}, n);
        var page = SYMBOLS[n].split("#")[0].replace(/^api\//, "").replace(/\.html$/, "");
        a.appendChild(el("span", {"class": "where"}, "  " + page));
        li.appendChild(a); results.appendChild(li);
      });
      if (!hits.length) results.appendChild(el("li", {"class": "where"}, "No public name matches."));
    }
    input.addEventListener("input", show);
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        var first = results.querySelector("a");
        if (first) location.href = first.href;
      } else if (e.key === "Escape") {
        input.value = ""; show();
      }
    });
  }

  var KEYWORDS = {};
  ("auto break case char const continue default do else enum extern for goto if inline int long " +
   "register return short signed sizeof static struct switch typedef union unsigned void volatile while")
    .split(" ").forEach(function (w) { KEYWORDS[w] = "k"; });
  "uint8_t uint16_t uint32_t int8_t int16_t int32_t size_t".split(" ").forEach(function (w) { KEYWORDS[w] = "ty"; });
  var TOKEN = /(\/\*[\s\S]*?\*\/|\/\/[^\n]*)|("(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')|(^[ \t]*#[^\n]*)|(\b0x[0-9A-Fa-f]+[uUlL]*\b|\b\d+[uUlL]*\b)|([A-Za-z_]\w*)/gm;

  function escape(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
  function linkFor(name) { return SYMBOLS[name] ? url(SYMBOLS[name]) : null; }

  function highlight(code) {
    var text = code.textContent, out = "", last = 0, m;
    TOKEN.lastIndex = 0;
    while ((m = TOKEN.exec(text))) {
      out += escape(text.slice(last, m.index));
      var t = m[0], cls = null, href = null;
      if (m[1]) cls = "cm";
      else if (m[2]) cls = "s";
      else if (m[3]) cls = "p";
      else if (m[4]) cls = "n";
      else { cls = KEYWORDS[t] || null; href = linkFor(t); }
      if (href) out += '<a href="' + href + '">' + escape(t) + "</a>";
      else out += cls ? '<span class="' + cls + '">' + escape(t) + "</span>" : escape(t);
      last = m.index + t.length;
    }
    code.innerHTML = out + escape(text.slice(last));
  }

  function linkInline() {
    var codes = document.querySelectorAll("main code:not(.def)");
    Array.prototype.forEach.call(codes, function (code) {
      if (code.closest("pre, a, .sig")) return;
      var name = code.textContent.trim().replace(/\(\)$/, "");
      var href = linkFor(name);
      if (!href) return;
      var a = el("a", {href: href});
      code.parentNode.insertBefore(a, code);
      a.appendChild(code);
    });
  }

  function linkSignatures() {
    Array.prototype.forEach.call(document.querySelectorAll(".sig"), function (sig) {
      var own = sig.getAttribute("data-name");
      sig.innerHTML = escape(sig.textContent).replace(/\b(ti_\w+|TI_\w+)\b/g, function (name) {
        var href = linkFor(name);
        return href && name !== own ? '<a href="' + href + '">' + name + "</a>" : name;
      });
    });
  }

  function run() {
    buildNav();
    Array.prototype.forEach.call(document.querySelectorAll("pre code.c"), highlight);
    linkSignatures();
    linkInline();
    if (location.hash) {
      var target = document.getElementById(decodeURIComponent(location.hash.slice(1)));
      if (target) target.scrollIntoView();
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", run);
  else run();
})();
