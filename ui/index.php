<?php
require_once __DIR__ . '/config.php';

$runs    = api_get('/api/pipeline/runs', ['limit' => 5]);
$pending = api_get('/api/pipeline/runs/pending');
$mappings= api_get('/api/mappings', ['limit' => 5]);

$total     = count($runs);
$waiting   = count($pending);
$completed = count(array_filter($runs, fn($r) => $r['status'] === 'completed'));
$failed    = count(array_filter($runs, fn($r) => $r['status'] === 'failed'));
?>
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title><?= APP_TITLE ?> — Dashboard</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://unpkg.com/htmx.org@1.9.12"></script>
  <script defer src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css">
  <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
  <link rel="stylesheet" href="/assets/style.css">
</head>
<body class="bg-gray-50 text-gray-900 font-sans">

<!-- Sidebar -->
<div class="flex h-screen overflow-hidden">
  <nav class="w-56 bg-gray-900 text-white flex flex-col flex-shrink-0">
    <div class="px-6 py-5 border-b border-gray-700">
      <span class="font-bold text-lg">⚡ SQL-Gen</span>
      <div class="text-gray-400 text-xs mt-0.5">v<?= APP_VERSION ?></div>
    </div>
    <div class="flex-1 py-4 space-y-1 px-3">
      <a href="/index.php"         class="nav-link active">Dashboard</a>
      <a href="/pages/pipelines.php" class="nav-link">Pipelines</a>
      <a href="/pages/requirements.php" class="nav-link">Requirements</a>
      <a href="/pages/mappings.php"  class="nav-link">Mappings</a>
      <a href="/pages/engineering.php" class="nav-link">Engineering</a>
      <a href="/pages/qa.php"        class="nav-link">QA</a>
    </div>
    <?php if ($waiting > 0): ?>
    <div class="px-4 py-3 bg-yellow-600 text-white text-sm font-medium">
      ⚠ <?= $waiting ?> run<?= $waiting > 1 ? 's' : '' ?> awaiting review
    </div>
    <?php endif; ?>
  </nav>

  <!-- Main -->
  <main class="flex-1 overflow-auto">
    <header class="bg-white border-b px-8 py-4 flex items-center justify-between">
      <h1 class="text-xl font-semibold">Dashboard</h1>
      <button onclick="document.getElementById('trigger-modal').classList.remove('hidden')"
              class="btn-primary">+ New Pipeline</button>
    </header>

    <div class="p-8 space-y-8">

      <!-- Stat cards -->
      <div class="grid grid-cols-4 gap-4">
        <div class="stat-card"><div class="stat-value"><?= $total ?></div><div class="stat-label">Total Runs</div></div>
        <div class="stat-card border-yellow-300"><div class="stat-value text-yellow-600"><?= $waiting ?></div><div class="stat-label">Awaiting Review</div></div>
        <div class="stat-card border-green-300"><div class="stat-value text-green-600"><?= $completed ?></div><div class="stat-label">Completed</div></div>
        <div class="stat-card border-red-300"><div class="stat-value text-red-600"><?= $failed ?></div><div class="stat-label">Failed</div></div>
      </div>

      <!-- Pending reviews -->
      <?php if ($pending): ?>
      <div class="bg-yellow-50 border border-yellow-200 rounded-xl p-6">
        <h2 class="text-base font-semibold text-yellow-900 mb-3">⚠ Pending Reviews</h2>
        <div class="space-y-2">
          <?php foreach ($pending as $r): ?>
          <div class="flex items-center justify-between bg-white rounded-lg px-4 py-3 border border-yellow-100">
            <div>
              <span class="font-mono text-sm font-medium"><?= htmlspecialchars($r['jira_issue']) ?></span>
              <span class="ml-3"><?= stage_badge($r['stage']) ?></span>
              <span class="text-gray-400 text-xs ml-2"><?= time_ago($r['started_at']) ?></span>
            </div>
            <a href="/pages/pipelines.php?run_id=<?= urlencode($r['run_id']) ?>"
               class="btn-sm">Review →</a>
          </div>
          <?php endforeach; ?>
        </div>
      </div>
      <?php endif; ?>

      <!-- Recent runs -->
      <div class="card">
        <div class="card-header">
          <h2 class="card-title">Recent Runs</h2>
          <a href="/pages/pipelines.php" class="text-blue-600 text-sm hover:underline">View all →</a>
        </div>
        <table class="w-full text-sm">
          <thead>
            <tr class="text-left text-gray-500 border-b">
              <th class="pb-2 pr-4">Run ID</th>
              <th class="pb-2 pr-4">Jira Issue</th>
              <th class="pb-2 pr-4">Stage</th>
              <th class="pb-2 pr-4">Status</th>
              <th class="pb-2">Started</th>
            </tr>
          </thead>
          <tbody class="divide-y">
            <?php foreach ($runs as $r): ?>
            <tr class="hover:bg-gray-50 cursor-pointer"
                onclick="window.location='/pages/pipelines.php?run_id=<?= urlencode($r['run_id']) ?>'">
              <td class="py-2 pr-4 font-mono text-xs text-gray-600"><?= substr($r['run_id'], 0, 8) ?></td>
              <td class="py-2 pr-4 font-medium"><?= htmlspecialchars($r['jira_issue']) ?></td>
              <td class="py-2 pr-4"><?= stage_badge($r['stage']) ?></td>
              <td class="py-2 pr-4 text-xs"><?= status_badge($r['status']) ?></td>
              <td class="py-2 text-gray-400 text-xs"><?= time_ago($r['started_at']) ?></td>
            </tr>
            <?php endforeach; ?>
            <?php if (!$runs): ?>
            <tr><td colspan="5" class="py-8 text-center text-gray-400">No runs yet. Create one above.</td></tr>
            <?php endif; ?>
          </tbody>
        </table>
      </div>

      <!-- Pipeline architecture -->
      <div class="card">
        <div class="card-header"><h2 class="card-title">Pipeline Architecture</h2></div>
        <div class="flex items-center gap-2 overflow-x-auto pb-2 pt-1">
          <?php
          $stages = [
            ['Agent 1', 'Requirements', 'Paramjit', 'bg-blue-500'],
            ['↓ Review', '', '', 'bg-yellow-400'],
            ['Agent 2', 'Mapping', 'Shankar', 'bg-purple-500'],
            ['↓ Review', '', '', 'bg-yellow-400'],
            ['Agent 3', 'Engineering\n3a SQL · 3b Conv\n3c DQ · 3d Obs · 3e Meta', 'Pradeep et al', 'bg-indigo-500'],
            ['↓ Review', '', '', 'bg-yellow-400'],
            ['Agent 4', 'QA', 'Sandeep', 'bg-teal-500'],
          ];
          foreach ($stages as [$agent, $name, $owner, $color]) {
            if (str_starts_with($agent, '↓')) {
              echo "<div class='text-gray-400 text-sm flex-shrink-0 px-1'>↓<br><span class='text-xs'>review</span></div>";
            } else {
              echo "<div class='flex-shrink-0 rounded-lg p-3 text-white text-xs {$color} w-32'>
                <div class='font-bold'>{$agent}</div>
                <div class='mt-1 opacity-90'>" . nl2br(htmlspecialchars($name)) . "</div>
                <div class='mt-1 opacity-70'>{$owner}</div>
              </div>";
            }
          }
          ?>
        </div>
      </div>

    </div>
  </main>
