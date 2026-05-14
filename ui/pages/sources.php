<?php
require_once __DIR__ . '/../config.php';
$profiles = api_get('/api/discovery/profiles')['profiles'] ?? [];
$flash = $_GET['msg'] ?? '';
$err   = $_GET['err'] ?? '';
$tab   = $_GET['tab'] ?? 'jira';
?>
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title><?= APP_TITLE ?> — Sources</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script defer src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js"></script>
  <link rel="stylesheet" href="/assets/style.css">
  <style>
    .tab-pill { padding: .5rem 1rem; border-radius: 9999px; font-weight: 500; font-size: .875rem; }
    .tab-pill.active { background: #1f2937; color: white; }
    .tab-pill:not(.active) { background: #e5e7eb; color: #374151; }
    .tab-pill:not(.active):hover { background: #d1d5db; }
    .dot { width: .5rem; height: .5rem; border-radius: 9999px; display: inline-block; margin-right: .35rem; }
    .dot.ok { background: #10b981; }
    .dot.err { background: #ef4444; }
    .dot.unknown { background: #9ca3af; }
  </style>
</head>
<body class="bg-gray-50 font-sans">
<div class="flex h-screen overflow-hidden">
  <?php include 'sidebar.php'; ?>
  <main class="flex-1 overflow-auto">
    <header class="bg-white border-b px-8 py-4">
      <h1 class="text-xl font-semibold">Sources</h1>
      <p class="text-sm text-gray-500 mt-1">Register Jira workspaces, BigQuery projects, and source databases. These profiles feed L1 intent, L2 metadata discovery, and L3/L4 mapping.</p>
    </header>

    <?php if ($flash): ?>
      <div class="mx-8 mt-4 bg-green-50 border border-green-200 text-green-800 rounded px-4 py-2 text-sm"><?= htmlspecialchars($flash) ?></div>
    <?php endif; ?>
    <?php if ($err): ?>
      <div class="mx-8 mt-4 bg-red-50 border border-red-200 text-red-800 rounded px-4 py-2 text-sm"><?= htmlspecialchars($err) ?></div>
    <?php endif; ?>

    <div class="p-8 space-y-6">
      <div class="flex gap-3">
        <a class="tab-pill <?= $tab==='jira' ? 'active' : '' ?>"     href="?tab=jira">Jira</a>
        <a class="tab-pill <?= $tab==='bigquery' ? 'active' : '' ?>" href="?tab=bigquery">BigQuery</a>
        <a class="tab-pill <?= $tab==='db' ? 'active' : '' ?>"        href="?tab=db">Source DB</a>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <!-- LEFT: registration form -->
        <div class="bg-white border rounded-lg p-6">
          <?php if ($tab === 'jira'): ?>
            <h2 class="font-semibold mb-1">Connect a Jira workspace</h2>
            <p class="text-xs text-gray-500 mb-4">Atlassian Cloud. Use an API token from <a class="underline" href="https://id.atlassian.com/manage-profile/security/api-tokens" target="_blank">id.atlassian.com</a>.</p>
            <form action="/api.php" method="POST" class="space-y-3 text-sm">
              <input type="hidden" name="action" value="sources_register_jira">
              <div><label class="block text-xs text-gray-600 mb-1">Label</label>
                <input name="label" required class="w-full border rounded px-3 py-2" placeholder="Acme — Engineering"></div>
              <div><label class="block text-xs text-gray-600 mb-1">Base URL</label>
                <input name="base_url" required class="w-full border rounded px-3 py-2" placeholder="https://acme.atlassian.net"></div>
              <div><label class="block text-xs text-gray-600 mb-1">Email</label>
                <input name="email" type="email" required class="w-full border rounded px-3 py-2" placeholder="you@acme.com"></div>
              <div><label class="block text-xs text-gray-600 mb-1">API token</label>
                <input name="api_token" type="password" required class="w-full border rounded px-3 py-2"></div>
              <div><label class="block text-xs text-gray-600 mb-1">Default project key (optional)</label>
                <input name="project_key" class="w-full border rounded px-3 py-2" placeholder="DATA"></div>
              <button class="bg-indigo-600 hover:bg-indigo-700 text-white rounded px-4 py-2">Register Jira workspace</button>
            </form>

          <?php elseif ($tab === 'bigquery'): ?>
            <h2 class="font-semibold mb-1">Connect a BigQuery project</h2>
            <p class="text-xs text-gray-500 mb-4">Service-account JSON contents (optional if ADC is configured on the API host).</p>
            <form action="/api.php" method="POST" class="space-y-3 text-sm">
              <input type="hidden" name="action" value="sources_register_bq">
              <div><label class="block text-xs text-gray-600 mb-1">Label</label>
                <input name="label" required class="w-full border rounded px-3 py-2" placeholder="Acme — Analytics"></div>
              <div><label class="block text-xs text-gray-600 mb-1">Project ID</label>
                <input name="project_id" required class="w-full border rounded px-3 py-2" placeholder="acme-analytics-prod"></div>
              <div><label class="block text-xs text-gray-600 mb-1">Service-account JSON (optional)</label>
                <textarea name="credentials_json" rows="6" class="w-full border rounded px-3 py-2 font-mono text-xs" placeholder='{"type":"service_account", ...}'></textarea></div>
              <button class="bg-blue-600 hover:bg-blue-700 text-white rounded px-4 py-2">Register BigQuery project</button>
            </form>

          <?php else: ?>
            <h2 class="font-semibold mb-1">Connect a source database</h2>
            <p class="text-xs text-gray-500 mb-4">Postgres / MySQL / MSSQL / Oracle.</p>
            <form action="/api.php" method="POST" class="space-y-3 text-sm">
              <input type="hidden" name="action" value="sources_register_db">
              <div><label class="block text-xs text-gray-600 mb-1">Label</label>
                <input name="label" required class="w-full border rounded px-3 py-2" placeholder="CRM — Postgres replica"></div>
              <div><label class="block text-xs text-gray-600 mb-1">Dialect</label>
                <select name="dialect" class="w-full border rounded px-3 py-2">
                  <option value="postgres">Postgres</option>
                  <option value="mysql">MySQL</option>
                  <option value="mssql">MS SQL</option>
                  <option value="oracle">Oracle</option>
                </select></div>
              <div x-data="{dialect:'postgres'}" x-init="$watch('$root.querySelector(\'select[name=dialect]\').value',v=>dialect=v)">
                <label class="block text-xs text-gray-600 mb-1">DSN</label>
                <input name="dsn" required class="w-full border rounded px-3 py-2 font-mono text-xs"
                       placeholder="postgresql://user:pass@host:5432/db">
              </div>
              <button class="bg-emerald-600 hover:bg-emerald-700 text-white rounded px-4 py-2">Register source DB</button>
            </form>
          <?php endif; ?>
        </div>

        <!-- RIGHT: registered profiles -->
        <div class="bg-white border rounded-lg p-6">
          <h2 class="font-semibold mb-3">Registered profiles</h2>
          <?php if (!$profiles): ?>
            <div class="text-xs text-gray-500">No profiles yet — register one on the left.</div>
          <?php else: ?>
            <div class="space-y-2">
            <?php foreach ($profiles as $p):
              $ping_status = $p['last_ping_status'] ?? 'unknown';
              $dot_cls = $ping_status === 'ok' ? 'ok' : ($ping_status === 'error' ? 'err' : 'unknown');
              ?>
              <div class="border rounded p-3 text-sm flex items-center justify-between">
                <div class="min-w-0 flex-1">
                  <div class="flex items-center gap-2">
                    <span class="dot <?= $dot_cls ?>"></span>
                    <span class="font-medium truncate"><?= htmlspecialchars($p['label']) ?></span>
                    <span class="text-xs text-gray-400 px-1.5 py-0.5 bg-gray-100 rounded"><?= htmlspecialchars($p['dialect']) ?></span>
                  </div>
                  <div class="text-xs text-gray-500 mt-0.5 font-mono truncate"><?= htmlspecialchars($p['host']) ?></div>
                  <?php if ($ping_status !== 'unknown'): ?>
                    <div class="text-xs text-gray-400 mt-0.5">last ping: <?= htmlspecialchars($p['last_ping'] ?? '?') ?></div>
                  <?php endif; ?>
                </div>
                <div class="flex gap-2 ml-3">
                  <form action="/api.php" method="POST">
                    <input type="hidden" name="action" value="sources_ping">
                    <input type="hidden" name="id" value="<?= htmlspecialchars($p['id']) ?>">
                    <input type="hidden" name="tab" value="<?= htmlspecialchars($tab) ?>">
                    <button class="text-xs border rounded px-2 py-1 hover:bg-gray-50">Test</button>
                  </form>
                  <form action="/api.php" method="POST" onsubmit="return confirm('Delete this profile?');">
                    <input type="hidden" name="action" value="sources_delete">
                    <input type="hidden" name="id" value="<?= htmlspecialchars($p['id']) ?>">
                    <input type="hidden" name="tab" value="<?= htmlspecialchars($tab) ?>">
                    <button class="text-xs border border-red-200 text-red-600 rounded px-2 py-1 hover:bg-red-50">Delete</button>
                  </form>
                </div>
              </div>
            <?php endforeach; ?>
            </div>
          <?php endif; ?>
        </div>
      </div>
    </div>
  </main>
</div>
</body>
</html>
