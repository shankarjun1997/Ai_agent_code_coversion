<?php
require_once __DIR__ . '/../auth.php';
$current = basename($_SERVER['PHP_SELF']);
$user = stm_auth_user();
function nav_link(string $href, string $label, string $current): string {
    $active = (str_contains($href, $current) || ($current === 'index.php' && $href === '/index.php'))
        ? 'bg-gray-700 text-white'
        : 'text-gray-300 hover:bg-gray-700 hover:text-white';
    return "<a href=\"$href\" class=\"nav-link-base $active\">$label</a>";
}
?>
<nav class="w-56 bg-gray-900 text-white flex flex-col flex-shrink-0">
  <div class="px-6 py-5 border-b border-gray-700">
    <a href="/index.php" class="font-bold text-lg block">⚡ SQL-Gen</a>
    <div class="text-gray-400 text-xs mt-0.5">v<?= APP_VERSION ?></div>
  </div>
  <div class="flex-1 py-4 space-y-0.5 px-3">
    <?= nav_link('/index.php',                'Dashboard',     $current) ?>
    <?= nav_link('/pages/sources.php',        'Sources',       $current) ?>
    <?= nav_link('/pages/pipelines.php',      'Pipelines',     $current) ?>
    <?= nav_link('/pages/requirements.php',   'Requirements',  $current) ?>
    <?= nav_link('/pages/mappings.php',       'Mappings',      $current) ?>
    <?= nav_link('/mapping_compose_react.html?mode=agentic', 'Agentic STM', $current) ?>
    <?= nav_link('/pages/engineering.php',    'Engineering',   $current) ?>
    <?= nav_link('/pages/qa.php',             'QA',            $current) ?>
  </div>
  <?php
  $pending_count = count(api_get('/api/pipeline/runs/pending'));
  if ($pending_count > 0):
  ?>
  <a href="/pages/pipelines.php" class="px-4 py-3 bg-yellow-600 hover:bg-yellow-700 text-white text-sm font-medium">
    ⚠ <?= $pending_count ?> awaiting review
  </a>
  <?php endif; ?>
  <?php if ($user): ?>
  <div class="border-t border-gray-700 px-4 py-3 text-xs">
    <div class="flex items-center justify-between">
      <div class="min-w-0">
        <div class="text-gray-300 truncate"><?= htmlspecialchars($user['email'] ?? 'anonymous') ?></div>
        <div class="text-gray-500 text-[10px] mt-0.5">tenant: <span class="font-mono"><?= htmlspecialchars($user['tenant_slug'] ?? '—') ?></span></div>
      </div>
      <a href="/logout.php" class="text-gray-400 hover:text-white text-[10px]" title="Sign out">⏻</a>
    </div>
  </div>
  <?php endif; ?>
</nav>
