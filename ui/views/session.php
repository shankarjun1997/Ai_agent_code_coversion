<?php // views/session.php — expects $session_id, $session (array|null), $api_ext ?>
<div class="page-header">
  <h1>Session Stepper</h1>
  <p>Session ID: <code style="font-family:var(--mono);font-size:12px"><?= htmlspecialchars($session_id) ?></code></p>
</div>

<!-- Summary card -->
<div class="card">
  <h2>Summary</h2>
  <?php if ($session): ?>
  <table>
    <tbody>
      <tr><th style="width:140px">Status</th>
          <td><span class="badge badge-<?= htmlspecialchars($session['status'] ?? 'pending') ?>">
            <?= htmlspecialchars($session['status'] ?? '—') ?>
          </span></td></tr>
      <tr><th>Stage</th>
          <td><?= htmlspecialchars($session['current_stage'] ?? $session['stage'] ?? '—') ?></td></tr>
      <tr><th>Created</th>
          <td><?= htmlspecialchars(substr($session['created_at'] ?? '—', 0, 19)) ?></td></tr>
    </tbody>
  </table>
  <?php else: ?>
  <p style="font-size:12px;color:var(--muted)">Session data unavailable or still initialising.</p>
  <?php endif; ?>
</div>

<!-- Stage sections -->
<details class="card" style="cursor:pointer">
  <summary style="font-weight:600;font-size:13px;padding:4px 0">§01 Schemas</summary>
  <div style="margin-top:12px;font-size:12px;color:var(--muted)">
    Schema intelligence output will appear here once Stage 1 completes.
  </div>
</details>

<details class="card" style="cursor:pointer">
  <summary style="font-weight:600;font-size:13px;padding:4px 0">§02 Shortlist</summary>
  <div style="margin-top:12px;font-size:12px;color:var(--muted)">
    Candidate field shortlist will appear here once Stage 2 completes.
  </div>
</details>

<details class="card" style="cursor:pointer">
  <summary style="font-weight:600;font-size:13px;padding:4px 0">§03 Mapping</summary>
  <div style="margin-top:12px;font-size:12px;color:var(--muted)">
    Field-level mapping decisions will appear here once Stage 3 completes.
  </div>
</details>

<details class="card" style="cursor:pointer">
  <summary style="font-weight:600;font-size:13px;padding:4px 0">§04 SQL</summary>
  <div style="margin-top:12px;font-size:12px;color:var(--muted)">
    Generated SQL will appear here once Stage 4 completes.
  </div>
</details>

<script>
(function() {
  const SESSION_ID = <?= json_encode($session_id) ?>;
  const API_EXT    = <?= json_encode($api_ext) ?>;
  const url        = API_EXT + '/api/stm/sessions/' + encodeURIComponent(SESSION_ID) + '/events';

  // Phase 2 will hook SSE events into the DOM sections above.
  const es = new EventSource(url);

  es.onopen = function() {
    console.log('[SSE] connected to', url);
  };

  es.onmessage = function(e) {
    console.log('[SSE] message:', e.data);
  };

  es.onerror = function(e) {
    console.warn('[SSE] error / stream closed', e);
    // Do not auto-reconnect in Phase 1 stub — EventSource retries natively.
  };

  // Expose for Phase 2 DOM wiring.
  window.__stmSSE = es;
})();
</script>
