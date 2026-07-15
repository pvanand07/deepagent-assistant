const { createApp, ref, reactive, computed, nextTick, onMounted, onBeforeUnmount } = Vue;

/* ---------------------------------------------------------------- */
/* Constants and pure helpers                                        */
/* ---------------------------------------------------------------- */

const API = window.location.origin;
const SESSION_KEY = "deepagent_session_id";
const TERMINAL_RUN_EVENTS = new Set(["done", "cancelled", "error"]);

/* One coherent icon set (Phosphor, 256 viewBox), rendered by <p-icon>. */
const ICON_PATHS = {
  plus: "M224,128a8,8,0,0,1-8,8H136v80a8,8,0,0,1-16,0V136H40a8,8,0,0,1,0-16h80V40a8,8,0,0,1,16,0v80h80A8,8,0,0,1,224,128Z",
  refresh: "M240,56v48a8,8,0,0,1-8,8H184a8,8,0,0,1,0-16h28.69L182.06,65.37a79.56,79.56,0,0,0-56.13-23.43h-.45A79.52,79.52,0,0,0,69.59,64.72,8,8,0,0,1,58.41,53.28a96,96,0,0,1,135,.79L224,84.69V56a8,8,0,0,1,16,0Zm-27.59,134.72a80,80,0,0,1-112.47.66L69.25,161H98a8,8,0,0,0,0-16H50a8,8,0,0,0-8,8v48a8,8,0,0,0,16,0V172.69l30.63,30.28a96,96,0,0,0,135-.79,8,8,0,0,0-11.18-11.46Z",
  folder: "M216,72H131.31L104,44.69A15.86,15.86,0,0,0,92.69,40H40A16,16,0,0,0,24,56V200.62A15.4,15.4,0,0,0,39.38,216H216.89A15.13,15.13,0,0,0,232,200.89V88A16,16,0,0,0,216,72Zm0,128H40V56H92.69l27.32,27.32A15.86,15.86,0,0,0,131.31,88H216Z",
  file: "M213.66,82.34l-56-56A8,8,0,0,0,152,24H56A16,16,0,0,0,40,40V216a16,16,0,0,0,16,16H200a16,16,0,0,0,16-16V88A8,8,0,0,0,213.66,82.34ZM160,51.31,188.69,80H160ZM200,216H56V40h88V88a8,8,0,0,0,8,8h48V216Z",
  "caret-right": "M181.66,133.66l-80,80a8,8,0,0,1-11.32-11.32L164.69,128,90.34,53.66a8,8,0,0,1,11.32-11.32l80,80A8,8,0,0,1,181.66,133.66Z",
  "caret-down": "M213.66,101.66l-80,80a8,8,0,0,1-11.32,0l-80-80A8,8,0,0,1,53.66,90.34L128,164.69l74.34-74.35a8,8,0,0,1,11.32,11.32Z",
  download: "M224,152v56a16,16,0,0,1-16,16H48a16,16,0,0,1-16-16V152a8,8,0,0,1,16,0v56H208V152a8,8,0,0,1,16,0Zm-101.66,5.66a8,8,0,0,0,11.32,0l40-40a8,8,0,0,0-11.32-11.32L136,132.69V40a8,8,0,0,0-16,0v92.69L93.66,106.34a8,8,0,0,0-11.32,11.32Z",
  cpu: "M112,96h32a8,8,0,0,1,8,8v48a8,8,0,0,1-8,8H112a8,8,0,0,1-8-8V104A8,8,0,0,1,112,96Zm120,40a8,8,0,0,1-8,8H208v16a32,32,0,0,1-32,32H160v16a8,8,0,0,1-16,0V192H112v16a8,8,0,0,1-16,0V192H80a32,32,0,0,1-32-32V144H32a8,8,0,0,1,0-16H48V96H32a8,8,0,0,1,0-16H48V64A32,32,0,0,1,80,32H96V16a8,8,0,0,1,16,0V32h32V16a8,8,0,0,1,16,0V32h16a32,32,0,0,1,32,32V80h16a8,8,0,0,1,0,16H208v32h16A8,8,0,0,1,232,136ZM192,64a16,16,0,0,0-16-16H80A16,16,0,0,0,64,64v96a16,16,0,0,0,16,16h96a16,16,0,0,0,16-16Z",
  search: "M229.66,218.34l-50.07-50.06a88.11,88.11,0,1,0-11.31,11.31l50.06,50.07a8,8,0,0,0,11.32-11.32ZM40,112a72,72,0,1,1,72,72A72.08,72.08,0,0,1,40,112Z",
  info: "M128,24A104,104,0,1,0,232,128,104.11,104.11,0,0,0,128,24Zm0,192a88,88,0,1,1,88-88A88.1,88.1,0,0,1,128,216Zm16-40a8,8,0,0,1-8,8,16,16,0,0,1-16-16V128a8,8,0,0,1,0-16,16,16,0,0,1,16,16v40A8,8,0,0,1,144,176ZM112,84a12,12,0,1,1,12,12A12,12,0,0,1,112,84Z",
  warning: "M128,24A104,104,0,1,0,232,128,104.11,104.11,0,0,0,128,24Zm-8,56a8,8,0,0,1,16,0v56a8,8,0,0,1-16,0Zm8,104a12,12,0,1,1,12-12A12,12,0,0,1,128,184Z",
  x: "M205.66,194.34a8,8,0,0,1-11.32,11.32L128,139.31,61.66,205.66a8,8,0,0,1-11.32-11.32L116.69,128,50.34,61.66A8,8,0,0,1,61.66,50.34L128,116.69l66.34-66.35a8,8,0,0,1,11.32,11.32L139.31,128Z",
  check: "M229.66,77.66l-128,128a8,8,0,0,1-11.32,0l-56-56a8,8,0,0,1,11.32-11.32L96,188.69,218.34,66.34a8,8,0,0,1,11.32,11.32Z",
  "arrow-up": "M205.66,117.66a8,8,0,0,1-11.32,0L136,59.31V216a8,8,0,0,1-16,0V59.31L61.66,117.66a8,8,0,0,1-11.32-11.32l72-72a8,8,0,0,1,11.32,0l72,72A8,8,0,0,1,205.66,117.66Z",
  stop: "M200,40H56A16,16,0,0,0,40,56V200a16,16,0,0,0,16,16H200a16,16,0,0,0,16-16V56A16,16,0,0,0,200,40Z",
  cube: "M223.68,66.15,135.68,18a15.88,15.88,0,0,0-15.36,0l-88,48.17a16,16,0,0,0-8.32,14v95.64a16,16,0,0,0,8.32,14l88,48.17a15.88,15.88,0,0,0,15.36,0l88-48.17a16,16,0,0,0,8.32-14V80.18A16,16,0,0,0,223.68,66.15ZM128,32l80.34,44-29.77,16.3-80.35-44ZM128,120,47.66,76l33.9-18.56,80.34,44ZM40,90l80,43.78v85.79L40,175.82Zm176,85.78h0l-80,43.79V133.82l32-17.51V152a8,8,0,0,0,16,0V107.55L216,90v85.77Z",
  terminal: "M117.31,134l-72,64a8,8,0,1,1-10.63-12L100,128,34.69,70A8,8,0,1,1,45.32,58l72,64a8,8,0,0,1,0,12ZM216,184H120a8,8,0,0,0,0,16h96a8,8,0,0,0,0-16Z",
  subagent: "M248,124a59.92,59.92,0,0,0-29.85-51.85,44,44,0,0,0-86.3,0A59.92,59.92,0,0,0,8,124a60.07,60.07,0,0,0,40,56.44V192a8,8,0,0,0,8,8h48a8,8,0,0,0,8-8v-11.56A60.07,60.07,0,0,0,248,124ZM172,200H84V181.56a8,8,0,0,0-2.67-6A44,44,0,0,1,52.17,140.17a8,8,0,0,0-6-2.67,44,44,0,0,1,0-19A8,8,0,0,0,52.17,115.83a44,44,0,0,1,29.16-35.39,8,8,0,0,0,6-2.67,44,44,0,0,1,19,0,8,8,0,0,0,6,2.67A44,44,0,0,1,141.83,115.83a8,8,0,0,0,6,2.67,44,44,0,0,1,0,19,8,8,0,0,0-2.67,6A44,44,0,0,1,116,175.56a8,8,0,0,0-2.67,6Z",
  sidebar: "M216,40H40A16,16,0,0,0,24,56V200a16,16,0,0,0,16,16H216a16,16,0,0,0,16-16V56A16,16,0,0,0,216,40ZM40,56H80V200H40ZM216,200H96V56H216V200Z",
  external: "M224,104a8,8,0,0,1-16,0V59.31l-82.34,82.35a8,8,0,0,1-11.32-11.32L196.69,48H152a8,8,0,0,1,0-16h64a8,8,0,0,1,8,8Zm-40,24a8,8,0,0,0-8,8v72H48V80h72a8,8,0,0,0,0-16H48A16,16,0,0,0,32,80V208a16,16,0,0,0,16,16H176a16,16,0,0,0,16-16V136A8,8,0,0,0,184,128Z",
  "corners-out": "M216,48V96a8,8,0,0,1-16,0V67.31l-42.34,42.35a8,8,0,0,1-11.32-11.32L188.69,56H160a8,8,0,0,1,0-16h48A8,8,0,0,1,216,48ZM98.34,146.34,56,188.69V160a8,8,0,0,0-16,0v48a8,8,0,0,0,8,8H96a8,8,0,0,0,0-16H67.31l42.35-42.34a8,8,0,0,0-11.32-11.32ZM208,152a8,8,0,0,0-8,8v28.69l-42.34-42.35a8,8,0,0,0-11.32,11.32L188.69,200H160a8,8,0,0,0,0,16h48a8,8,0,0,0,8-8V160A8,8,0,0,0,208,152ZM67.31,56H96a8,8,0,0,0,0-16H48a8,8,0,0,0-8,8V96a8,8,0,0,0,16,0V67.31l42.34,42.35a8,8,0,0,0,11.32-11.32Z",
  "corners-in": "M144,104V56a8,8,0,0,1,16,0V84.69l42.34-42.35a8,8,0,0,1,11.32,11.32L171.31,96H200a8,8,0,0,1,0,16H152A8,8,0,0,1,144,104ZM104,144H56a8,8,0,0,0,0,16H84.69L42.34,202.34a8,8,0,0,0,11.32,11.32L96,171.31V200a8,8,0,0,0,16,0V152A8,8,0,0,0,104,144Zm96,0H152a8,8,0,0,0-8,8v48a8,8,0,0,0,16,0V171.31l42.34,42.35a8,8,0,0,0,11.32-11.32L171.31,160H200a8,8,0,0,0,0-16ZM104,40a8,8,0,0,0-8,8V84.69L53.66,42.34A8,8,0,0,0,42.34,53.66L84.69,96H56a8,8,0,0,0,0,16h48a8,8,0,0,0,8-8V56A8,8,0,0,0,104,40Z",
};

/* Tiny icon component so every icon is rendered the same way. */
const PIcon = {
  name: "PIcon",
  props: { name: { type: String, required: true }, size: { type: [Number, String], default: 16 } },
  computed: { path() { return ICON_PATHS[this.name] || ICON_PATHS.file; } },
  template: `
    <svg xmlns="http://www.w3.org/2000/svg" :width="size" :height="size" fill="currentColor"
      viewBox="0 0 256 256" aria-hidden="true"><path :d="path"/></svg>
  `,
};

/* Shared icon-button style: one size, one hover, one disabled treatment. */
const ICON_BTN =
  "inline-flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors " +
  "hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-40";

const IMAGE_EXT = new Set(["png", "jpg", "jpeg", "gif", "webp", "bmp", "ico", "avif"]);
const CODE_LANG = {
  js: "javascript", mjs: "javascript", cjs: "javascript", jsx: "javascript",
  ts: "typescript", tsx: "typescript",
  py: "python", rb: "ruby", rs: "rust", go: "go",
  java: "java", kt: "kotlin", swift: "swift", php: "php",
  sh: "bash", bash: "bash", zsh: "bash",
  yaml: "yaml", yml: "yaml", toml: "ini", ini: "ini",
  xml: "xml", sql: "sql", graphql: "graphql", gql: "graphql",
  scss: "scss", less: "less",
  c: "c", h: "c", cpp: "cpp", cc: "cpp", cxx: "cpp", hpp: "cpp",
  cs: "csharp", lua: "lua", r: "r", vue: "xml", svelte: "xml",
  json: "json", css: "css", html: "xml",
};

