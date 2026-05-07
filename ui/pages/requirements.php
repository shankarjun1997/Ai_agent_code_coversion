<?php
require_once __DIR__ . '/../config.php';
// Show runs in requirements or requirements_review stage
$runs = api_get('/api/pipeline/runs', ['limit' => 50]);
$req_runs = array_filter($runs, fn($r) => in_array($r['stage'], ['requirements', 'requirements_review']));
?>
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title><?= APP_TITLE ?> — Requirements</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script defer src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js"></script>
  <link rel="stylesheet" href="/assets/style.css">
</head>
<body class="bg-gray-50 font-sans">
<div class="flex h-screen overflow-hidden">
  <?php include 'sidebar.php'; ?>
  <main class="flex-1 overflow-auto">
    <header class="bg-white border-b px-8 py-4">
      <h1 class="text-xl font-semibold">Requirements — Agent 1 (Paramjit)</h1>
    </header>
    <div class="p-8 space-y-6">
      <div class="card">
        <div class="card-header"><h2 class="card-title">Start from Unstructured Input</h2></div>
        <form action="/api.php" method="POST" class="space-y-4">
          <input type="hidden" name="action" value="trigger">
          <textarea name="raw_input" rows="8" class="w-full border rounded-lg px-3 py-2 text-sm"
                    placeholder="Paste call transcript, email, meeting notes, or any unstructured requirements here..."></textarea>
          <div class="flex gap-3">
            <input type="text" name="jira_issue_key" placeholder="Jira issue key (optional)"
                   class="border rounded px-3 py-2 text-sm w-48">
            <button type="submit" class="btn-primary">Analyse with Agent 1 →</button>
          </div>
        </form>
      </div>

      <!-- Active requirement runs -->
      <?php foreach ($req_runs as $r):
        $req_data = json_decode($r['requirements_json'] ?? 'null', true);
      ?>
      <div x-data="{open: true}" class="card <?= $r['status'] === 'waiting_review' ? 'border-yellow-300' : '' ?>">
        <button @click="open = !open" class="w-full text-left">
          <div class="flex items-center justify-between">
            <div>
              <span class="font-semibold"><?= htmlspecialchars($r['jira_issue']) ?></span>
              <?= stage_badge($r['stage']) ?>
            </div>
            <span class="text-xs text-gray-400"><?= time_ago($r['started_at']) ?></span>
          </div>
        </button>

        <div x-show="open" x-cloak class="mt-4 border-t pt-4">
          <?php if ($req_data): ?>
          <div class="grid grid-cols-2 gap-6 text-sm">
            <div>
              <div class="text-xs font-medium text-gray-500 mb-1">Summary</div>
              <div class="font-medium"><?= htmlspecialchars($req_data['jira_story_draft']['summary'] ?? '') ?></div>
              <div class="mt-2 text-xs text-gray-500">Description</div>
              <div class="text-sm text-gray-700 mt-1 whitespace-pre-wrap"><?= htmlspecialchars($req_data['jira_story_draft']['description'] ?? '') ?></div>
            </div>
            <div>
              <div class="text-xs font-medium text-gray-500 mb-2">Task Breakdown</div>
              <?php foreach ($req_data['task_breakdown'] ?? [] as $task): ?>
              <div class="text-xs bg-gray-50 border rounded px-2 py-1 mb-1"><?= htmlspecialchars($task) ?></div>
              <?php endforeach; ?>

              <?php if ($req_data['clarifying_questions'] ?? []): ?>
              <div class="mt-3 text-xs font-medium text-gray-500 mb-2">Clarifying Questions</div>
              <?php foreach ($req_data['clarifying_questions'] as $q): ?>
              <div class="text-xs bg-amber-50 border border-amber-100 rounded px-2 py-1 mb-1">
                <span class="font-medium">[<?= strtoupper(htmlspecialchars($q['priority'])) ?>]</span>
                <?= htmlspecialchars($q['question']) ?>
              </div>
              <?php endforeach; ?>
              <?php endif; ?>

              <?php if ($req_data['contradictions'] ?? []): ?>
              <div class="mt-3 text-xs font-medium text-red-500 mb-2">Contradictions Detected</div>
              <?php foreach ($req_data['contradictions'] as $c): ?>
              <div class="text-xs bg-red-50 border border-red-100 rounded px-2 py-1 mb-1"><?= htmlspecialchars($c) ?></div>
              <?php endforeach; ?>
              <?php endif; ?>
            </div>
          </div>

          <!-- Prototype -->
          <?php if ($req_data['prototype'] ?? null): $proto = $req_data['prototype']; ?>
          <div class="mt-4 border-t pt-4">
            <div class="text-xs font-medium text-gray-500 mb-2">Data Prototype — <?= htmlspecialchars($proto['target_table']) ?></div>
            <div class="overflow-x-auto">
              <table class="text-xs border-collapse">
                <thead>
                  <tr class="bg-gray-100">
                    <?php foreach ($proto['columns'] ?? [] as $col): ?>
                    <th class="border px-3 py-1 text-left">
                      <?= htmlspecialchars($col['name']) ?>
                      <div class="text-gray-400 font-normal"><?= htmlspecialchars($col['type']) ?></div>
                    </th>
                    <?php endforeach; ?>
                  </tr>
                </thead>
                <tbody>
                  <?php foreach ($proto['sample_rows'] ?? [] as $row): ?>
                  <tr class="hover:bg-gray-50">
                    <?php foreach ($proto['columns'] ?? [] as $col): ?>
                    <td class="border px-3 py-1 font-mono"><?= htmlspecialchars((string)($row[$col['name']] ?? '—')) ?></td>
                    <?php endforeach; ?>
                  </tr>
                  <?php endforeach; ?>
                </tbody>
              </table>
            </div>
            <?php if ($proto['notes'] ?? null): ?>
            <div class="text-xs text-gray-500 mt-2"><?= htmlspecialchars($proto['notes']) ?></div>
            <?php endif; ?>
          </div>
          <?php endif; ?>

          <?php if ($r['status'] === 'waiting_review'): ?>
          <div class="mt-4 border-t pt-4 flex gap-3">
            <form action="/api.php" method="POST" class="flex-1 flex gap-2">
              <input type="hidden" name="action" value="approve">
              <input type="hidden" name="run_id" value="<?= htmlspecialchars($r['run_id']) ?>">
              <input type="text" name="reviewer" placeholder="Your name" class="border rounded px-2 py-1 text-sm flex-1" required>
              <input type="text" name="notes" placeholder="Notes (optional)" class="border rounded px-2 py-1 text-sm flex-1">
              <button type="submit" class="bg-green-600 text-white rounded px-4 py-1 text-sm">✓ Approve → Push to Jira</button>
            </form>
            <form action="/api.php" method="POST">
              <input type="hidden" name="action" value="reject">
              <input type="hidden" name="run_id" value="<?= htmlspecialchars($r['run_id']) ?>">
              <input type="hidden" name="reviewer" value="reviewer">
              <input type="hidden" name="notes" value="Rejected from requirements page">
              <button type="submit" class="bg-red-600 text-white rounded px-4 py-1 text-sm">✗ Reject</button>
            </form>
          </div>
          <?php endif; ?>

          <?php else: ?>
          <div class="text-gray-400 text-sm py-4">Agent 1 is still processing...</div>
          <?php endif; ?>
        </div>
      </div>
      <?php endforeach; ?>

    </div>
  </main>
</div>
</body>
</html>