</div>

<!-- Trigger modal -->
<div id="trigger-modal" class="hidden fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
  <div class="bg-white rounded-xl shadow-2xl p-8 w-full max-w-lg">
    <h2 class="text-lg font-semibold mb-4">Start New Pipeline</h2>
    <form action="/api.php" method="POST">
      <input type="hidden" name="action" value="trigger">
      <div class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">Jira Issue Key</label>
          <input type="text" name="jira_issue_key" placeholder="DATA-1042"
                 class="w-full border rounded-lg px-3 py-2 text-sm">
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">
            Or paste requirements text
          </label>
          <textarea name="raw_input" rows="6" placeholder="Paste call transcript, meeting notes, email..."
                    class="w-full border rounded-lg px-3 py-2 text-sm"></textarea>
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">
            Legacy code to convert (optional)
          </label>
          <textarea name="legacy_code" rows="3" placeholder="Paste Teradata/Oracle SQL..."
                    class="w-full border rounded-lg px-3 py-2 text-sm font-mono"></textarea>
          <select name="legacy_dialect" class="mt-1 border rounded px-2 py-1 text-sm">
            <option value="teradata">Teradata</option>
            <option value="oracle">Oracle</option>
            <option value="sql_server">SQL Server</option>
            <option value="informatica">Informatica</option>
            <option value="spark_sql">Spark SQL</option>
          </select>
        </div>
      </div>
      <div class="flex gap-3 mt-6">
        <button type="submit" class="btn-primary flex-1">Start Pipeline</button>
        <button type="button" onclick="document.getElementById('trigger-modal').classList.add('hidden')"
                class="btn-secondary flex-1">Cancel</button>
      </div>
    </form>
  </div>
</div>

<script>hljs.highlightAll();</script>
</body>
</html>