const fileName = (p) => (p || "").split("/").filter(Boolean).pop() || "file";
const fileExt = (p) => fileName(p).toLowerCase().split(".").pop() || "";
const isImagePath = (p) => IMAGE_EXT.has(fileExt(p));
const truncate = (t, max = 48) => {
  const s = (t || "").trim();
  return s.length <= max ? (s || "New chat") : s.slice(0, max - 1) + "…";
};

/** Short label for pickers: `anthropic/claude-sonnet-4.5` → `Claude Sonnet 4.5`. */
function modelDisplayName(id) {
  const raw = (id || "").trim();
  if (!raw) return "";
  const slug = raw.includes("/") ? raw.split("/").pop() : raw;
  return slug
    .replace(/[-_]+/g, " ")
    .replace(/\b([a-z])/g, (ch) => ch.toUpperCase());
}

/** Workspace root + top-level folders only (no nested paths). */
function rootFoldersOnly(folders) {
  const out = [""];
  for (const f of folders || []) {
    const path = (f || "").trim().replace(/^\/+|\/+$/g, "");
    if (!path || path.includes("/")) continue;
    if (!out.includes(path)) out.push(path);
  }
  return [out[0], ...out.slice(1).sort((a, b) => a.localeCompare(b))];
}

function codeLanguageFor(path) {
  const base = fileName(path).toLowerCase();
  if (base === "dockerfile") return "dockerfile";
  if (base === "makefile") return "makefile";
  return CODE_LANG[fileExt(path)] || "plaintext";
}

function previewModeFor(path) {
  const ext = fileExt(path);
  const base = fileName(path).toLowerCase();
  if (isImagePath(path)) return "image";
  if (ext === "html" || ext === "htm" || ext === "svg") return "html";
  if (ext === "md" || ext === "mdx") return "markdown";
  if (ext === "csv" || ext === "tsv") return "csv";
  if (ext === "css") return "css";
  if (base === "dockerfile" || base === "makefile" || CODE_LANG[ext]) return "code";
  return "text";
}

/* CSV parsing that handles quoted newlines. */
function parseDelimited(text, delimiter) {
  const rows = [];
  let row = [], cell = "", inQuotes = false;
  const src = text.replace(/\r\n/g, "\n");
  for (let i = 0; i < src.length; i++) {
    const ch = src[i];
    if (ch === '"') {
      if (inQuotes && src[i + 1] === '"') { cell += '"'; i++; }
      else inQuotes = !inQuotes;
    } else if (ch === delimiter && !inQuotes) {
      row.push(cell); cell = "";
    } else if (ch === "\n" && !inQuotes) {
      row.push(cell); cell = "";
      if (row.some((c) => c.trim() !== "")) rows.push(row);
      row = [];
    } else {
      cell += ch;
    }
  }
  row.push(cell);
  if (row.some((c) => c.trim() !== "")) rows.push(row);
  return rows;
}

function cssPreviewDocument(css) {
  const safe = css.replace(/<\/style/gi, "<\\/style");
  return `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/><style>${safe}</style></head><body><main><h1>Preview heading</h1><p>Sample paragraph with <a href="#">a link</a>, <strong>bold</strong>, and <em>italic</em> text.</p><ul><li>First list item</li><li>Second list item</li></ul><button type="button">Button</button><input type="text" value="Input field" aria-label="Sample input"/></main></body></html>`;
}

function prettyJson(text) {
  try { return JSON.stringify(JSON.parse(text), null, 2); }
  catch { return text; }
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function normalizeWorkspacePath(path) {
  return String(path || "")
    .trim()
    .replace(/^\/+/, "")
    .replace(/^workspace\//, "");
}

function previewTagToButton(attrStr, innerLabel) {
  const path = attrStr.match(/path\s*=\s*["']([^"']+)["']/i)?.[1];
  const labelAttr = attrStr.match(/label\s*=\s*["']([^"']+)["']/i)?.[1];
  const label = (innerLabel || labelAttr || "Open preview").trim();
  const cleanPath = normalizeWorkspacePath(path);
  if (!cleanPath) return "";
  return `<button type="button" class="preview-action-btn" data-preview-path="${escapeHtml(cleanPath)}">${escapeHtml(label)}</button>`;
}

/** Expand <preview> XML tags from assistant messages into clickable UI buttons. */
function expandPreviewTags(text) {
  if (!text) return text;
  return text
    .replace(/<preview\s+([^>]*?)\/>/gi, (_, attrs) => previewTagToButton(attrs))
    .replace(/<preview\s+([^>]*)>([\s\S]*?)<\/preview>/gi, (_, attrs, label) => previewTagToButton(attrs, label));
}

marked.setOptions({
  breaks: true,
  gfm: true,
  highlight(code, lang) {
    try {
      if (lang && hljs.getLanguage(lang)) return hljs.highlight(code, { language: lang }).value;
      return hljs.highlightAuto(code).value;
    } catch { return code; }
  },
});
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A") {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  }
});

/* Incremental SSE parser: handles CRLF, multi-line data fields, comments. */
function createSseParser() {
  let buffer = "";
  return function feed(chunk) {
    buffer += chunk;
    const events = [];
    buffer = buffer.replace(/\r\n/g, "\n");
    let sep;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      if (!block.trim()) continue;
      let eventType = "message";
      const dataLines = [];
      for (const line of block.split("\n")) {
        if (line.startsWith(":")) continue;
        if (line.startsWith("event:")) eventType = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
      }
      if (!dataLines.length) continue;
      try { events.push({ event: eventType, data: JSON.parse(dataLines.join("\n")) }); }
      catch { /* skip malformed frames */ }
    }
    return events;
  };
}

/* ---------------------------------------------------------------- */
/* Recursive file-tree node                                          */
/* ---------------------------------------------------------------- */

const FileNode = {
  name: "FileNode",
  components: { PIcon },
  props: ["entry", "depth", "expanded", "childrenMap", "activePath"],
  emits: ["toggle", "preview", "download"],
  computed: {
    isExpanded() { return this.expanded.has(this.entry.path); },
    isActive() { return !this.entry.is_dir && this.activePath === this.entry.path; },
    children() { return this.childrenMap[this.entry.path]; },
    indent() { return { paddingLeft: `${this.depth * 0.875 + 0.375}rem` }; },
    childIndent() { return { paddingLeft: `${(this.depth + 1) * 0.875 + 0.375}rem` }; },
  },
  template: `
    <li class="flex flex-col gap-px" :title="entry.path">
      <div class="group flex h-6 items-center gap-1 rounded-md pr-1 transition-colors"
        :class="isActive ? 'bg-accent-soft text-accent' : 'hover:bg-muted'"
        :style="indent">

        <button v-if="entry.is_dir" type="button"
          class="flex h-full min-w-0 flex-1 items-center gap-1.5 text-left"
          :aria-expanded="String(isExpanded)" @click="$emit('toggle', entry.path)">
          <p-icon name="caret-right" :size="9"
            class="shrink-0 text-muted-foreground/50 transition-transform duration-150"
            :class="{ 'rotate-90': isExpanded }" />
          <p-icon name="folder" :size="13" class="shrink-0 text-muted-foreground/70" />
          <span class="min-w-0 truncate">{{ entry.name }}</span>
        </button>

        <button v-else type="button"
          class="flex h-full min-w-0 flex-1 items-center gap-1.5 text-left"
          :class="isActive ? 'font-medium' : ''"
          @click="$emit('preview', entry.path)">
          <span class="w-[9px] shrink-0" aria-hidden="true"></span>
          <p-icon name="file" :size="13" class="shrink-0"
            :class="isActive ? 'text-accent' : 'text-muted-foreground/60'" />
          <span class="min-w-0 truncate">{{ entry.name }}</span>
        </button>

        <button v-if="!entry.is_dir" type="button"
          class="hidden size-5 shrink-0 place-items-center rounded text-muted-foreground/70 transition-colors hover:bg-background hover:text-foreground group-hover:grid"
          :title="'Download ' + entry.name" :aria-label="'Download ' + entry.name"
          @click.stop="$emit('download', entry.path)">
          <p-icon name="download" :size="11" />
        </button>
      </div>

      <ul v-if="entry.is_dir && isExpanded" class="flex flex-col gap-px">
        <li v-if="children === undefined" class="h-6 leading-6 text-muted-foreground/60" :style="childIndent">Loading…</li>
        <li v-else-if="!children.length" class="h-6 leading-6 text-muted-foreground/50" :style="childIndent">Empty folder</li>
        <file-node v-else v-for="child in children" :key="child.path" :entry="child" :depth="depth + 1"
          :expanded="expanded" :children-map="childrenMap" :active-path="activePath"
          @toggle="$emit('toggle', $event)" @preview="$emit('preview', $event)" @download="$emit('download', $event)" />
      </ul>
    </li>
  `,
};

const PwdPicker = {
  name: "PwdPicker",
  components: { PIcon },
  props: {
    streaming: { type: Boolean, default: false },
    folders: { type: Array, default: () => [""] },
    selected: { type: String, default: "" },
    closeSignal: { type: Number, default: 0 },
  },
  emits: ["select"],
  data() {
    return { menuOpen: false, menuStyle: {} };
  },
  computed: {
    label() {
      return this.selected ? this.selected.split("/").pop() : "Workspace root";
    },
  },
  watch: {
    closeSignal() {
      this.menuOpen = false;
    },
    streaming(val) {
      if (val) this.menuOpen = false;
    },
    menuOpen(val) {
      if (val) this.$nextTick(() => this.positionMenu());
    },
    folders() {
      if (this.menuOpen) this.$nextTick(() => this.positionMenu());
    },
  },
  mounted() {
    this._onDocClick = (e) => {
      if (!this.menuOpen) return;
      const target = e.target;
      if (target.closest("[data-pwd-menu]") || this.$el.contains(target)) return;
      this.menuOpen = false;
    };
    this._onLayout = () => { if (this.menuOpen) this.positionMenu(); };
    document.addEventListener("click", this._onDocClick);
    window.addEventListener("resize", this._onLayout);
    window.addEventListener("scroll", this._onLayout, true);
  },
  beforeUnmount() {
    document.removeEventListener("click", this._onDocClick);
    window.removeEventListener("resize", this._onLayout);
    window.removeEventListener("scroll", this._onLayout, true);
  },
  methods: {
    toggle() {
      this.menuOpen = !this.menuOpen;
    },
    close() {
      this.menuOpen = false;
    },
    positionMenu() {
      const r = this.$el.getBoundingClientRect();
      const menuWidth = Math.min(Math.max(r.width, 220), window.innerWidth - 16);
      const left = Math.max(8, Math.min(r.left, window.innerWidth - menuWidth - 8));
      this.menuStyle = {
        position: "fixed",
        left: `${left}px`,
        bottom: `${window.innerHeight - r.top + 8}px`,
        width: `${menuWidth}px`,
        zIndex: 200,
      };
    },
  },
  template: `
    <div class="relative min-w-[8.5rem] max-w-52 shrink-0">
      <button type="button" data-pwd-picker-trigger :disabled="streaming"
        class="inline-flex h-8 w-full items-center gap-1.5 rounded-full bg-muted px-2.5 text-xs text-muted-foreground transition-colors hover:bg-muted/80 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
        aria-haspopup="listbox" :aria-expanded="String(menuOpen)" title="Working directory for this message">
        <p-icon name="folder" :size="14" class="shrink-0 text-muted-foreground/70" />
        <span class="min-w-0 truncate">{{ label }}</span>
        <p-icon name="caret-down" :size="11"
          class="shrink-0 text-muted-foreground/50 transition-transform duration-150"
          :class="{ 'rotate-180': menuOpen }" />
      </button>
      <teleport to="body">
        <div v-if="menuOpen" :style="menuStyle"
          class="overflow-hidden rounded-xl border border-border bg-background p-1 shadow-lg"
          role="listbox" aria-label="Working directory" data-pwd-menu>
          <ul class="scrollbar-hide flex max-h-56 flex-col gap-0.5 overflow-y-auto">
            <li v-for="folder in folders" :key="folder || '__root__'">
              <button type="button" role="option" data-pwd-option :data-folder="folder"
                :aria-selected="String(folder === selected)"
                class="flex w-full min-w-0 items-center gap-2 rounded-lg py-1.5 pl-2.5 pr-2 text-left text-xs leading-5 transition-colors"
                :class="folder === selected
                  ? 'bg-accent-soft font-medium text-accent'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'">
                <p-icon name="folder" :size="14" class="shrink-0"
                  :class="folder === selected ? 'text-accent' : 'text-muted-foreground/70'" />
                <span class="min-w-0 flex-1 truncate">{{ folder || 'Workspace root' }}</span>
                <p-icon v-if="folder === selected" name="check" :size="12" class="shrink-0 text-accent" />
              </button>
            </li>
          </ul>
        </div>
      </teleport>
    </div>
  `,
};

