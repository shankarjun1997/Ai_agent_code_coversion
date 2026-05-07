<?php
require_once __DIR__ . '/../config.php';
$runs = api_get('/api/pipeline/runs', ['limit' => 50]);
$eng_runs = array_filter($runs, fn($r) => in_array($r['stage'],
    ['engineering', 'engineering_review', 'qa', 'qa_review', 'completed']));
?>
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title><?= APP_TITLE ?> — Engineering</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script defer src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css">
  <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
  <link rel="stylesheet" href="/assets/style.css">
</head>
<body class="bg-gray-50 font-sans">
<div class="flex h-screen overflow-hidden">
  <?php include 'sidebar.php'; ?>
  <main class="flex-1 overflow-auto">
    <header class="bg-white border-b px-8 py-4">
      <h1 class="text-xl font-semibold">Engineering — Agent 3 (Pradeep / Chirag / Rahul / Dinesh)</h1>
    </header>
    <div class="p-8 space-y-6">

      <!-- Sub-agent legend -->
      <div class="grid grid-cols-5 gap-3 text-xs">
        <?php
        $agents = [
          ['3a', 'SQL Gen', 'DDL · Views · dbt · SQLX', 'bg-blue-50 border-blue-200 text-blue-800'],
          ['3b', 'Code Conv', 'Teradata / Oracle → BQ', 'bg-purple-50 border-purple-200 text-purple-800'],
          ['3c', 'DQ', 'Assertions · dbt tests · Procedures', 'bg-amber-50 border-amber-200 text-amber-800'],
          ['3d', 'Observability', 'Logging · Alerts · Dashboards', 'bg-teal-50 border-teal-200 text-teal-800'],
          ['3e', 'Metadata', 'Lineage · Catalog · PII · Dataplex', 'bg-indigo-50 border-indigo-200 text-indigo-800'],
        ];
        foreach ($agents as [$id, $name, $desc, $cls]):
        ?>
        <div class="border rounded-lg p-3 <?= $cls ?>">
          <div class="font-bold">Agent <?= $id ?></div>
          <div class="font-medium mt-0.5"><?= $name ?></div>
          <div class="text-xs opacity-70 mt-1"><?= $desc ?></div>
        </div>
        <?php endforeach; ?>
      </div>

      <!-- Engineering runs -->
      <?php foreach ($eng_runs as $r):
        $eng_data = json_decode($r['engineering_json'] ?? 'null', true);
        $artifacts = api_get("/api/pipeline/runs/{$r['run_id']}/artifacts");
      ?>
      <div x-data="{open: false, activeTab: 'artifacts'}" class="card">
        <button @click="open = !open" class="w-full text-left">
          <div class="flex items-center justify-between">
            <div>
              <span class="font-semibold"><?= htmlspecialchars($r['jira_issue']) ?></span>
              <?= stage_badge($r['stage']) ?>
              <?php if ($eng_data && $eng_data['github_pr_url'] ?? null): ?>
              <a href="<?= htmlspecialchars($eng_data['github_pr_url']) ?>" target="_blank"
                 class="ml-2 text-xs text-blue-600 hover:underline" onclick="event.stopPropagation()">
                GitHub PR →
              </a>
              <?php endif; ?>
            </div>
            <span class="text-xs text-gray-400"><?= time_ago($r['started_at']) ?></span>
          </div>
        </button>

        <div x-show="open" x-cloak class="mt-4 border-t pt-4">

          <?php if ($r['status'] === 'waiting_review' && $r['stage'] === 'engineering_review'): ?>
          <div class="mb-4 bg-yellow-50 border border-yellow-200 rounded-lg p-4">
            <p class="text-sm font-medium text-yellow-900 mb-3">Engineer review required before merge/deploy</p>
            <form action="/api.php" method="POST" class="flex gap-2">
              <input type="hidden" name="action" value="approve">
              <input type="hidden" name="run_id" value="<?= htmlspecialchars($r['run_id']) ?>">
              <input type="text" name="reviewer" placeholder="Your name" class="border rounded px-2 py-1 text-sm" required>
              <input type="text" name="notes" placeholder="Notes" class="border rounded px-2 py-1 text-sm flex-1">
              <button type="submit" class="bg-green-600 text-white rounded px-4 py-1 text-sm">✓ Approve → QA</button>
            </form>
          </div>
          <?php endif; ?>

          <!-- Tab nav -->
          <div class="flex gap-1 border-b mb-4">
            <?php foreach (['artifacts', 'dq', 'observability', 'metadata'] as $tab): ?>
            <button @click="activeTab = '<?= $tab ?>'"
                    :class="activeTab === '<?= $tab ?>' ? 'border-b-2 border-blue-500 text-blue-600' : 'text-gray-500 hover:text-gray-700'"
                    class="px-4 py-2 text-sm font-medium capitalize"><?= $tab ?></button>
            <?php endforeach; ?>
          </div>

          <!-- Artifacts tab -->
          <div x-show="activeTab === 'artifacts'">
            <?php if ($artifacts): ?>
            <div class="space-y-3">
              <?php foreach ($artifacts as $art): ?>
              <div x-data="{open2: false}" class="border rounded-lg">
                <button @click="open2 = !open2" class="w-full flex items-center justify-between px-3 py-2 bg-gray-50 hover:bg-gray-100 text-left">
                  <div class="flex items-center gap-2">
                    <span class="font-mono text-xs font-medium"><?= htmlspecialchars($art['filename']) ?></span>
                    <span class="text-xs text-gray-400"><?= htmlspecialchars($art['artifact_type']) ?></span>
                    <?php if (isset($art['dry_run_valid'])): ?>
                    <span class="text-xs <?= $art['dry_run_valid'] ? 'text-green-600' : 'text-red-600' ?>">
                      <?= $art['dry_run_valid'] ? '✓' : '✗' ?>
                    </span>
                    <?php endif; ?>
                  </div>
                  <span class="text-gray-400 text-xs" x-text="open2 ? '▲' : '▼'">▼</span>
                </button>
                <div x-show="open2" x-cloak>
                  <div class="px-3 py-1 text-xs text-gray-500 bg-gray-50 border-t border-b"><?= htmlspecialchars($art['explanation'] ?? '') ?></div>
                  <pre class="overflow-auto text-xs max-h-64 p-3"><code class="<?= str_ends_with($art['filename'], '.py') ? 'language-python' : (str_ends_with($art['filename'], '.yaml') || str_ends_with($art['filename'], '.yml') ? 'language-yaml' : 'language-sql') ?>"><?= htmlspecialchars($art['content']) ?></code></pre>
                </div>
              </div>
              <?php endforeach; ?>
            </div>
            <?php else: echo '<div class="text-gray-400 text-sm py-4">No artifacts yet.</div>'; endif; ?>
          </div>

          <!-- DQ tab -->
          <div x-show="activeTab === 'dq'">
            <?php
            $dq = $eng_data['dq_report'] ?? null;
            if ($dq && $dq['rules'] ?? []):
            ?>
            <div class="overflow-x-auto">
              <table class="w-full text-xs">
                <thead><tr class="text-left text-gray-400 border-b">
                  <th class="pb-1 pr-3">Rule</th>
                  <th class="pb-1 pr-3">Type</th>
                  <th class="pb-1 pr-3">Severity</th>
                  <th class="pb-1">Description</th>
                </tr></thead>
                <tbody class="divide-y">
                  <?php foreach ($dq['rules'] as $rule): ?>
                  <tr class="hover:bg-gray-50">
                    <td class="py-1 pr-3 font-mono"><?= htmlspecialchars($rule['rule_name']) ?></td>
                    <td class="py-1 pr-3"><?= htmlspecialchars($rule['rule_type']) ?></td>
                    <td class="py-1 pr-3">
                      <span class="px-1.5 py-0.5 rounded text-xs <?= $rule['severity'] === 'critical' ? 'bg-red-100 text-red-700' : 'bg-yellow-100 text-yellow-700' ?>">
                        <?= htmlspecialchars($rule['severity']) ?>
                      </span>
                    </td>
                    <td class="py-1 text-gray-600"><?= htmlspecialchars($rule['description']) ?></td>
                  </tr>
                  <?php endforeach; ?>
                </tbody>
              </table>
            </div>
            <?php else: echo '<div class="text-gray-400 text-sm py-4">DQ rules not generated yet.</div>'; endif; ?>
          </div>

          <!-- Observability tab -->
          <div x-show="activeTab === 'observability'">
            <?php $obs = $eng_data['observability'] ?? null; ?>
            <?php if ($obs): ?>
            <div class="space-y-3 text-xs">
              <div><strong>Audit Columns:</strong> <?= implode(', ', array_column($obs['audit_columns'] ?? [], 'name')) ?: '—' ?></div>
              <div>
                <strong>Alerts (<?= count($obs['alert_configs'] ?? []) ?>):</strong>
                <?php foreach ($obs['alert_configs'] ?? [] as $a): ?>
                <div class="bg-gray-50 border rounded px-2 py-1 mt-1"><?= htmlspecialchars($a['name'] ?? '') ?> — <?= htmlspecialchars($a['condition'] ?? '') ?></div>
                <?php endforeach; ?>
              </div>
            </div>
            <?php else: echo '<div class="text-gray-400 text-sm py-4">Observability config not generated yet.</div>'; endif; ?>
          </div>

          <!-- Metadata tab -->
          <div x-show="activeTab === 'metadata'">
            <?php $meta = $eng_data['metadata'] ?? null; ?>
            <?php if ($meta): ?>
            <div class="space-y-3 text-sm">
              <div><strong>Table:</strong> <?= htmlspecialchars($meta['table_fqn'] ?? '') ?></div>
              <div><strong>Description:</strong> <?= htmlspecialchars($meta['description'] ?? '') ?></div>
              <?php if ($meta['pii_columns'] ?? []): ?>
              <div><strong class="text-red-600">PII Columns:</strong> <?= htmlspecialchars(implode(', ', $meta['pii_columns'])) ?></div>
              <?php endif; ?>
              <div><strong>Lineage Upstream:</strong> <?= htmlspecialchars(implode(', ', $meta['lineage_upstream'] ?? [])) ?: '—' ?></div>
            </div>
            <?php else: echo '<div class="text-gray-400 text-sm py-4">Metadata not generated yet.</div>'; endif; ?>
          </div>
        </div>
      </div>
      <?php endforeach; ?>

    </div>
  </main>
</div>
<script>hljs.highlightAll();</script>
</body>
</html>
