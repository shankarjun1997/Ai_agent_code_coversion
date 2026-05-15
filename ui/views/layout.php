<?php // views/layout.php — expects $content, $title (optional), $page (optional) ?>
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title><?= htmlspecialchars($title ?? 'Mapping Agent') ?> — SQL-Gen</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg:       #faf9f6;
  --surface:  #ffffff;
  --border:   #d4cfc8;
  --text:     #1a1918;
  --muted:    #6b6460;
  --accent:   #2563eb;
  --danger:   #dc2626;
  --success:  #16a34a;
  --warn:     #d97706;
  --mono:     'JetBrains Mono', 'Fira Mono', 'Courier New', monospace;
  --serif:    Georgia, 'Times New Roman', serif;
}

html { background: var(--bg); color: var(--text); font-family: var(--mono); font-size: 13px; }

/* ── Top bar ─────────────────────────────────────── */
.topbar {
  display: flex; align-items: center; gap: 16px;
  padding: 0 24px; height: 44px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  position: sticky; top: 0; z-index: 100;
}
.topbar-brand { font-family: var(--serif); font-size: 15px; font-weight: bold; letter-spacing: 0.02em; }
.topbar-vol   { font-size: 11px; color: var(--muted); }
.topbar-nav   { display: flex; gap: 12px; margin-left: auto; }
.topbar-nav a { color: var(--muted); text-decoration: none; font-size: 12px; }
.topbar-nav a:hover, .topbar-nav a.active { color: var(--text); }

/* ── Layout ─────────────────────────────────────── */
.page { max-width: 1280px; margin: 0 auto; padding: 24px 24px; }
.page-header { margin-bottom: 20px; }
.page-header h1 { font-family: var(--serif); font-size: 24px; font-weight: normal; }
.page-header p  { color: var(--muted); margin-top: 4px; font-size: 12px; }

/* ── Dot-matrix tables ──────────────────────────── */
table { border-collapse: collapse; width: 100%; font-size: 12px; }
th, td { padding: 6px 10px; border: 1px dotted var(--border); text-align: left; }
th { font-weight: 600; background: #f2f0ec; }
tr:hover td { background: #f8f7f4; }

/* ── Two-col split ──────────────────────────────── */
.split { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
@media (max-width: 900px) { .split { grid-template-columns: 1fr; } }

/* ── Cards / sections ───────────────────────────── */
.card { background: var(--surface); border: 1px solid var(--border); padding: 16px; margin-bottom: 16px; }
.card h2 { font-family: var(--serif); font-size: 16px; font-weight: normal; margin-bottom: 12px; }
.card h3 { font-size: 13px; font-weight: 600; margin-bottom: 8px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }

/* ── Forms ───────────────────────────────────────── */
label  { display: block; margin-bottom: 4px; font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
input[type=text], input[type=file], textarea, select {
  width: 100%; padding: 7px 10px; border: 1px solid var(--border);
  background: var(--bg); color: var(--text); font-family: var(--mono); font-size: 13px;
}
textarea { resize: vertical; min-height: 80px; }
.form-row { margin-bottom: 14px; }
.btn { display: inline-block; padding: 7px 16px; border: 1px solid currentColor; cursor: pointer;
       background: transparent; font-family: var(--mono); font-size: 13px; }
.btn-primary { color: var(--accent); }
.btn-danger  { color: var(--danger); }
.btn-sm { padding: 3px 10px; font-size: 11px; }

/* ── Badges ──────────────────────────────────────── */
.badge { display: inline-block; padding: 2px 7px; font-size: 11px; border: 1px solid; }
.badge-active  { color: var(--success); border-color: var(--success); }
.badge-pending { color: var(--warn);    border-color: var(--warn); }
.badge-done    { color: var(--muted);   border-color: var(--border); }
.badge-error   { color: var(--danger);  border-color: var(--danger); }

/* ── Alerts ──────────────────────────────────────── */
.alert { padding: 10px 14px; margin-bottom: 14px; border-left: 3px solid; font-size: 12px; }
.alert-info    { border-color: var(--accent);  background: #eff6ff; }
.alert-warn    { border-color: var(--warn);    background: #fffbeb; }
.alert-error   { border-color: var(--danger);  background: #fef2f2; }
.alert-success { border-color: var(--success); background: #f0fdf4; }
</style>
</head>
<body>
<nav class="topbar">
  <span class="topbar-vol">Vol.&thinsp;#1</span>
  <span class="topbar-brand">MAPPING AGENT</span>
  <nav class="topbar-nav">
    <a href="/catalog"   class="<?= ($page??'') === 'catalog'    ? 'active' : '' ?>">Catalog</a>
    <a href="/batch/new" class="<?= ($page??'') === 'batch_new'  ? 'active' : '' ?>">New Batch</a>
    <a href="/queue"     class="<?= ($page??'') === 'queue'       ? 'active' : '' ?>">Queue</a>
  </nav>
</nav>
<main class="page">
<?= $content ?>
</main>
</body>
</html>
