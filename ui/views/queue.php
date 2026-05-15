<?php // views/queue.php — expects $sessions (array), $pending_count ?>
<?php
$gate_sessions = array_filter($sessions ?? [], function($s) {
    return in_array($s['status'] ?? '', ['awaiting_gate_1', 'awaiting_gate_2'], true);
});
$gate_sessions = array_values($gate_sessions);
?>
<div class="page-header">
  <h1>Review Queue</h1>
  <p>Sessions awaiting human gate approval. Use j/k to navigate rows.</p>
</div>

<?php if ((int)($pending_count ?? count($gate_sessions)) > 0): ?>
<div class="alert alert-warn">
  <?= (int)($pending_count ?? count($gate_sessions)) ?> session(s) awaiting gate decision.
</div>
<?php else: ?>
<div class="alert alert-success">
  No sessions pending review. All gates cleared.
</div>
<?php endif; ?>

<?php if (!empty($gate_sessions)): ?>
<div class="card">
  <table id="queue-table">
    <thead>
      <tr>
        <th>Session ID</th>
        <th>Status</th>
        <th>Stage</th>
        <th>Created</th>
        <th>Action</th>
      </tr>
    </thead>
    <tbody>
    <?php foreach ($gate_sessions as $i => $s): ?>
      <tr data-idx="<?= $i ?>">
        <td><a href="/session/<?= urlencode($s['id'] ?? '') ?>"><?= htmlspecialchars(substr($s['id'] ?? '—', 0, 16)) ?>…</a></td>
        <td><span class="badge badge-pending"><?= htmlspecialchars($s['status'] ?? '—') ?></span></td>
        <td><?= htmlspecialchars($s['current_stage'] ?? $s['stage'] ?? '—') ?></td>
        <td><?= htmlspecialchars(substr($s['created_at'] ?? '—', 0, 10)) ?></td>
        <td><a href="/session/<?= urlencode($s['id'] ?? '') ?>" class="btn btn-sm btn-primary">Review</a></td>
      </tr>
    <?php endforeach; ?>
    </tbody>
  </table>
</div>
<?php elseif (empty($sessions)): ?>
<div class="card">
  <p style="font-size:12px;color:var(--muted);text-align:center;padding:24px">
    No active sessions found. <a href="/batch/new">Start a new batch</a>.
  </p>
</div>
<?php endif; ?>

<script>
(function() {
  const rows = Array.from(document.querySelectorAll('#queue-table tbody tr'));
  if (!rows.length) return;

  let cur = 0;

  function highlight(idx) {
    rows.forEach((r, i) => r.style.background = i === idx ? 'var(--bg)' : '');
    cur = idx;
  }

  highlight(0);

  document.addEventListener('keydown', function(e) {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    if (e.key === 'j') { highlight(Math.min(cur + 1, rows.length - 1)); e.preventDefault(); }
    if (e.key === 'k') { highlight(Math.max(cur - 1, 0)); e.preventDefault(); }
    if (e.key === 'Enter') {
      const link = rows[cur] && rows[cur].querySelector('a');
      if (link) link.click();
    }
  });
})();
</script>
