<?php // views/batch_show.php — expects $batch_id, $api_ext ?>
<div class="page-header">
  <h1>Batch Dashboard</h1>
  <p>Batch ID: <code style="font-family:var(--mono);font-size:12px"><?= htmlspecialchars($batch_id) ?></code></p>
</div>

<div class="alert alert-warn">
  Phase 2 pending. POST /api/stm/batches not yet implemented. Session data will appear here once the endpoint is live.
</div>

<div class="card">
  <h2>Sessions</h2>
  <table>
    <thead>
      <tr>
        <th>Session ID</th>
        <th>Status</th>
        <th>Stage</th>
        <th>Created</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td colspan="5" style="color:var(--muted);font-size:12px;text-align:center;padding:24px">
          No sessions yet. Sessions will appear here once the batch API is implemented.
        </td>
      </tr>
    </tbody>
  </table>
</div>
