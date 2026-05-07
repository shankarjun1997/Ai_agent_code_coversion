<?php
require_once __DIR__ . '/../config.php';

$run_id = $_GET['run_id'] ?? null;
$msg    = $_GET['msg'] ?? null;

if ($run_id) {
    $run       = api_get("/api/pipeline/runs/$run_id");
    $artifacts = api_get("/api/pipeline/runs/$run_id/artifacts");
    $logs      = json_decode($run['log_json'] ?? '[]', true) ?? [];
    $approvals = json_decode($run['approvals_json'] ?? '[]', true) ?? [];
} else {
    $runs = api_get('/api/pipeline/runs', ['limit' => 50]);
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title><?= APP_TITLE ?> — Pipelines</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://unpkg.com/htmx.org@1.9.12"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css">
  <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
  <link rel="stylesheet" href="/assets/style.css">
</head>
<body class="bg-gray-50 font-sans">

<div class="flex h-screen overflow-hidden">
  <!-- Sidebar (same across all pages) -->
  <?php include __DIR__ . '/sidebar.php'; ?>

  <main class="flex-1 overflow-auto">
    <header class="bg-white border-b px-8 py-4">
      <h1 class="text-xl font-semibold">
        <?= $run_id ? 'Pipeline Run — ' . htmlspecialchars(substr($run_id, 0, 8)) : 'All Pipelines' ?>
      </h1>
    </header>

    <div class="p-8">

    <?php if ($msg): ?>
      <div class="mb-4 px-4 py-3 rounded-lg <?= $msg === 'approved' ? 'bg-green-50 text-green-800 border border-green-200' : 'bg-red-50 text-red-800 border border-red-200' ?>">
        <?= $msg === 'approved' ? '✓ Approved — pipeline advancing to next stage.' : '✗ Rejected — pipeline has been stopped.' ?>
      </div>
    <?php endif; ?>

    <?php if ($run_id && $run): ?>
      <!-- Run detail view -->
      <div class="grid grid-cols-3 gap-6">

        <!-- Left: Status + Logs -->
        <div class="col-span-2 space-y-6">

          <!-- Status card -->
          <div class="card">
            <div class="card-header">
              <h2 class="card-title">Status</h2>
              <div class="text-sm">
                <?= stage_badge($run['stage']) ?>
                <span class="ml-2"><?= status_badge($run['status']) ?></span>
              </div>
            </div>
            <dl class="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
              <dt class="text-gray-500">Jira Issue</dt><dd class="font-medium"><?= htmlspecialchars($run['jira_issue']) ?></dd>
              <dt class="text-gray-500">Run ID</dt><dd class="font-mono text-xs"><?= htmlspecialchars($run['run_id']) ?></dd>
              <dt class="text-gray-500">Started</dt><dd><?= time_ago($run['started_at']) ?></dd>
              <dt class="text-gray-500">Completed</dt><dd><?= $run['completed_at'] ? time_ago($run['completed_at']) : '—' ?></dd>
            </dl>
          </div>

          <!-- Live log with SSE -->
          <div class="card" id="log-card">
            <div class="card-header">
              <h2 class="card-title">Pipeline Log</h2>
              <?php if ($run['status'] === 'running'): ?>
              <span class="inline-flex items-center gap-1 text-xs text-blue-600">
                <span class="animate-pulse w-2 h-2 bg-blue-500 rounded-full"></span> Live
              </span>
              <?php endif; ?>
            </div>
            <div id="log-output" class="font-mono text-xs text-gray-700 space-y-0.5 max-h-72 overflow-auto">
              <?php foreach ($logs as $log): ?>
              <div class="log-line"><?= htmlspecialchars($log) ?></div>
              <?php endforeach; ?>
            </div>
          </div>

          <!-- Artifacts -->
          <?php if ($artifacts): ?>
          <div class="card">
            <div class="card-header"><h2 class="card-title">Generated Artifacts (<?= count($artifacts) ?>)</h2></div>
            <div class="space-y-4">
              <?php foreach ($artifacts as $art): ?>
              <div x-data="{open: false}" class="border rounded-lg overflow-hidden">
                <button @click="open = !open"
                        class="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 text-left">
                  <div>
                    <span class="font-mono text-sm font-medium"><?= htmlspecialchars($art['filename']) ?></span>
                    <span class="ml-2 text-xs text-gray-500"><?= htmlspecialchars($art['artifact_type']) ?></span>
                    <?php if (isset($art['dry_run_valid'])): ?>
                    <span class="ml-2 text-xs <?= $art['dry_run_valid'] ? 'text-green-600' : 'text-red-600' ?>">
                      <?= $art['dry_run_valid'] ? '✓ dry-run ok' : '✗ dry-run failed' ?>
                    </span>
                    <?php endif; ?>
                  </div>
                  <span class="text-gray-400 text-sm" x-text="open ? '▲' : '▼'">▼</span>
                </button>
                <div x-show="open" x-cloak class="border-t">
                  <div class="px-4 py-2 bg-gray-50 text-xs text-gray-600 border-b">
                    <?= htmlspecialchars($art['explanation'] ?? '') ?>
                  </div>
                  <pre class="overflow-auto text-xs max-h-96 p-4"><code class="<?= str_ends_with($art['filename'], '.py') ? 'language-python' : 'language-sql' ?>"><?= htmlspecialchars($art['content']) ?></code></pre>
                </div>
              </div>
              <?php endforeach; ?>
            </div>
          </div>
          <?php endif; ?>

        </div>

        <!-- Right: Review gate + history -->
        <div class="space-y-6">

          <!-- Review gate -->
          <?php if ($run['status'] === 'waiting_review'): ?>
          <div class="card border-yellow-300 bg-yellow-50">
            <h2 class="card-title text-yellow-900 mb-3">⚠ Review Required</h2>
            <p class="text-sm text-yellow-800 mb-4">
              Stage <strong><?= htmlspecialchars($run['stage']) ?></strong> requires human approval.
            </p>
            <form action="/api.php" method="POST" class="space-y-3">
              <input type="hidden" name="run_id" value="<?= htmlspecialchars($run['run_id']) ?>">
              <div>
                <label class="block text-xs font-medium text-yellow-900 mb-1">Your name</label>
                <input type="text" name="reviewer" class="w-full border rounded px-3 py-1.5 text-sm" required>
              </div>
              <div>
                <label class="block text-xs font-medium text-yellow-900 mb-1">Notes</label>
                <textarea name="notes" rows="3" class="w-full border rounded px-3 py-1.5 text-sm"
                          placeholder="Optional review comments..."></textarea>
              </div>
              <div class="flex gap-2">
                <button type="submit" name="action" value="approve"
                        class="flex-1 bg-green-600 hover:bg-green-700 text-white rounded-lg px-3 py-2 text-sm font-medium">
                  ✓ Approve
                </button>
                <button type="submit" name="action" value="reject"
                        class="flex-1 bg-red-600 hover:bg-red-700 text-white rounded-lg px-3 py-2 text-sm font-medium">
                  ✗ Reject
                </button>
              </div>
            </form>
          </div>
          <?php endif; ?>

          <!-- Approval history -->
          <?php if ($approvals): ?>
          <div class="card">
            <h2 class="card-title mb-3">Approval History</h2>
            <div class="space-y-2">
              <?php foreach ($approvals as $ap): ?>
              <div class="text-xs border rounded p-2 <?= $ap['status'] === 'approved' ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200' ?>">
                <div class="font-medium"><?= htmlspecialchars($ap['status']) ?> — <?= htmlspecialchars($ap['reviewer'] ?? '') ?></div>
                <div class="text-gray-500"><?= htmlspecialchars($ap['stage']) ?></div>
                <?php if ($ap['notes']): ?>
                <div class="mt-1 text-gray-600"><?= htmlspecialchars($ap['notes']) ?></div>
                <?php endif; ?>
              </div>
              <?php endforeach; ?>
            </div>
          </div>
          <?php endif; ?>

          <!-- Errors -->
          <?php $errors = json_decode($run['errors_json'] ?? '[]', true) ?? []; ?>
          <?php if ($errors): ?>
          <div class="card border-red-200 bg-red-50">
            <h2 class="card-title text-red-900 mb-2">Errors</h2>
            <?php foreach ($errors as $e): ?>
            <div class="text-xs text-red-700 font-mono mt-1"><?= htmlspecialchars($e) ?></div>
            <?php endforeach; ?>
          </div>
          <?php endif; ?>

        </div>
      </div>

    <?php else: ?>
      <!-- Run list -->
      <div class="card">
        <div class="card-header"><h2 class="card-title">All Pipeline Runs</h2></div>
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
            <?php foreach (($runs ?? []) as $r): ?>
            <tr class="hover:bg-gray-50 cursor-pointer"
                onclick="window.location='?run_id=<?= urlencode($r['run_id']) ?>'">
              <td class="py-2 pr-4 font-mono text-xs"><?= substr($r['run_id'], 0, 8) ?></td>
              <td class="py-2 pr-4 font-medium"><?= htmlspecialchars($r['jira_issue']) ?></td>
              <td class="py-2 pr-4"><?= stage_badge($r['stage']) ?></td>
              <td class="py-2 pr-4 text-xs"><?= status_badge($r['status']) ?></td>
              <td class="py-2 text-gray-400 text-xs"><?= time_ago($r['started_at']) ?></td>
            </tr>
            <?php endforeach; ?>
          </tbody>
        </table>
      </div>
    <?php endif; ?>

    </div>
  </main>
</div>

<?php if ($run_id && isset($run) && $run['status'] === 'running'): ?>
<script>
const logOutput = document.getElementById('log-output');
const src = new EventSource('/sse.php?run_id=<?= urlencode($run_id) ?>');
src.onmessage = (e) => {
  const data = JSON.parse(e.data);
  if (data.type === 'log') {
    const div = document.createElement('div');
    div.className = 'log-line';
    div.textContent = data.message;
    logOutput.appendChild(div);
    logOutput.scrollTop = logOutput.scrollHeight;
  }
  if (data.type === 'status') {
    // Reload page to show updated status badges
  }
  if (data.type === 'done') {
    src.close();
    setTimeout(() => window.location.reload(), 1500);
  }
};
</script>
<?php endif; ?>

<script>hljs.highlightAll();</script>
</body>
</html>
