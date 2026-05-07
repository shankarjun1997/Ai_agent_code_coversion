<?php
require_once __DIR__ . '/../config.php';
$mappings = api_get('/api/mappings', ['limit' => 50]);
?>
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title><?= APP_TITLE ?> — Mappings</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script defer src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js"></script>
  <link rel="stylesheet" href="/assets/style.css">
</head>
<body class="bg-gray-50 font-sans">
<div class="flex h-screen overflow-hidden">
  <?php include 'sidebar.php'; ?>
  <main class="flex-1 overflow-auto">
    <header class="bg-white border-b px-8 py-4">
      <h1 class="text-xl font-semibold">Data Mappings</h1>
    </header>
    <div class="p-8 space-y-4">
      <?php foreach ($mappings as $m):
        $data = json_decode($m['mapping_json'], true) ?? [];
        $fields = $data['field_mappings'] ?? [];
        $sources = $data['source_tables'] ?? [];
      ?>
      <div x-data="{open: false}" class="card">
        <button @click="open = !open" class="w-full text-left">
          <div class="flex items-center justify-between">
            <div>
              <span class="font-semibold"><?= htmlspecialchars($data['target_dataset'] ?? '') ?>.<strong><?= htmlspecialchars($data['target_table'] ?? '') ?></strong></span>
              <span class="ml-3 text-xs text-gray-500 font-mono"><?= htmlspecialchars($m['mapping_id']) ?></span>
              <span class="ml-3 text-xs text-gray-400">v<?= $m['version'] ?></span>
            </div>
            <div class="flex items-center gap-3">
              <span class="text-xs text-gray-500"><?= count($fields) ?> fields</span>
              <span class="text-xs text-gray-500"><?= count($sources) ?> sources</span>
              <span class="text-xs text-gray-400"><?= time_ago($m['created_at']) ?></span>
            </div>
          </div>
        </button>
        <div x-show="open" x-cloak class="mt-4 border-t pt-4">
          <!-- Source → Target summary -->
          <div class="grid grid-cols-3 gap-4 mb-4 text-sm">
            <div>
              <div class="text-xs font-medium text-gray-500 mb-2">Source Tables</div>
              <?php foreach ($sources as $s): ?>
              <div class="font-mono text-xs bg-blue-50 rounded px-2 py-1 mb-1">
                <?= htmlspecialchars($s['dataset'] . '.' . $s['table']) ?>
                <span class="text-gray-400"> AS <?= htmlspecialchars($s['alias']) ?></span>
              </div>
              <?php endforeach; ?>
            </div>
            <div class="flex items-center justify-center text-2xl text-gray-300">→</div>
            <div>
              <div class="text-xs font-medium text-gray-500 mb-2">Target</div>
              <div class="font-mono text-xs bg-green-50 rounded px-2 py-1">
                <?= htmlspecialchars(($data['target_dataset'] ?? '') . '.' . ($data['target_table'] ?? '')) ?>
              </div>
              <?php if ($data['partition_field'] ?? null): ?>
              <div class="text-xs text-gray-500 mt-1">Partition: <?= htmlspecialchars($data['partition_field']) ?></div>
              <?php endif; ?>
              <div class="text-xs text-gray-500">Strategy: <?= htmlspecialchars($data['idempotency_strategy'] ?? '') ?></div>
            </div>
          </div>

          <!-- Field mapping table -->
          <div class="overflow-x-auto">
            <table class="w-full text-xs">
              <thead>
                <tr class="text-left text-gray-400 border-b">
                  <th class="pb-1 pr-3">Target Field</th>
                  <th class="pb-1 pr-3">Source Expression</th>
                  <th class="pb-1 pr-3">Type</th>
                  <th class="pb-1 pr-3">Nullable</th>
                  <th class="pb-1 pr-3">PII</th>
                  <th class="pb-1">Description</th>
                </tr>
              </thead>
              <tbody class="divide-y">
                <?php foreach ($fields as $f): ?>
                <tr class="hover:bg-gray-50">
                  <td class="py-1 pr-3 font-medium font-mono"><?= htmlspecialchars($f['target_field']) ?></td>
                  <td class="py-1 pr-3 font-mono text-blue-700"><?= htmlspecialchars($f['source_expression']) ?></td>
                  <td class="py-1 pr-3 text-gray-500"><?= htmlspecialchars($f['data_type']) ?></td>
                  <td class="py-1 pr-3"><?= $f['nullable'] ? '✓' : '✗' ?></td>
                  <td class="py-1 pr-3"><?= ($f['is_pii'] ?? false) ? '<span class="text-red-500">PII</span>' : '—' ?></td>
                  <td class="py-1 text-gray-500"><?= htmlspecialchars($f['description'] ?? '') ?></td>
                </tr>
                <?php endforeach; ?>
              </tbody>
            </table>
          </div>

          <?php if ($data['business_rules'] ?? []): ?>
          <div class="mt-3">
            <div class="text-xs font-medium text-gray-500 mb-1">Business Rules</div>
            <?php foreach ($data['business_rules'] as $rule): ?>
            <div class="text-xs bg-amber-50 border border-amber-100 rounded px-2 py-1 mb-1">
              <?= htmlspecialchars($rule) ?>
            </div>
            <?php endforeach; ?>
          </div>
          <?php endif; ?>

          <?php if ($data['schema_verify'] ?? null): ?>
          <?php $sv = $data['schema_verify']; ?>
          <div class="mt-3">
            <div class="text-xs font-medium text-gray-500 mb-1">BQ CLI Schema Verification</div>
            <?php if ($sv['error'] ?? null): ?>
            <div class="text-xs text-amber-600 bg-amber-50 rounded px-2 py-1"><?= htmlspecialchars($sv['error']) ?></div>
            <?php elseif ($sv['is_clean'] ?? false): ?>
            <div class="text-xs text-green-700 bg-green-50 rounded px-2 py-1">
              ✓ Verified — <?= count($sv['verified_fields'] ?? []) ?> fields confirmed in BigQuery
            </div>
            <?php else: ?>
            <div class="text-xs text-red-700 bg-red-50 rounded px-2 py-1">
              ✗ Issues found — <?= count($sv['missing_fields'] ?? []) ?> missing,
              <?= count($sv['type_mismatches'] ?? []) ?> type mismatches,
              <?= count($sv['tables_not_found'] ?? []) ?> tables not found
            </div>
            <?php endif; ?>
          </div>
          <?php endif; ?>

          <?php if ($data['svg_path'] ?? null): ?>
          <div class="mt-4" x-data="{showSvg: false}">
            <button @click="showSvg = !showSvg"
                    class="text-xs text-indigo-600 hover:text-indigo-800 font-medium flex items-center gap-1">
              <span x-text="showSvg ? '▲ Hide' : '▼ Show'"></span> Workflow Diagram (SVG)
            </button>
            <div x-show="showSvg" x-cloak class="mt-2 border rounded overflow-auto bg-white" style="max-height:600px">
              <img src="/svg.php?id=<?= urlencode($m['mapping_id']) ?>"
                   alt="Mapping workflow diagram"
                   class="max-w-full"
                   loading="lazy">
            </div>
          </div>
          <?php endif; ?>
        </div>
      </div>
      <?php endforeach; ?>
      <?php if (!$mappings): ?>
      <div class="text-center py-16 text-gray-400">No mappings yet. Run a pipeline to generate one.</div>
      <?php endif; ?>
    </div>
  </main>
</div>
</body>
</html>