const ModelPicker = {
  name: "ModelPicker",
  components: { PIcon },
  props: {
    streaming: { type: Boolean, default: false },
    selected: { type: String, default: "" },
    groups: { type: Array, default: () => [] },
    closeSignal: { type: Number, default: 0 },
    loading: { type: Boolean, default: false },
  },
  emits: ["select", "add", "open"],
  data() {
    return { menuOpen: false, menuStyle: {}, search: "" };
  },
  computed: {
    label() {
      const m = (this.selected || "").trim();
      if (!m) return "Select model";
      return modelDisplayName(m);
    },
    filteredGroups() {
      const q = (this.search || "").toLowerCase().trim();
      const out = [];
      for (const g of this.groups || []) {
        const models = (g.models || []).filter((m) => {
          if (!q) return true;
          const id = (m.id || "").toLowerCase();
          const name = modelDisplayName(m.id).toLowerCase();
          return id.includes(q) || name.includes(q);
        });
        if (models.length) out.push({ name: g.name, models });
      }
      return out;
    },
  },
  watch: {
    closeSignal() {
      this.menuOpen = false;
    },
    streaming(val) {
      if (val) this.menuOpen = false;
    },
    menuOpen(val) {
      if (val) {
        this.search = "";
        this.$emit("open");
        this.$nextTick(() => {
          this.positionMenu();
          const input = this.$refs.searchInput;
          if (input) input.focus();
        });
      }
    },
    groups() {
      if (this.menuOpen) this.$nextTick(() => this.positionMenu());
    },
  },
  mounted() {
    this._onDocClick = (e) => {
      if (!this.menuOpen) return;
      const target = e.target;
      if (target.closest("[data-model-menu]") || this.$el.contains(target)) return;
      this.menuOpen = false;
    };
    this._onLayout = () => { if (this.menuOpen) this.positionMenu(); };
    document.addEventListener("click", this._onDocClick);
    window.addEventListener("resize", this._onLayout);
    window.addEventListener("scroll", this._onLayout, true);
  },
  beforeUnmount() {
    document.removeEventListener("click", this._onDocClick);
    window.removeEventListener("resize", this._onLayout);
    window.removeEventListener("scroll", this._onLayout, true);
  },
  methods: {
    displayName(id) {
      return modelDisplayName(id);
    },
    toggle() {
      this.menuOpen = !this.menuOpen;
    },
    close() {
      this.menuOpen = false;
    },
    positionMenu() {
      const r = this.$el.getBoundingClientRect();
      const menuWidth = Math.min(Math.max(280, r.width), window.innerWidth - 16);
      const left = Math.max(8, Math.min(r.left, window.innerWidth - menuWidth - 8));
      this.menuStyle = {
        position: "fixed",
        left: `${left}px`,
        bottom: `${window.innerHeight - r.top + 8}px`,
        width: `${menuWidth}px`,
        zIndex: 200,
      };
    },
    pick(id) {
      this.menuOpen = false;
      if (id && id !== this.selected) this.$emit("select", id);
    },
    onAdd() {
      this.menuOpen = false;
      this.$emit("add");
    },
  },
  template: `
    <div class="relative min-w-0 max-w-40 shrink-0 sm:min-w-[9rem] sm:max-w-56">
      <button type="button" data-model-picker-trigger :disabled="streaming" @click.stop="toggle"
        class="inline-flex h-8 w-full items-center gap-1.5 rounded-full bg-muted px-2.5 text-xs text-muted-foreground transition-colors hover:bg-muted/80 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
        aria-haspopup="listbox" :aria-expanded="String(menuOpen)" :title="selected || label">
        <p-icon name="cpu" :size="14" class="shrink-0 text-muted-foreground/70" />
        <span class="min-w-0 truncate">{{ label }}</span>
        <p-icon name="caret-down" :size="11"
          class="shrink-0 text-muted-foreground/50 transition-transform duration-150"
          :class="{ 'rotate-180': menuOpen }" />
      </button>
      <teleport to="body">
        <div v-if="menuOpen" :style="menuStyle"
          class="overflow-hidden rounded-xl border border-border bg-background shadow-lg"
          role="listbox" aria-label="Select model" data-model-menu>
          <div class="border-b border-border p-2">
            <div class="flex h-8 items-center gap-2 rounded-lg bg-muted px-2.5">
              <p-icon name="search" :size="13" class="shrink-0 text-muted-foreground/60" />
              <input ref="searchInput" v-model="search" type="text" placeholder="Search models"
                class="min-w-0 flex-1 border-0 bg-transparent text-xs text-foreground outline-none placeholder:text-muted-foreground"
                @keydown.escape.stop="close()" />
            </div>
          </div>
          <div class="scrollbar-hide max-h-64 overflow-y-auto p-1">
            <p v-if="loading" class="px-2.5 py-3 text-xs text-muted-foreground">Loading models…</p>
            <template v-else-if="filteredGroups.length">
              <div v-for="group in filteredGroups" :key="group.name" class="mb-0.5">
                <p class="px-2.5 pb-1 pt-1.5 text-[11px] font-medium text-muted-foreground">{{ group.name }}</p>
                <ul class="flex flex-col gap-0.5">
                  <li v-for="mod in group.models" :key="mod.id">
                    <button type="button" role="option"
                      :aria-selected="String(mod.id === selected)"
                      class="flex w-full min-w-0 items-center gap-2 rounded-lg px-2.5 py-2 text-left transition-colors"
                      :class="mod.id === selected
                        ? 'bg-muted text-foreground'
                        : 'text-foreground hover:bg-muted'"
                      @click="pick(mod.id)">
                      <span class="min-w-0 flex-1 truncate text-sm font-medium">{{ displayName(mod.id) }}</span>
                      <p-icon v-if="mod.id === selected" name="check" :size="14" class="shrink-0 text-accent" />
                    </button>
                  </li>
                </ul>
              </div>
            </template>
            <p v-else class="px-2.5 py-3 text-xs text-muted-foreground">No matching models</p>
          </div>
          <div class="border-t border-border p-1">
            <button type="button"
              class="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              @click="onAdd">
              <p-icon name="plus" :size="12" class="shrink-0" />
              <span>Add Model</span>
            </button>
          </div>
        </div>
      </teleport>
    </div>
  `,
};

/* ---------------------------------------------------------------- */
/* App                                                               */
/* ---------------------------------------------------------------- */

