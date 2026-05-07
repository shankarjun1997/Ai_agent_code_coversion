<?php
require_once __DIR__ . '/../config.php';
$runs = api_get('/api/pipeline/runs', ['limit' => 50]);
$qa_runs = array_filter($runs, fn($r) => in_array($r['stage'], ['qa', 'qa_review', 'completed']));
?>
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title><?= APP_TITLE ?> — QA</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script defer src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js"></script>
  <link rel="stylesheet" href="/assets/style.css">
</head>
<body class="bg-gray-50 font-sans">
<div class="flex h-screen overflow-hidden">
  <?php include 'sidebar.php'; ?>
  <main class="flex-1 overflow-auto">
    <header class="bg-white border-b px-8 py-4">
      <h1 class="text-xl font-semibold">QA — Agent 4 (Sandeep / Saikrishna)</h1>
    </header>
    <div class="p-8 space-y-6">
      <?php foreach ($qa_runs as $r):
        $qa_data = json_decode($r['qa_report_json'] ?? 'null', true);
        if (!$qa_data) continue;
        $tests   = $qa_data['test_cases'] ?? [];
        $results = $qa_data['execution_results'] ?? [];
        $defects = $qa_data['defects'] ?? [];
        $by_id   = [];
        foreach ($results as $res) $by_id[$res['test_name']] = $res;
        $pass = count(array_filter($results, fn($r2) => $r2['status'] === 'PASS'));
        $fail = count(array_filter($results, fn($r2) => $r2['status'] === 'FAIL'));
        $err  = count(array_filter($results, fn($r2) => $r2['status'] === 'ERROR'));
      ?>
      <div x-data="{open: true}" class="card">
        <button @click="open = !open" class="w-full text-left">
          <div class="flex items-center justify-between">
            <div>
              <span class="font-semibold"><?= htmlspecialchars($r['jira_issue']) ?></span>
              <?= stage_badge($r['stage']) ?>
              <span class="ml-3 text-xs <?= $qa_data['sign_off_ready'] ? 'text-green-600' : 'text-red-600' ?>">
                <?= $qa_data['sign_off_ready'] ? '✓ Sign-off ready' : '✗ Defects outstanding' ?>
              </span>
            </div>
            <div class="flex gap-4 text-xs text-gray-500">
              <span class="text-green-600">PASS: <?= $pass ?></span>
              <span class="text-red-600">FAIL: <?= $fail ?></span>
              <span class="text-gray-400">ERR: <?= $err ?></span>
            </div>
          </div>
        </button>

        <div x-show="open" x-cloak class="mt-4 border-t pt-4 space-y-4">

          <?php if ($defects): ?>
          <div class="bg-red-50 border border-red-200 rounded-lg p-4">
            <div class="text-sm font-medium text-red-900 mb-2">Defects (<?= count($defects) ?>)</div>
            <?php foreach ($defects as $d): ?>
            <div class="text-xs text-red-700 font-mono mb-1"><?= htmlspecialchars($d) ?></div>
            <?php endforeach; ?>
          </div>
          <?php endif; ?>

          <!-- Test results table -->
          <div class="overflow-x-auto">
            <table class="w-full text-xs">
              <thead><tr class="text-left text-gray-400 border-b">
                <th class="pb-1 pr-3">Test</th>
                <th class="pb-1 pr-3">Type</th>
                <th class="pb-1 pr-3">Result</th>
                <th class="pb-1">Description</th>
              </tr></thead>
              <tbody class="divide-y">
                <?php foreach ($tests as $tc):
                  $res = $by_id[$tc['test_name']] ?? null;
                  $status = $res['status'] ?? 'PENDING';
                  $cls = match($status) {
                    'PASS' => 'text-green-600',
                    'FAIL' => 'text-red-600',
                    'ERROR' => 'text-amber-600',
                    default => 'text-gray-400',
                  };
                ?>
                <tr class="hover:bg-gray-50">
                  <td class="py-1.5 pr-3 font-mono"><?= htmlspecialchars($tc['test_name']) ?></td>
                  <td class="py-1.5 pr-3 text-gray-500"><?= htmlspecialchars($tc['test_type']) ?></td>
                  <td class="py-1.5 pr-3 font-medium <?= $cls ?>"><?= $status ?></td>
                  <td class="py-1.5 text-gray-600"><?= htmlspecialchars($tc['description']) ?></td>
                </tr>
                <?php endforeach; ?>
              </tbody>
            </table>
          </div>

          <!-- QA sign-off -->
          <?php if ($r['status'] === 'waiting_review' && $r['stage'] === 'qa_review'): ?>
          <div class="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
            <p class="text-sm font-medium text-yellow-900 mb-3">QA lead sign-off required</p>
            <form action="/api.php" method="POST" class="flex gap-2">
              <input type="hidden" name="action" value="approve">
              <input type="hidden" name="run_id" value="<?= htmlspecialchars($r['run_id']) ?>">
              <input type="text" name="reviewer" placeholder="QA lead name" class="border rounded px-2 py-1 text-sm" required>
              <input type="text" name="notes" placeholder="Sign-off notes" class="border rounded px-2 py-1 text-sm flex-1">
              <button type="submit" class="bg-green-600 text-white rounded px-4 py-1 text-sm">✓ Sign Off → Complete</button>
              <button type="button" onclick="this.form.elements['action'].value='reject'; this.form.submit()"
                      class="bg-red-600 text-white rounded px-4 py-1 text-sm">✗ Reject</button>
              <input type="hidden" name="action" value="approve">
            </form>
          </div>
          <?php endif; ?>

        </div>
      </div>
      <?php endforeach; ?>
      <?php if (!$qa_runs): ?>
      <div class="text-center py-16 text-gray-400">No QA reports yet. Complete engineering review to trigger Agent 4.</div>
      <?php endif; ?>
    </div>
  </main>
</div>
</body>
</html>