createApp({
  components: {
    FileNode,
    PIcon,
    PwdPicker,
    ModelPicker,
    "pwd-picker": PwdPicker,
    "model-picker": ModelPicker,
  },
  setup() {
    /* ---------- session / config ---------- */
    const config = ref(null);
    const session = ref(null);
    const sessionId = ref(null);
    const sessionInfoOpen = ref(false);
    const sessionInfoEl = ref(null);
    const sessionList = ref([]);
    const sessionListLoading = ref(false);
    const route = ref(location.hash.replace(/^#\/?/, "") === "settings" ? "settings" : "chat");
    const setupRequired = ref(false);
    const setupSaving = ref(false);
    const setupError = ref("");
    const setupForm = reactive({
      kind: "openrouter",
      baseUrl: "",
      apiKey: "",
      model: "anthropic/claude-sonnet-4.5",
    });
    const setupCatalog = ref([]);
    const setupCatalogLoading = ref(false);
    const setupCatalogError = ref("");
    const settingsPanel = ref("models");
    const settingsConfig = reactive({
      platforms: [],
      default_model: "",
      active_platform_id: "",
      temperature: 0.3,
    });
    const settingsMeta = reactive({
      data_dir: "", workdir: "", env_path: "", settings_path: "", values: {},
    });
    const sandboxForm = reactive({
      network: false,
      memory_mib: 2048,
      cpus: 2,
      dns_nameservers: "1.1.1.1,8.8.8.8",
      exec_timeout: 120,
      idle_timeout: 600,
    });
    const settingsSaving = ref(false);
    const settingsMessage = ref("");
    const settingsError = ref(false);
    const sandboxRetrying = ref(false);
    const collapsedPlatforms = reactive({});
    const modal = ref("");
    const toastMsg = ref("");
    let toastTimer = null;
    const appVersion = ref("0.1.0");
    const updateChecking = ref(false);
    const updateInstalling = ref(false);
    const pendingUpdateVersion = ref("");
    let updateEventUnlisten = null;
    const platformDraft = reactive({
      isNew: false, id: "", name: "", kind: "openrouter", base_url: "",
      api_key: "", api_key_set: false, site_url: "", site_name: "", enabled: true,
    });
    const addModelPlatformId = ref("");
    const modelSearch = ref("");
    const catalogModels = ref([]);
    const catalogLoading = ref(false);
    const catalogError = ref("");
    const selectedCatalogIds = ref([]);
    const modelDraft = reactive({ platformId: "", id: "", temperature: 0.3 });
    const mcpServers = reactive({});
    const mcpMeta = reactive({ path: "" });
    const mcpStatus = reactive({});
    const mcpDraft = reactive({
      isNew: true, name: "", transport: "stdio", command: "", args: "",
      url: "", bearer_token: "",
    });
    const mcpImportJson = ref(`{\n  "mcpServers": {\n  }\n}`);
    const mcpImportError = ref("");

    const filteredCatalog = computed(() => {
      const q = (modelSearch.value || "").toLowerCase().trim();
      const list = catalogModels.value || [];
      if (!q) return list;
      return list.filter((m) => m.id.toLowerCase().includes(q) || (m.name || "").toLowerCase().includes(q));
    });

    /* ---------- runs ----------
       activeRuns maps sessionId -> run_id for every run the server reports
       as in flight. The agent turn executes server-side as a background run,
       so it keeps going when we switch sessions, close the SSE reader, or
       reload the page; this map is what lets any session's UI know there is
       something to reattach to. Exactly one SSE reader is open at a time --
       the one observing the currently visible session. */
    const activeRuns = reactive({});
    let runAbort = null;   // AbortController for the visible SSE reader
    let turnCtx = null;    // render state for the currently attached run

    /* ---------- chat ---------- */
    const timeline = ref([]);
    const draft = ref("");
    const thinking = ref(false);
    const errorMessage = ref("");
    const sidebarSubtitle = ref("Starting session");
    const chatTitleOverride = ref("");
    let itemId = 0;
    let errorTimer = null;

    /* `streaming` is now per-session: true only when the *visible* session
       has a run in flight. Other sessions stay fully interactive. */
    const streaming = computed(() => !!(sessionId.value && activeRuns[sessionId.value]));

    /* ---------- usage ----------
       lastStepUsage = latest model-call prompt size (used context).
       lastTurnUsage = summed totals across all model calls in the turn. */
    const lastTurnUsage = ref(null);
    const lastStepUsage = ref(null);
    const usageEstimate = ref(null);

    /* ---------- running tool ---------- */
    const runningTool = ref(null);
    const runningSeconds = ref("0.0");
    let runningTimer = null;

    /* ---------- files ---------- */
    const fileTree = ref(null);
    const childrenMap = reactive({});
    const expandedFolders = reactive(new Set());
    const filesLoading = ref(false);
    const filesError = ref("");
    const workspaceOpen = ref(true);
    const workspaceCache = new Map();
    const newFolderOpen = ref(false);
    const newFolderName = ref("");
    const creatingFolder = ref(false);
    const newFolderInputEl = ref(null);

    /* ---------- pwd picker ---------- */
    const workspaceFolders = ref([""]);
    const workspaceFoldersLoaded = ref(false);
    const selectedPwd = ref("");
    const pwdCloseSignal = ref(0);
    const pwdPickerEl = ref(null);

    /* ---------- preview ---------- */
    const previewCollapsed = ref(true);
    const previewExpanded = ref(false);
    const sidebarOpen = ref(false);
    const isMobileLayout = ref(false);
    const preview = reactive({
      mode: "empty", message: "Select a workspace file to preview it here.",
      title: "Preview", subtitle: "No file selected",
      path: null, content: "", rows: [], highlighted: "", blobUrl: null,
      ready: false, blob: null, type: "",
    });

    /* ---------- DOM refs ---------- */
    const scrollEl = ref(null);
    const inputEl = ref(null);

    /* ---------- computed ---------- */
    const chatTitle = computed(() => chatTitleOverride.value || "Deep Agent");
    const chatSubtitle = computed(() =>
      session.value
        ? `Sandbox ${session.value.sandbox_id} · network ${session.value.network ? "on" : "off"}`
        : "Sandboxed workspace"
    );
    const sandboxDegraded = computed(() => !!(config.value?.sandbox_degraded));
    const sandboxStarting = computed(() => !!(config.value?.sandbox_starting));
    const sandboxDegradedReason = computed(() =>
      config.value?.sandbox_status?.degraded_reason
      || config.value?.sandbox_status?.fix_it
      || ""
    );
    const modelLabel = computed(() => {
      const m = (session.value?.model || config.value?.default_model || "").trim();
      if (!m) return "Select model";
      return modelDisplayName(m);
    });
    const selectedModelId = computed(() =>
      (session.value?.model || config.value?.default_model || "").trim()
    );
    const modelPickerGroups = computed(() => {
      const platforms = settingsConfig.platforms || [];
      return platforms
        .filter((p) => p.enabled !== false)
        .map((p) => ({
          name: p.name || p.id,
          models: (p.models || []).filter((m) => m.enabled !== false).map((m) => ({ id: m.id })),
        }))
        .filter((g) => g.models.length);
    });
    const modelPickerLoading = ref(false);
    const modelCloseSignal = ref(0);
    const modelPickerEl = ref(null);
    const username = computed(() => config.value?.username || "User");
    const userInitial = computed(() => {
      const name = username.value.trim();
      return name ? name.charAt(0).toUpperCase() : "?";
    });
    const sessionInfoRows = computed(() => {
      const s = session.value;
      if (!s) return [];
      return [
        { label: "Session", value: s.id },
        { label: "Sandbox", value: s.sandbox_id },
        { label: "Workdir", value: s.workdir },
        { label: "Model", value: s.model },
        { label: "Network", value: s.network ? "on" : "off" },
        { label: "Subagents", value: (s.subagent_names || []).join(", ") || "none" },
        { label: "Messages", value: String(s.message_count ?? timeline.value.length) },
      ];
    });
    const canSend = computed(() => !!draft.value.trim() && !streaming.value && !!sessionId.value);
    const previewWidth = computed(() => {
      if (previewCollapsed.value) return "3rem";
      if (isMobileLayout.value) return "min(100vw, 28rem)";
      return previewExpanded.value ? "min(52vw, 760px)" : "min(38vw, 520px)";
    });
    const previewBackdropVisible = computed(() =>
      isMobileLayout.value && !previewCollapsed.value
    );
    /** Latest model-call prompt size as `in`; out = cumulative turn output so far. */
    const usageText = computed(() => {
      const step = lastStepUsage.value;
      const turn = lastTurnUsage.value;
      const est = usageEstimate.value;
      if (!step && !turn?.model_calls && !(est && Number(est.estimated_output_tokens || 0))) {
        return "";
      }
      const parts = [];
      const context = Number(step?.input_tokens || 0);
      const out = Number(turn?.output_tokens || step?.output_tokens || 0);
      const estOut = Number(est?.estimated_output_tokens || 0);
      if (est && estOut) {
        parts.push(`in ${context ? context.toLocaleString() : "—"}`);
        parts.push(`out ~${(out + estOut).toLocaleString()}`);
        if (est.phase === "tool_args" && est.tool_name) {
          parts.push(`${est.tool_name} args ${Number(est.chars || 0).toLocaleString()} chars`);
        } else if (est.phase === "text") {
          parts.push("streaming");
        }
      } else if (step || turn?.model_calls) {
        parts.push(`in ${context ? context.toLocaleString() : "—"}`);
        parts.push(`out ${out.toLocaleString()}`);
        if (step?.cache_read) parts.push(`cache ${Number(step.cache_read).toLocaleString()}`);
      }
      return parts.join(" · ");
    });
    /** Summed turn metrics for the session-details popover. */
    const turnTotalsText = computed(() => {
      const turn = lastTurnUsage.value;
      if (!turn?.model_calls) return "";
      const parts = [
        `${Number(turn.total_tokens || 0).toLocaleString()} tokens`,
        `in ${Number(turn.input_tokens || 0).toLocaleString()}`,
        `out ${Number(turn.output_tokens || 0).toLocaleString()}`,
      ];
      if (turn.cache_read) parts.push(`cache ${Number(turn.cache_read).toLocaleString()}`);
      parts.push(`${turn.model_calls} model call${turn.model_calls === 1 ? "" : "s"}`);
      return parts.join(" · ");
    });

    /* ---------- small helpers ---------- */
    function isRunning(id) {
      return !!activeRuns[id];
    }

    function showError(message) {
      errorMessage.value = message || "Something went wrong";
      clearTimeout(errorTimer);
      errorTimer = setTimeout(() => (errorMessage.value = ""), 8000);
    }

    function renderMarkdown(text) {
      if (!text) return "";
      const html = marked.parse(expandPreviewTags(text));
      return DOMPurify.sanitize(html, { ADD_ATTR: ["target", "data-preview-path"] });
    }

    async function scrollToBottom() {
      await nextTick();
      const el = scrollEl.value;
      if (el) el.scrollTop = el.scrollHeight;
    }

    function pushItem(item) {
      timeline.value.push({ id: ++itemId, ...item });
      scrollToBottom();
      return timeline.value[timeline.value.length - 1];
    }

    function autoGrow() {
      const el = inputEl.value;
      if (!el) return;
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 144) + "px";
    }

    function onComposerEnter(e) {
      if (isMobileLayout.value) return;
      e.preventDefault();
      submit();
    }

    async function api(path, options = {}) {
      const res = await fetch(`${API}${path}`, {
        headers: { "Content-Type": "application/json", ...(options.headers || {}) },
        ...options,
      });
      if (res.status === 204) return null;
      if (!res.ok) {
        let detail = res.statusText;
        try {
          const body = await res.json();
          detail = typeof body.detail === "string"
            ? body.detail
            : JSON.stringify(body.detail ?? body);
        } catch {}
        throw new Error(detail);
      }
      return res.json();
    }

    /* ---------- history helpers ---------- */
    function messageContent(msg) {
      const content = msg?.data?.content ?? msg?.content ?? "";
      if (typeof content === "string") return content;
      if (Array.isArray(content)) {
        return content
          .map((b) => (typeof b === "string" ? b : b?.type === "text" ? b.text || "" : ""))
          .join("");
      }
      return String(content ?? "");
    }
    const messageRole = (msg) => msg?.type || msg?.role || msg?.data?.type || "";

    function renderHistory(messages) {
      timeline.value = [];
      for (const msg of messages) {
        const role = messageRole(msg);
        const text = messageContent(msg);
        if (!text) continue;
        if (role === "human" || role === "user") pushItem({ kind: "user", text });
        else if (role === "ai" || role === "assistant") pushItem({ kind: "assistant", text });
      }
    }

    /* ---------- running tool timer ---------- */
    function startToolTimer(name) {
      stopToolTimer();
      runningTool.value = name;
      const startedAt = Date.now();
      runningSeconds.value = "0.0";
      runningTimer = setInterval(() => {
        runningSeconds.value = ((Date.now() - startedAt) / 1000).toFixed(1);
      }, 100);
    }
    function stopToolTimer() {
      clearInterval(runningTimer);
      runningTimer = null;
      runningTool.value = null;
    }

    /* ---------- files ---------- */
    async function fetchEntries(path = "") {
      const q = path ? `?path=${encodeURIComponent(path)}` : "";
      const data = await api(`/api/sessions/${sessionId.value}/files${q}`);
      return data.entries || [];
    }

    function snapshotWorkspace(id = sessionId.value) {
      if (!id || fileTree.value === null) return;
      workspaceCache.set(id, {
        fileTree: fileTree.value,
        childrenMap: { ...childrenMap },
        expandedFolders: new Set(expandedFolders),
        workspaceFolders: workspaceFolders.value,
        workspaceFoldersLoaded: workspaceFoldersLoaded.value,
        selectedPwd: selectedPwd.value,
      });
    }

    function restoreWorkspace(id) {
      const cached = workspaceCache.get(id);
      if (!cached) {
        fileTree.value = null;
        for (const key of Object.keys(childrenMap)) delete childrenMap[key];
        expandedFolders.clear();
        workspaceFolders.value = [""];
        workspaceFoldersLoaded.value = false;
        selectedPwd.value = "";
        filesError.value = "";
        return false;
      }
      fileTree.value = cached.fileTree;
      for (const key of Object.keys(childrenMap)) delete childrenMap[key];
      Object.assign(childrenMap, cached.childrenMap);
      expandedFolders.clear();
      for (const p of cached.expandedFolders) expandedFolders.add(p);
      workspaceFolders.value = cached.workspaceFolders;
      workspaceFoldersLoaded.value = cached.workspaceFoldersLoaded && cached.workspaceFolders.length > 1;
      selectedPwd.value = cached.selectedPwd;
      filesError.value = "";
      return true;
    }

    function clearWorkspaceView() {
      fileTree.value = null;
      for (const key of Object.keys(childrenMap)) delete childrenMap[key];
      expandedFolders.clear();
      workspaceFolders.value = [""];
      workspaceFoldersLoaded.value = false;
      selectedPwd.value = "";
      filesError.value = "";
    }

    async function loadFiles({ silent = false, force = false } = {}) {
      if (!sessionId.value || filesLoading.value) return;
      if (!force && !silent && fileTree.value !== null) {
        snapshotWorkspace(sessionId.value);
        return;
      }
      const showSpinner = !silent;
      if (showSpinner) {
        filesLoading.value = true;
        if (fileTree.value === null) filesError.value = "";
      }
      try {
        fileTree.value = await fetchEntries("");
        const stillExpanded = [...expandedFolders].filter((p) => folderExists(p, fileTree.value));
        expandedFolders.clear();
        for (const p of stillExpanded) expandedFolders.add(p);
        const missingExpanded = stillExpanded.filter((p) => childrenMap[p] === undefined);
        if (missingExpanded.length) {
          await Promise.allSettled(
            missingExpanded.map(async (p) => { childrenMap[p] = await fetchEntries(p); })
          );
        }
        snapshotWorkspace(sessionId.value);
      } catch {
        if (!silent) {
          filesError.value = "Files unavailable";
          fileTree.value = [];
        }
      } finally {
        if (showSpinner) filesLoading.value = false;
      }
    }

    function folderExists(path, rootEntries) {
      const top = path.split("/")[0];
      return (rootEntries || []).some((e) => e.is_dir && (e.path === path || e.path === top));
    }

    async function toggleFolder(path) {
      if (expandedFolders.has(path)) {
        expandedFolders.delete(path);
        return;
      }
      expandedFolders.add(path);
      if (childrenMap[path] === undefined) {
        try {
          childrenMap[path] = await fetchEntries(path);
          snapshotWorkspace();
        } catch (e) {
          expandedFolders.delete(path);
          showError(e.message || "Folder unavailable");
        }
      }
    }

    async function loadWorkspaceFolders() {
      if (!sessionId.value) return;
      const previous = selectedPwd.value;
      try {
        const data = await api(`/api/sessions/${sessionId.value}/folders`);
        workspaceFolders.value = rootFoldersOnly(data.folders?.length ? data.folders : [""]);
        workspaceFoldersLoaded.value = true;
      } catch {
        workspaceFolders.value = collectFoldersFromTree();
        workspaceFoldersLoaded.value = workspaceFolders.value.length > 1;
      }
      if (!workspaceFolders.value.includes(previous)) selectedPwd.value = "";
      snapshotWorkspace();
    }

    function openNewFolder() {
      if (!sessionId.value) return;
      workspaceOpen.value = true;
      newFolderOpen.value = true;
      newFolderName.value = "";
      nextTick(() => newFolderInputEl.value?.focus());
    }

    function cancelNewFolder() {
      newFolderOpen.value = false;
      newFolderName.value = "";
    }

    async function createFolder() {
      const name = newFolderName.value.trim();
      if (!name || creatingFolder.value || !sessionId.value) return;
      creatingFolder.value = true;
      try {
        const parent = selectedPwd.value || "";
        const data = await api(`/api/sessions/${sessionId.value}/folders`, {
          method: "POST",
          body: JSON.stringify({ name, parent }),
        });
        cancelNewFolder();
        if (parent) {
          expandedFolders.add(parent);
          childrenMap[parent] = await fetchEntries(parent);
        }
        await loadFiles({ force: true });
        await loadWorkspaceFolders();
        if (data.path) expandedFolders.add(data.path);
        snapshotWorkspace();
      } catch (e) {
        showError(e.message || "Failed to create folder");
      } finally {
        creatingFolder.value = false;
      }
    }

    function collectFoldersFromTree() {
      const folders = new Set([""]);
      for (const entry of fileTree.value || []) {
        if (!entry?.is_dir) continue;
        const path = (entry.path || "").replace(/^\/+|\/+$/g, "");
        if (path && !path.includes("/")) folders.add(path);
      }
      return rootFoldersOnly([...folders]);
    }

    function closePwdMenu() {
      pwdCloseSignal.value += 1;
      pwdPickerEl.value?.close?.();
    }

    function closeModelMenu() {
      modelCloseSignal.value += 1;
      modelPickerEl.value?.close?.();
    }

    async function ensurePickerModels() {
      closePwdMenu();
      if ((settingsConfig.platforms || []).length) return;
      modelPickerLoading.value = true;
      try {
        await loadSettings();
      } catch {
        /* picker shows empty / no matches */
      } finally {
        modelPickerLoading.value = false;
      }
    }

    async function selectModel(modelId) {
      const mid = (modelId || "").trim();
      if (!mid || !sessionId.value || streaming.value) return;
      if ((session.value?.model || "") === mid) return;
      closeModelMenu();
      try {
        const updated = await api(`/api/sessions/${sessionId.value}`, {
          method: "PATCH",
          body: JSON.stringify({ model: mid }),
        });
        session.value = { ...session.value, ...updated, model: updated.model || mid };
        if (config.value) config.value.default_model = mid;
        settingsConfig.default_model = mid;
        const owner = (settingsConfig.platforms || []).find((p) =>
          (p.models || []).some((m) => m.id === mid)
        );
        if (owner) settingsConfig.active_platform_id = owner.id;
      } catch (e) {
        showError(e.message || "Failed to switch model");
      }
    }

    async function openAddModelFromPicker() {
      closeModelMenu();
      settingsPanel.value = "models";
      await openSettings();
      try {
        await loadSettings();
        const plats = (settingsConfig.platforms || []).filter((p) => p.enabled !== false);
        if (plats.length === 1) openAddModel(plats[0]);
      } catch {
        /* settings page is enough */
      }
    }

    function onPwdPickerOpen() {
      closeModelMenu();
      const fromTree = collectFoldersFromTree();
      if (fromTree.length > 1) workspaceFolders.value = fromTree;
      loadWorkspaceFolders();
    }

    function onSessionInfoClick(event) {
      event.stopPropagation();
      sessionInfoOpen.value = !sessionInfoOpen.value;
    }

    function selectPwd(folder) {
      selectedPwd.value = folder || "";
      closePwdMenu();
      snapshotWorkspace();
    }

    /* ---------- preview ---------- */
    function clearPreviewBlob() {
      if (preview.blobUrl) {
        URL.revokeObjectURL(preview.blobUrl);
        preview.blobUrl = null;
      }
      preview.blob = null;
    }

    async function loadFileBlob(path) {
      const res = await fetch(`${API}/api/sessions/${sessionId.value}/files/raw?path=${encodeURIComponent(path)}`);
      if (!res.ok) {
        let detail = res.statusText;
        try { detail = (await res.json()).detail || detail; } catch {}
        throw new Error(detail);
      }
      return res.blob();
    }

    async function previewWorkspaceFile(path) {
      if (!sessionId.value) return;
      sidebarOpen.value = false;
      previewCollapsed.value = false;
      clearPreviewBlob();
      Object.assign(preview, {
        mode: "empty", message: "Loading preview…",
        title: fileName(path), subtitle: path,
        path, content: "", rows: [], highlighted: "", ready: false, type: "",
      });

      try {
        if (isImagePath(path)) {
          const blob = await loadFileBlob(path);
          preview.blob = blob;
          preview.blobUrl = URL.createObjectURL(blob);
          preview.mode = "image";
          preview.subtitle = `${path} · ${Number(blob.size || 0).toLocaleString()} bytes`;
        } else {
          const data = await api(`/api/sessions/${sessionId.value}/files/content?path=${encodeURIComponent(path)}`);
          const mode = previewModeFor(data.path);
          preview.subtitle = `${data.path} · ${Number(data.size || 0).toLocaleString()} bytes`;
          if (mode === "html") {
            preview.content = data.content;
            preview.mode = "html";
          } else if (mode === "css") {
            preview.content = cssPreviewDocument(data.content);
            preview.mode = "html";
          } else if (mode === "markdown") {
            preview.content = data.content;
            preview.mode = "markdown";
          } else if (mode === "csv") {
            preview.rows = parseDelimited(data.content, fileExt(path) === "tsv" ? "\t" : ",");
            preview.mode = "csv";
          } else if (mode === "code") {
            const lang = codeLanguageFor(path);
            const source = lang === "json" ? prettyJson(data.content) : data.content;
            let html;
            try { html = hljs.highlight(source, { language: lang }).value; }
            catch { html = hljs.highlightAuto(source).value; }
            preview.highlighted = DOMPurify.sanitize(html);
            preview.mode = "code";
          } else {
            preview.content = data.content;
            preview.mode = "text";
          }
          preview.type = mode === "html" ? "text/html" : "text/plain";
          preview.blob = new Blob([data.content], { type: preview.type });
          preview.blobUrl = URL.createObjectURL(preview.blob);
        }
        preview.ready = true;
      } catch (e) {
        Object.assign(preview, { mode: "empty", message: e.message || "Preview unavailable", ready: false });
      }
    }

    function openPreviewInTab() {
      if (preview.blobUrl) window.open(preview.blobUrl, "_blank", "noopener,noreferrer");
    }

    async function downloadWorkspaceFile(path) {
      if (!sessionId.value || !path) return;
      try {
        let blob;
        if (preview.path === path && preview.blob) {
          blob = preview.blob;
        } else if (isImagePath(path)) {
          blob = await loadFileBlob(path);
        } else {
          const data = await api(`/api/sessions/${sessionId.value}/files/content?path=${encodeURIComponent(path)}`);
          blob = new Blob([data.content], { type: "text/plain" });
        }
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = fileName(path);
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      } catch (e) {
        showError(e.message);
      }
    }

    /* ---------- run streaming (run-based API) ----------
       POST /chat returns 202 {run_id}; the turn executes server-side as a
       background run. We attach a *pure observer* SSE reader to
       GET /runs/{run_id}/events. Closing the reader (switching sessions,
       reloading) never affects the run; only POST /runs/{id}/cancel does.
       Every event carries a monotonic `seq`, so a dropped connection
       resumes with ?after=<lastSeq>, and a full reattach replays from 0. */

    function abortRunReader() {
      if (runAbort) {
        runAbort.abort();
        runAbort = null;
      }
      turnCtx = null;
    }

    function newTurnCtx(sid, runId, { startIndex, originalMessage = null }) {
      return {
        sessionId: sid,
        runId,
        startIndex,          // timeline index of this turn's user bubble
        originalMessage,     // restored to the composer on cancellation
        prevTitle: chatTitleOverride.value,
        assistantItem: null,
        toolItem: null,
        toolName: "",
        toolArgs: "",
        lastSeq: 0,
        gotTerminal: false,
      };
    }

    /* Undo everything this turn added to the timeline and hand the original
       text back to the composer -- mirrors the server-side checkpoint
       rollback that a cancelled run performs. */
    function rollBackTurn(ctx) {
      if (timeline.value.length > ctx.startIndex) {
        timeline.value.length = ctx.startIndex;
      }
      if (ctx.originalMessage != null && !draft.value.trim()) {
        draft.value = ctx.originalMessage;
        nextTick(() => autoGrow());
      }
      chatTitleOverride.value = ctx.prevTitle;
      sidebarSubtitle.value = "Stopped — message restored";
    }

    function finishRun(ctx) {
      ctx.gotTerminal = true;
      if (activeRuns[ctx.sessionId] === ctx.runId) delete activeRuns[ctx.sessionId];
      loadSessionList().catch(() => {});
    }

    function ensureAssistant(ctx) {
      if (!ctx.assistantItem) ctx.assistantItem = pushItem({ kind: "assistant", text: "" });
      return ctx.assistantItem;
    }

    function processRunEvent(ctx, data) {
      switch (data.type) {
        case "source_start":
          thinking.value = false;
          if (data.is_subagent) {
            pushItem({ kind: "activity", icon: "subagent", name: "Sub-agent", detail: data.source });
          }
          break;

        case "token":
          thinking.value = false;
          if (!data.is_subagent && data.source === "main") {
            ensureAssistant(ctx).text += data.text || "";
            scrollToBottom();
          }
          break;

        case "tool_call_start":
          thinking.value = false;
          ctx.toolName = data.name || "tool";
          ctx.toolArgs = "";
          ctx.toolItem = pushItem({ kind: "activity", icon: "terminal", name: ctx.toolName, detail: "(…)" });
          break;

        case "tool_call_args":
          ctx.toolArgs += data.args || "";
          if (ctx.toolItem) ctx.toolItem.detail = `(${ctx.toolArgs})`;
          break;

        case "tool_call_end":
          if (ctx.toolItem) ctx.toolItem.detail = `(${ctx.toolArgs || ""})`;
          ctx.toolItem = null;
          ctx.assistantItem = null;
          break;

        case "tool_running":
          startToolTimer(data.name || ctx.toolName);
          break;

        case "tool_result": {
          thinking.value = false;
          stopToolTimer();
          usageEstimate.value = null;
          const content = data.content || "";
          const previewText = content.slice(0, 200) + (content.length > 200 ? "…" : "");
          pushItem({ kind: "activity", icon: "terminal", name: data.name, detail: `→ ${previewText}` });
          ctx.assistantItem = null;
          break;
        }

        case "usage":
          if (data.turn?.model_calls) {
            lastTurnUsage.value = data.turn;
            if (data.step) lastStepUsage.value = data.step;
            usageEstimate.value = null;
          }
          break;

        case "usage_estimate":
          if (data.turn?.model_calls) lastTurnUsage.value = data.turn;
          usageEstimate.value = data;
          break;

        case "done":
          thinking.value = false;
          stopToolTimer();
          usageEstimate.value = null;
          if (!ctx.assistantItem && data.reply) {
            pushItem({ kind: "assistant", text: data.reply });
          }
          if (data.usage?.model_calls) lastTurnUsage.value = data.usage;
          if (data.step_usage) lastStepUsage.value = data.step_usage;
          sidebarSubtitle.value = `${data.messages?.length || 0} messages`;
          if (session.value?.id === ctx.sessionId) {
            session.value.message_count = data.messages?.length || 0;
          }
          loadFiles({ silent: true, force: true }).catch(() => {});
          finishRun(ctx);
          break;

        case "cancelled":
          thinking.value = false;
          stopToolTimer();
          usageEstimate.value = null;
          rollBackTurn(ctx);
          finishRun(ctx);
          break;

        case "error":
          thinking.value = false;
          stopToolTimer();
          usageEstimate.value = null;
          showError(data.error || data.message || "Agent error");
          finishRun(ctx);
          break;
      }
    }

    /* Observe a run's event stream until its terminal event. Reconnects
       from ctx.lastSeq if the connection drops without a terminal event
       (the durable event log makes resume exact -- no duplicates, no gaps).
       Returns when the run ends or the reader is aborted (session switch). */
    async function attachRun(ctx) {
      let attempts = 0;
      while (!ctx.gotTerminal && attempts < 30) {
        attempts += 1;
        runAbort = new AbortController();
        try {
          const res = await fetch(
            `${API}/api/sessions/${ctx.sessionId}/runs/${ctx.runId}/events?after=${ctx.lastSeq}`,
            { signal: runAbort.signal }
          );
          if (!res.ok || !res.body) throw new Error(`Stream failed (${res.status})`);
          const reader = res.body.getReader();
          const decoder = new TextDecoder();
          const feed = createSseParser();
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            for (const { data } of feed(decoder.decode(value, { stream: true }))) {
              if (typeof data.seq === "number") ctx.lastSeq = Math.max(ctx.lastSeq, data.seq);
              processRunEvent(ctx, data);
              attempts = 0; // healthy stream: reset the retry budget
              if (ctx.gotTerminal) return;
            }
          }
        } catch (e) {
          if (e.name === "AbortError") return; // switched away / page teardown
        }
        if (ctx.gotTerminal) return;
        // Dropped without a terminal event -- back off, then resume from lastSeq.
        await new Promise((r) => setTimeout(r, Math.min(500 * attempts, 5000)));
      }
      if (!ctx.gotTerminal) {
        showError("Lost connection to the run stream. Reload or reopen this chat to reattach.");
      }
    }

    /* Attach the visible UI to an already-running turn (page reload or
       switching back to a session whose run is still going). History is
       trimmed to end at the run's triggering user message -- everything
       after it is this run's partial output, which the seq-0 replay
       reconstructs exactly. */
    function reattachToRun(sid, runId, messages) {
      let lastHuman = -1;
      for (let i = messages.length - 1; i >= 0; i--) {
        if (["human", "user"].includes(messageRole(messages[i]))) { lastHuman = i; break; }
      }
      renderHistory(lastHuman >= 0 ? messages.slice(0, lastHuman + 1) : messages);

      const hasUserBubble = lastHuman >= 0 && timeline.value.length > 0;
      const ctx = newTurnCtx(sid, runId, {
        startIndex: hasUserBubble ? timeline.value.length - 1 : timeline.value.length,
        originalMessage: lastHuman >= 0 ? messageContent(messages[lastHuman]) : null,
      });
      activeRuns[sid] = runId;
      sidebarSubtitle.value = "Running…";
      thinking.value = true;
      turnCtx = ctx;
      attachRun(ctx).finally(() => {
        if (turnCtx === ctx) turnCtx = null;
        if (sessionId.value === sid) {
          thinking.value = false;
          stopToolTimer();
        }
      });
    }

    /* Stop = explicit server-side cancel. We do NOT abort the reader here:
       the `cancelled` event arrives through the stream, triggers the UI
       rollback, and closes the reader -- keeping client and checkpoint
       rollback in lockstep. */
    async function stopStream() {
      const sid = sessionId.value;
      const rid = sid && activeRuns[sid];
      if (!rid) return;
      try {
        await api(`/api/sessions/${sid}/runs/${rid}/cancel`, { method: "POST" });
      } catch (e) {
        // Server unreachable or run unknown: tear down locally.
        if (turnCtx && turnCtx.runId === rid) rollBackTurn(turnCtx);
        delete activeRuns[sid];
        abortRunReader();
        thinking.value = false;
        stopToolTimer();
        showError(e.message || "Failed to cancel the run");
      }
    }

    async function submit() {
      const text = draft.value.trim();
      if (!text || streaming.value || !sessionId.value) return;
      const sid = sessionId.value;
      draft.value = "";
      await nextTick();
      autoGrow();
      closePwdMenu();
      sessionInfoOpen.value = false;
      lastTurnUsage.value = null;
      lastStepUsage.value = null;
      usageEstimate.value = null;

      const ctx = newTurnCtx(sid, null, {
        startIndex: timeline.value.length,
        originalMessage: text,
      });
      pushItem({ kind: "user", text });
      chatTitleOverride.value = truncate(text);
      sidebarSubtitle.value = session.value?.agent_ready === false
        ? "Preparing agent…"
        : "Running…";
      thinking.value = true;

      // Start the turn as a background run (202 { run_id }).
      // First Send hydrates the agent + MCP on the server if needed.
      let res;
      try {
        res = await fetch(`${API}/api/sessions/${sid}/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: text, pwd: selectedPwd.value || null }),
        });
      } catch (e) {
        thinking.value = false;
        rollBackTurn(ctx);
        showError(e.message || "Request failed");
        return;
      }

      if (res.ok && session.value) {
        session.value.agent_ready = true;
      }
      if (res.ok) {
        sidebarSubtitle.value = "Running…";
      }

      if (res.status === 409) {
        // A run is already in flight for this session (e.g. started in
        // another tab). Restore the composer and reattach to it.
        thinking.value = false;
        rollBackTurn(ctx);
        let activeId = null;
        try { activeId = (await res.json())?.detail?.active_run_id || null; } catch {}
        if (activeId && sessionId.value === sid) {
          try {
            const { messages } = await api(`/api/sessions/${sid}/messages`);
            reattachToRun(sid, activeId, messages);
          } catch {}
        }
        showError("A run is already in flight for this chat — reattached to it.");
        return;
      }

      if (!res.ok) {
        thinking.value = false;
        rollBackTurn(ctx);
        let detail = res.statusText;
        try {
          const body = await res.json();
          detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
        } catch {}
        showError(detail || "Request failed");
        return;
      }

      const created = await res.json();
      ctx.runId = created.run_id;
      activeRuns[sid] = created.run_id;
      turnCtx = ctx;
      try {
        await attachRun(ctx);
      } finally {
        if (turnCtx === ctx) turnCtx = null;
        if (sessionId.value === sid) {
          thinking.value = false;
          stopToolTimer();
          nextTick(() => inputEl.value?.focus());
        }
      }
    }

    /* ---------- session lifecycle ---------- */
    function resetChatUi() {
      timeline.value = [];
      itemId = 0;
      lastTurnUsage.value = null;
      lastStepUsage.value = null;
      usageEstimate.value = null;
      thinking.value = false;
      stopToolTimer();
      clearPreviewBlob();
      previewCollapsed.value = true;
      Object.assign(preview, {
        mode: "empty",
        message: "Select a workspace file to preview it here.",
        title: "Preview",
        subtitle: "No file selected",
        path: null,
        content: "",
        rows: [],
        highlighted: "",
        ready: false,
        type: "",
      });
    }

    async function loadSessionList() {
      sessionListLoading.value = true;
      try {
        const data = await api("/api/sessions");
        sessionList.value = data.sessions || [];
        // Sync the active-run map from the server (it is the source of truth
        // for runs started in other tabs or before a reload).
        for (const s of sessionList.value) {
          if (s.active_run_id) activeRuns[s.id] = s.active_run_id;
          else if (!(turnCtx && turnCtx.sessionId === s.id)) delete activeRuns[s.id];
        }
      } catch {
        sessionList.value = [];
      } finally {
        sessionListLoading.value = false;
      }
    }

    function applyPersistedUsage(s) {
      lastTurnUsage.value = s?.last_usage?.model_calls ? s.last_usage : null;
      lastStepUsage.value = s?.last_step_usage || null;
    }

    async function loadSessionState(id) {
      if (sessionId.value && sessionId.value !== id) snapshotWorkspace(sessionId.value);
      // Detach the observer from whatever we were watching. The server-side
      // run (if any) keeps executing; we reattach when we come back.
      abortRunReader();

      session.value = await api(`/api/sessions/${id}`);
      sessionId.value = id;
      sessionStorage.setItem(SESSION_KEY, id);
      const { messages } = await api(`/api/sessions/${id}/messages`);
      resetChatUi();
      applyPersistedUsage(session.value);
      const hadCache = restoreWorkspace(id);

      const runId = session.value.active_run_id || activeRuns[id] || null;
      if (runId) {
        reattachToRun(id, runId, messages);
      } else {
        delete activeRuns[id];
        renderHistory(messages);
      }

      const firstUser = messages.find((m) => ["human", "user"].includes(messageRole(m)));
      chatTitleOverride.value = firstUser ? truncate(messageContent(firstUser)) : "New chat";
      sidebarSubtitle.value = runId
        ? "Running…"
        : messages.length ? `${messages.length} messages` : "Ready";
      if (hadCache) {
        loadFiles({ silent: true, force: true }).catch(() => {});
      } else {
        loadFiles({ force: true }).catch(() => {});
      }
      loadWorkspaceFolders().catch(() => {});
    }

    async function switchSession(id) {
      if (!id || id === sessionId.value) return;
      sessionInfoOpen.value = false;
      sidebarOpen.value = false;
      try {
        await loadSessionState(id);
      } catch (e) {
        showError(e.message || "Chat unavailable");
        await loadSessionList();
      }
    }

    async function deleteSession(id) {
      if (!id) return;
      const running = isRunning(id);
      const prompt = running
        ? "This chat has a run in progress. Deleting it cancels the run and removes its sandbox workspace. Continue?"
        : "Delete this chat and its sandbox workspace?";
      if (!confirm(prompt)) return;
      if (id === sessionId.value) abortRunReader();
      try {
        await api(`/api/sessions/${id}`, { method: "DELETE" });
      } catch (e) {
        showError(e.message || "Failed to delete chat");
        return;
      }
      delete activeRuns[id];
      workspaceCache.delete(id);
      if (id === sessionId.value) {
        sessionStorage.removeItem(SESSION_KEY);
        sessionId.value = null;
        session.value = null;
        resetChatUi();
        const remaining = sessionList.value.filter((s) => s.id !== id);
        if (remaining.length) {
          try {
            await loadSessionState(remaining[0].id);
          } catch {
            await createSession();
            chatTitleOverride.value = "New chat";
            sidebarSubtitle.value = "Ready";
          }
        } else {
          await createSession();
          chatTitleOverride.value = "New chat";
          sidebarSubtitle.value = "Ready";
        }
      }
      await loadSessionList();
    }

    async function createSession() {
      if (sessionId.value) snapshotWorkspace(sessionId.value);
      abortRunReader();
      const preferred =
        (session.value?.model || config.value?.default_model || "").trim() || undefined;
      session.value = await api("/api/sessions", {
        method: "POST",
        body: JSON.stringify(preferred ? { model: preferred } : {}),
      });
      sessionId.value = session.value.id;
      sessionStorage.setItem(SESSION_KEY, sessionId.value);
      resetChatUi();
      clearWorkspaceView();
      fileTree.value = [];
      snapshotWorkspace(sessionId.value);
      loadFiles({ force: true }).catch(() => {});
      loadSessionList().catch(() => {});
      loadWorkspaceFolders().catch(() => {});
    }

    function syncRouteFromHash() {
      const hash = (location.hash || "").replace(/^#\/?/, "").toLowerCase();
      route.value = hash === "settings" ? "settings" : "chat";
      if (route.value === "settings") loadSettings().catch(() => {});
    }

    async function openSettings() {
      location.hash = "settings";
      syncRouteFromHash();
    }

    function closeSettings() {
      location.hash = "";
      syncRouteFromHash();
    }

    function settingsToast(msg) {
      toastMsg.value = msg;
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => { toastMsg.value = ""; }, 2200);
    }

    function tauriInvoke(cmd, args) {
      const invoke = window.__TAURI__?.core?.invoke;
      if (typeof invoke !== "function") {
        return Promise.reject(new Error("not-tauri"));
      }
      return invoke(cmd, args);
    }

    function isTauriShell() {
      return typeof window.__TAURI__?.core?.invoke === "function";
    }

    function showUpdateDialog(version) {
      if (!version) return;
      pendingUpdateVersion.value = String(version);
      modal.value = "app-update";
    }

    function closeUpdateModal() {
      if (updateInstalling.value) return;
      if (modal.value === "app-update") modal.value = "";
    }

    async function loadAppVersion() {
      if (!isTauriShell()) return;
      try {
        const v = await tauriInvoke("get_app_version");
        if (v) appVersion.value = String(v);
      } catch {
        /* keep fallback */
      }
    }

    async function checkForUpdates(manual) {
      if (!isTauriShell()) {
        if (manual) settingsToast("Update check is only available in the desktop app");
        return;
      }
      updateChecking.value = true;
      try {
        const info = await tauriInvoke("updater_check");
        if (info && info.available && info.version) {
          showUpdateDialog(info.version);
        } else if (manual) {
          settingsToast("You're up to date");
        }
      } catch (e) {
        if (manual) settingsToast(e?.message || "Update check failed");
      } finally {
        updateChecking.value = false;
      }
    }

    async function snoozeUpdate() {
      const version = pendingUpdateVersion.value;
      try {
        if (version) await tauriInvoke("updater_snooze", { version });
      } catch (e) {
        settingsToast(e?.message || "Could not snooze update");
        return;
      }
      modal.value = "";
      settingsToast("Remind me in 7 days");
    }

    async function installUpdate() {
      if (!isTauriShell()) return;
      updateInstalling.value = true;
      try {
        await tauriInvoke("updater_install");
        // App should restart; if we return, install finished without relaunch.
        settingsToast("Update installed — restarting…");
      } catch (e) {
        updateInstalling.value = false;
        settingsToast(e?.message || "Update failed");
      }
    }

    async function bindUpdateEvents() {
      const listen = window.__TAURI__?.event?.listen;
      if (typeof listen !== "function") return;
      try {
        updateEventUnlisten = await listen("update-available", (event) => {
          const payload = event?.payload || {};
          if (payload.version) showUpdateDialog(payload.version);
        });
      } catch {
        /* ignore */
      }
    }

    function closeModal() {
      modal.value = "";
    }

    function applySettingsPayload(data) {
      const cfg = data.config || {};
      settingsMeta.data_dir = data.data_dir || "";
      settingsMeta.workdir = data.workdir || "";
      settingsMeta.env_path = data.env_path || "";
      settingsMeta.settings_path = data.settings_path || data.env_path || "";
      settingsMeta.values = data.values || {};
      settingsConfig.platforms = Array.isArray(cfg.platforms) ? cfg.platforms.map((p) => ({
        ...p,
        models: (p.models || []).map((m) => ({
          id: m.id,
          enabled: m.enabled !== false,
          temperature: m.temperature != null ? Number(m.temperature) : 0.3,
        })),
      })) : [];
      settingsConfig.default_model = cfg.default_model || "";
      settingsConfig.active_platform_id = cfg.active_platform_id || "";
      settingsConfig.temperature = cfg.temperature != null ? Number(cfg.temperature) : 0.3;
      const sb = cfg.sandbox || {};
      sandboxForm.network = !!sb.network;
      sandboxForm.memory_mib = sb.memory_mib ?? 2048;
      sandboxForm.cpus = sb.cpus ?? 2;
      sandboxForm.dns_nameservers = sb.dns_nameservers ?? "1.1.1.1,8.8.8.8";
      sandboxForm.exec_timeout = sb.exec_timeout ?? 120;
      sandboxForm.idle_timeout = sb.idle_timeout ?? 600;
    }

    async function putSettingsConfig(config, { setupComplete } = {}) {
      const body = { config };
      if (setupComplete != null) body.setup_complete = setupComplete;
      const res = await fetch(`${API}/api/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        let detail = res.statusText;
        try { detail = (await res.json()).detail || detail; } catch {}
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      }
      const data = await res.json();
      applySettingsPayload(data);
      return data;
    }

    function platformsPayload(extraPlatformApiKeys = {}) {
      return settingsConfig.platforms.map((p) => {
        const out = {
          id: p.id,
          name: p.name,
          kind: p.kind,
          base_url: p.base_url || "",
          enabled: p.enabled !== false,
          site_url: p.site_url || "",
          site_name: p.site_name || "",
          models: (p.models || []).map((m) => ({
            id: m.id,
            enabled: m.enabled !== false,
            temperature: m.temperature != null ? Number(m.temperature) : 0.3,
          })),
        };
        if (extraPlatformApiKeys[p.id]) out.api_key = extraPlatformApiKeys[p.id];
        return out;
      });
    }

    async function persistPlatforms(extraKeys = {}, extra = {}) {
      settingsSaving.value = true;
      settingsMessage.value = "";
      settingsError.value = false;
      try {
        const data = await putSettingsConfig({
          platforms: platformsPayload(extraKeys),
          default_model: settingsConfig.default_model,
          active_platform_id: settingsConfig.active_platform_id,
          sandbox: {
            network: !!sandboxForm.network,
            memory_mib: sandboxForm.memory_mib,
            cpus: sandboxForm.cpus,
            dns_nameservers: sandboxForm.dns_nameservers,
            exec_timeout: sandboxForm.exec_timeout,
            idle_timeout: sandboxForm.idle_timeout,
          },
          ...extra,
        });
        if (data.sandbox_recreated) {
          settingsMessage.value = "Saved. Sandbox recreated with the new network/resource settings.";
        }
        config.value = await api("/api/config");
        return data;
      } catch (e) {
        settingsError.value = true;
        settingsMessage.value = e.message || "Failed to save settings";
        throw e;
      } finally {
        settingsSaving.value = false;
      }
    }

    async function loadSettings() {
      const data = await api("/api/settings");
      applySettingsPayload(data);
      settingsMessage.value = "";
      settingsError.value = false;
    }

    function onSetupProviderChange() {
      setupCatalog.value = [];
      setupCatalogError.value = "";
      if (setupForm.kind === "ollama") {
        setupForm.model = setupForm.model || "gemma4";
        setupForm.baseUrl = setupForm.baseUrl || "http://127.0.0.1:11434/v1";
      }
    }

    async function loadSetupCatalog() {
      setupCatalogLoading.value = true;
      setupCatalogError.value = "";
      try {
        const kind = setupForm.kind || "openrouter";
        if (kind !== "ollama" && !(setupForm.apiKey || "").trim()) {
          throw new Error("Enter an API key first");
        }
        if (kind === "custom" && !(setupForm.baseUrl || "").trim()) {
          throw new Error("Enter a base URL first");
        }
        await putSettingsConfig({
          platform: {
            id: kind,
            kind,
            name: kind === "openrouter" ? "OpenRouter" : kind === "ollama" ? "Ollama" : "Custom",
            base_url: kind === "openrouter" ? "" : (setupForm.baseUrl || "").trim(),
            api_key: (setupForm.apiKey || "").trim(),
          },
          default_model: (setupForm.model || "").trim() || undefined,
        });
        const data = await api(`/api/platforms/${encodeURIComponent(kind)}/models/available`);
        setupCatalog.value = data.models || [];
        if (!setupCatalog.value.length) setupCatalogError.value = "No models returned";
      } catch (e) {
        setupCatalogError.value = e.message || "Failed to list models";
        setupCatalog.value = [];
      } finally {
        setupCatalogLoading.value = false;
      }
    }

    async function finishSetup() {
      setupSaving.value = true;
      setupError.value = "";
      try {
        const kind = setupForm.kind || "openrouter";
        const model = (setupForm.model || "").trim();
        if (!model) throw new Error("Model is required");
        if (kind !== "ollama" && !(setupForm.apiKey || "").trim()) {
          throw new Error("API key is required");
        }
        if (kind === "custom" && !(setupForm.baseUrl || "").trim()) {
          throw new Error("Base URL is required for a custom provider");
        }
        await putSettingsConfig(
          {
            setup_complete: true,
            default_model: model,
            platform: {
              id: kind,
              kind,
              name: kind === "openrouter" ? "OpenRouter" : kind === "ollama" ? "Ollama" : "Custom",
              base_url: kind === "openrouter" ? "" : (setupForm.baseUrl || "").trim(),
              api_key: (setupForm.apiKey || "").trim(),
            },
          },
          { setupComplete: true },
        );
        config.value = await api("/api/config");
        setupRequired.value = !!config.value.setup_required;
        if (!setupRequired.value) {
          await ensureSession();
        }
      } catch (e) {
        setupError.value = e.message || "Setup failed";
      } finally {
        setupSaving.value = false;
      }
    }

    function togglePlatformCollapsed(id) {
      collapsedPlatforms[id] = !collapsedPlatforms[id];
    }

    async function togglePlatformEnabled(plat, enabled) {
      plat.enabled = enabled;
      try {
        await persistPlatforms();
        settingsToast(enabled ? "Platform enabled" : "Platform disabled");
      } catch {}
    }

    async function setDefaultModel(plat, mod) {
      if (plat.enabled === false) {
        settingsToast("Enable the platform first");
        return;
      }
      settingsConfig.default_model = mod.id;
      settingsConfig.active_platform_id = plat.id;
      try {
        await persistPlatforms();
        settingsToast(`Default: ${mod.id}`);
      } catch {}
    }

    async function toggleModelEnabled(plat, mod, enabled) {
      mod.enabled = enabled;
      try {
        await persistPlatforms();
      } catch {}
    }

    async function removeModel(plat, mod) {
      if (settingsConfig.default_model === mod.id) {
        settingsToast("Pick another default before removing this model");
        return;
      }
      plat.models = (plat.models || []).filter((m) => m.id !== mod.id);
      try {
        await persistPlatforms();
        settingsToast("Model removed");
      } catch {}
    }

    async function removePlatform(plat) {
      if (settingsConfig.platforms.length <= 1) {
        settingsToast("Keep at least one platform");
        return;
      }
      if (settingsConfig.active_platform_id === plat.id || settingsConfig.default_model &&
          (plat.models || []).some((m) => m.id === settingsConfig.default_model)) {
        settingsToast("Switch default model off this platform first");
        return;
      }
      settingsConfig.platforms = settingsConfig.platforms.filter((p) => p.id !== plat.id);
      try {
        await persistPlatforms();
        settingsToast("Platform removed");
      } catch {}
    }

    function openAddPlatform(kind) {
      platformDraft.isNew = true;
      platformDraft.id = kind === "custom" ? `custom-${Date.now().toString(36)}` : kind;
      platformDraft.kind = kind;
      platformDraft.name = kind === "openrouter" ? "OpenRouter" : kind === "ollama" ? "Ollama" : "Custom";
      platformDraft.base_url = kind === "ollama" ? "http://127.0.0.1:11434/v1" : "";
      platformDraft.api_key = "";
      platformDraft.api_key_set = false;
      platformDraft.site_url = kind === "openrouter" ? "http://localhost" : "";
      platformDraft.site_name = kind === "openrouter" ? "deep-agent" : "";
      platformDraft.enabled = true;
      modal.value = "edit-platform";
    }

    function openEditPlatform(plat) {
      platformDraft.isNew = false;
      platformDraft.id = plat.id;
      platformDraft.kind = plat.kind;
      platformDraft.name = plat.name || plat.id;
      platformDraft.base_url = plat.base_url || "";
      platformDraft.api_key = "";
      platformDraft.api_key_set = !!plat.api_key_set;
      platformDraft.site_url = plat.site_url || "";
      platformDraft.site_name = plat.site_name || "";
      platformDraft.enabled = plat.enabled !== false;
      modal.value = "edit-platform";
    }

    async function savePlatformDraft() {
      const kind = platformDraft.kind;
      if (kind !== "ollama" && !(platformDraft.api_key || "").trim() && !platformDraft.api_key_set) {
        settingsToast("API key is required");
        return;
      }
      if (kind === "custom" && !(platformDraft.base_url || "").trim()) {
        settingsToast("Base URL is required");
        return;
      }
      let plat = settingsConfig.platforms.find((p) => p.id === platformDraft.id);
      if (!plat) {
        plat = {
          id: platformDraft.id,
          name: platformDraft.name,
          kind,
          base_url: platformDraft.base_url,
          enabled: true,
          site_url: platformDraft.site_url,
          site_name: platformDraft.site_name,
          models: [],
          api_key_set: false,
        };
        settingsConfig.platforms.push(plat);
      } else {
        plat.name = platformDraft.name;
        plat.base_url = platformDraft.base_url;
        plat.site_url = platformDraft.site_url;
        plat.site_name = platformDraft.site_name;
        plat.enabled = platformDraft.enabled;
      }
      const keys = {};
      if ((platformDraft.api_key || "").trim()) keys[plat.id] = platformDraft.api_key.trim();
      try {
        await persistPlatforms(keys);
        closeModal();
        settingsToast("Platform saved");
      } catch {}
    }

    function openAddModel(plat) {
      addModelPlatformId.value = plat.id;
      modelSearch.value = "";
      selectedCatalogIds.value = [];
      catalogModels.value = [];
      catalogError.value = "";
      modal.value = "add-model";
      loadCatalogForAdd();
    }

    async function loadCatalogForAdd() {
      const pid = addModelPlatformId.value;
      if (!pid) return;
      catalogLoading.value = true;
      catalogError.value = "";
      try {
        const q = encodeURIComponent(modelSearch.value || "");
        const data = await api(`/api/platforms/${encodeURIComponent(pid)}/models/available?q=${q}`);
        catalogModels.value = data.models || [];
      } catch (e) {
        catalogError.value = e.message || "Catalog unavailable";
        catalogModels.value = [];
      } finally {
        catalogLoading.value = false;
      }
    }

    async function confirmAddModels() {
      const plat = settingsConfig.platforms.find((p) => p.id === addModelPlatformId.value);
      if (!plat) return;
      const existing = new Set((plat.models || []).map((m) => m.id));
      const toAdd = [...selectedCatalogIds.value];
      const custom = (modelSearch.value || "").trim();
      if (custom && !toAdd.includes(custom) && !existing.has(custom)) toAdd.push(custom);
      for (const id of toAdd) {
        if (!existing.has(id)) {
          plat.models = plat.models || [];
          plat.models.push({ id, enabled: true, temperature: 0.3 });
          existing.add(id);
        }
      }
      if (!toAdd.length) {
        settingsToast("Nothing selected");
        return;
      }
      try {
        await persistPlatforms();
        closeModal();
        settingsToast(`Added ${toAdd.length} model${toAdd.length > 1 ? "s" : ""}`);
      } catch {}
    }

    function openModelSettings(plat, mod) {
      modelDraft.platformId = plat.id;
      modelDraft.id = mod.id;
      modelDraft.temperature = mod.temperature != null ? Number(mod.temperature) : 0.3;
      modal.value = "model-settings";
    }

    async function setDefaultModelFromDraft() {
      const plat = settingsConfig.platforms.find((p) => p.id === modelDraft.platformId);
      const mod = plat?.models?.find((m) => m.id === modelDraft.id);
      if (plat && mod) await setDefaultModel(plat, mod);
    }

    async function saveModelDraft() {
      const plat = settingsConfig.platforms.find((p) => p.id === modelDraft.platformId);
      const mod = plat?.models?.find((m) => m.id === modelDraft.id);
      if (!mod) return;
      mod.temperature = Number(modelDraft.temperature);
      try {
        await persistPlatforms();
        closeModal();
        settingsToast("Model settings saved");
      } catch {}
    }

    async function testModel(plat, mod) {
      settingsToast("Testing…");
      try {
        const res = await fetch(`${API}/api/platforms/${encodeURIComponent(plat.id)}/models/test`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model: mod.id }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || res.statusText);
        if (data.ok) settingsToast(`OK · ${data.latency_ms}ms`);
        else settingsToast(data.error || "Test failed");
      } catch (e) {
        settingsToast(e.message || "Test failed");
      }
    }

    async function saveSandbox() {
      try {
        const data = await persistPlatforms();
        settingsMessage.value = data.sandbox_recreated
          ? "Saved. Sandbox recreated with the new network/resource settings."
          : "Sandbox settings saved.";
        settingsToast(settingsMessage.value);
      } catch {}
    }

    function mcpHasAuth(entry) {
      return !!(entry.bearer_token || (entry.headers && Object.keys(entry.headers).length));
    }

    async function loadMcp() {
      const data = await api("/api/mcp");
      mcpMeta.path = data.path || "";
      Object.keys(mcpServers).forEach((k) => delete mcpServers[k]);
      Object.assign(mcpServers, data.servers || {});
    }

    async function putMcpServers(servers, { merge = false } = {}) {
      const res = await fetch(`${API}/api/mcp`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ servers, merge }),
      });
      if (!res.ok) {
        let detail = res.statusText;
        try { detail = (await res.json()).detail || detail; } catch {}
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      }
      const data = await res.json();
      mcpMeta.path = data.path || "";
      Object.keys(mcpServers).forEach((k) => delete mcpServers[k]);
      Object.assign(mcpServers, data.servers || {});
      return data;
    }

    function openAddMcp() {
      Object.assign(mcpDraft, {
        isNew: true, name: "", transport: "stdio", command: "", args: "",
        url: "", bearer_token: "",
      });
      modal.value = "mcp";
    }

    function openEditMcp(name, entry) {
      const isStdio = !!entry.command;
      Object.assign(mcpDraft, {
        isNew: false,
        name,
        transport: isStdio ? "stdio" : (entry.type || entry.transport || "http"),
        command: entry.command || "",
        args: Array.isArray(entry.args) ? entry.args.join(" ") : (entry.args || ""),
        url: entry.url || "",
        bearer_token: entry.bearer_token || "",
      });
      modal.value = "mcp";
    }

    async function saveMcpDraft() {
      const name = (mcpDraft.name || "").trim();
      if (!name) { settingsToast("Name is required"); return; }
      const entry = {};
      if (mcpDraft.transport === "stdio") {
        if (!(mcpDraft.command || "").trim()) { settingsToast("Command is required"); return; }
        entry.command = mcpDraft.command.trim();
        const args = (mcpDraft.args || "").trim();
        if (args) entry.args = args.split(/\s+/);
      } else {
        if (!(mcpDraft.url || "").trim()) { settingsToast("URL is required"); return; }
        entry.url = mcpDraft.url.trim();
        entry.type = mcpDraft.transport;
        if ((mcpDraft.bearer_token || "").trim()) entry.bearer_token = mcpDraft.bearer_token.trim();
      }
      try {
        await putMcpServers({ [name]: entry }, { merge: true });
        closeModal();
        settingsToast(`Saved MCP “${name}”`);
      } catch (e) {
        settingsToast(e.message || "Failed to save MCP");
      }
    }

    async function removeMcp(name) {
      const next = { ...mcpServers };
      delete next[name];
      try {
        await putMcpServers(next, { merge: false });
        delete mcpStatus[name];
        settingsToast(`Removed ${name}`);
      } catch (e) {
        settingsToast(e.message || "Failed to remove");
      }
    }

    async function testMcp(name) {
      settingsToast(`Testing ${name}…`);
      try {
        const data = await api(`/api/mcp/${encodeURIComponent(name)}/test`, { method: "POST" });
        mcpStatus[name] = data.ok ? "ok" : "err";
        settingsToast(data.ok ? `OK · ${data.tool_count} tools` : (data.error || "Failed"));
      } catch (e) {
        mcpStatus[name] = "err";
        settingsToast(e.message || "Test failed");
      }
    }

    function openImportMcp() {
      mcpImportError.value = "";
      modal.value = "import-mcp";
    }

    async function confirmImportMcp() {
      mcpImportError.value = "";
      let data;
      try {
        data = JSON.parse(mcpImportJson.value);
      } catch (err) {
        mcpImportError.value = "Invalid JSON: " + err.message;
        return;
      }
      const servers = data && data.mcpServers;
      if (!servers || typeof servers !== "object" || Array.isArray(servers)) {
        mcpImportError.value = 'Expected a top-level "mcpServers" object.';
        return;
      }
      try {
        await putMcpServers(servers, { merge: true });
        closeModal();
        settingsToast(`Imported ${Object.keys(servers).length} server(s)`);
      } catch (e) {
        mcpImportError.value = e.message || "Import failed";
      }
    }

    async function retrySandbox() {
      sandboxRetrying.value = true;
      try {
        const status = await api("/api/sandbox/retry", { method: "POST" });
        config.value = await api("/api/config");
        if (status?.healthy) {
          errorMessage.value = "";
          sidebarSubtitle.value = "Sandbox ready — start a new chat for full tools";
        } else {
          showError(status?.degraded_reason || "Sandbox still unavailable");
        }
      } catch (e) {
        showError(e.message || "Retry failed");
      } finally {
        sandboxRetrying.value = false;
      }
    }

    async function pollSandboxUntilSettled() {
      for (let i = 0; i < 120; i++) {
        if (!config.value?.sandbox_starting) return;
        await new Promise((r) => setTimeout(r, 1000));
        try {
          config.value = await api("/api/config");
        } catch {
          return;
        }
      }
    }

    async function ensureSession() {
      sidebarSubtitle.value = "Starting session";
      const [cfg] = await Promise.all([
        api("/api/config"),
        loadSessionList(),
      ]);
      config.value = cfg;
      setupRequired.value = !!cfg.setup_required;
      if (setupRequired.value) {
        setupForm.kind = cfg.llm_provider || "openrouter";
        setupForm.model = cfg.default_model || setupForm.model;
        sidebarSubtitle.value = "Finish setup";
        return;
      }
      pollSandboxUntilSettled().catch(() => {});
      loadSettings().catch(() => {});

      const saved = sessionStorage.getItem(SESSION_KEY);
      if (saved && sessionList.value.some((s) => s.id === saved)) {
        try {
          await loadSessionState(saved);
          return;
        } catch {
          sessionStorage.removeItem(SESSION_KEY);
        }
      }
      if (sessionList.value.length) {
        try {
          await loadSessionState(sessionList.value[0].id);
          return;
        } catch {
          sessionList.value = [];
        }
      }
      await createSession();
      chatTitleOverride.value = "New chat";
      sidebarSubtitle.value = "Ready";
    }

    async function newChat() {
      sessionInfoOpen.value = false;
      sidebarOpen.value = false;
      try {
        await createSession();
        chatTitleOverride.value = "New chat";
        sidebarSubtitle.value = "Ready";
      } catch (e) {
        showError(e.message);
      }
    }

    /* ---------- global listeners ---------- */
    function onPwdPickerCapture(e) {
      const target = e.target;
      const trigger = target.closest("[data-pwd-picker-trigger]");
      if (trigger && !trigger.disabled && pwdPickerEl.value) {
        e.stopPropagation();
        pwdPickerEl.value.toggle();
        if (pwdPickerEl.value.menuOpen) onPwdPickerOpen();
        return;
      }
      const option = target.closest("[data-pwd-option]");
      if (option) {
        e.stopPropagation();
        selectPwd(option.dataset.folder || "");
      }
    }

    function onDocClick(e) {
      const target = e.target;
      const previewBtn = target.closest("[data-preview-path]");
      if (previewBtn && scrollEl.value?.contains(previewBtn)) {
        const path = previewBtn.dataset.previewPath;
        if (path) previewWorkspaceFile(path);
        return;
      }
      if (sessionInfoOpen.value && sessionInfoEl.value && !sessionInfoEl.value.contains(target)) {
        sessionInfoOpen.value = false;
      }
    }
    function onKeydown(e) {
      if (e.key === "Escape") {
        if (modal.value) {
          closeModal();
          return;
        }
        closePwdMenu();
        sessionInfoOpen.value = false;
        sidebarOpen.value = false;
        if (isMobileLayout.value) previewCollapsed.value = true;
      }
    }

    function updateLayoutMode() {
      isMobileLayout.value = window.matchMedia("(max-width: 1023px)").matches;
      if (!isMobileLayout.value) sidebarOpen.value = false;
    }

    onMounted(() => {
      updateLayoutMode();
      syncRouteFromHash();
      window.addEventListener("resize", updateLayoutMode);
      window.addEventListener("hashchange", syncRouteFromHash);
      document.addEventListener("click", onPwdPickerCapture, true);
      document.addEventListener("click", onDocClick);
      document.addEventListener("keydown", onKeydown);
      loadAppVersion();
      bindUpdateEvents();
      ensureSession().catch((e) => {
        showError(e.message || "Failed to connect to API");
        sidebarSubtitle.value = "Start API on port 8010";
      });
    });

    onBeforeUnmount(() => {
      window.removeEventListener("resize", updateLayoutMode);
      window.removeEventListener("hashchange", syncRouteFromHash);
      document.removeEventListener("click", onPwdPickerCapture, true);
      document.removeEventListener("click", onDocClick);
      document.removeEventListener("keydown", onKeydown);
      stopToolTimer();
      clearPreviewBlob();
      if (typeof updateEventUnlisten === "function") {
        try { updateEventUnlisten(); } catch {}
        updateEventUnlisten = null;
      }
      // Detach the observer only -- the server-side run keeps going.
      abortRunReader();
    });

    return {
      iconBtn: ICON_BTN,
      // session / chrome
      session, sessionId, sessionList, sessionListLoading, chatTitle, chatSubtitle, modelLabel, sidebarSubtitle,
      selectedModelId, modelPickerGroups, modelPickerLoading, modelCloseSignal, modelPickerEl,
      selectModel, openAddModelFromPicker, ensurePickerModels,
      username, userInitial,
      sessionInfoOpen, sessionInfoEl, sessionInfoRows,
      loadSessionList, switchSession, deleteSession, isRunning,
      route, openSettings, closeSettings,
      settingsPanel, settingsConfig, settingsMeta, settingsSaving,
      settingsMessage, settingsError, sandboxForm, collapsedPlatforms,
      modal, toastMsg, platformDraft, modelSearch, catalogModels, catalogLoading,
      catalogError, selectedCatalogIds, filteredCatalog, modelDraft,
      mcpServers, mcpMeta, mcpStatus, mcpDraft, mcpImportJson, mcpImportError,
      appVersion, updateChecking, updateInstalling, pendingUpdateVersion,
      checkForUpdates, snoozeUpdate, installUpdate, closeUpdateModal,
      settingsToast, closeModal, togglePlatformCollapsed, togglePlatformEnabled,
      setDefaultModel, toggleModelEnabled, removeModel, removePlatform,
      openAddPlatform, openEditPlatform, savePlatformDraft, openAddModel,
      loadCatalogForAdd, confirmAddModels, openModelSettings, setDefaultModelFromDraft,
      saveModelDraft, testModel, saveSandbox, mcpHasAuth, loadMcp, openAddMcp,
      openEditMcp, saveMcpDraft, removeMcp, testMcp, openImportMcp, confirmImportMcp,
      setupRequired, setupForm, setupSaving, setupError, finishSetup,
      setupCatalog, setupCatalogLoading, setupCatalogError, onSetupProviderChange, loadSetupCatalog,
      sandboxDegraded, sandboxDegradedReason, sandboxStarting, sandboxRetrying, retrySandbox,
      // chat
      timeline, draft, streaming, thinking, errorMessage, canSend,
      submit, stopStream, newChat, renderMarkdown, autoGrow, onComposerEnter,
      // usage / running
      usageText, turnTotalsText, runningTool, runningSeconds,
      // files
      fileTree, childrenMap, expandedFolders, filesLoading, filesError, workspaceOpen,
      loadFiles, toggleFolder, newFolderOpen, newFolderName, creatingFolder, newFolderInputEl,
      openNewFolder, cancelNewFolder, createFolder,
      // pwd
      workspaceFolders, selectedPwd, pwdCloseSignal, pwdPickerEl, selectPwd, onSessionInfoClick,
      // preview
      preview, previewCollapsed, previewExpanded, previewWidth, previewBackdropVisible,
      sidebarOpen,
      previewWorkspaceFile, downloadWorkspaceFile, openPreviewInTab,
      // refs
      scrollEl, inputEl,
    };
  },
}).mount("#app");
