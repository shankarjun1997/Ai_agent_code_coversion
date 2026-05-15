<?php // views/error.php — expects $code, $message ?>
<div class="page-header">
  <h1>Error</h1>
</div>

<div class="card" style="text-align:center;padding:48px 24px">
  <div style="font-family:var(--mono);font-size:64px;font-weight:bold;color:var(--danger);margin-bottom:16px">
    <?= (int)($code ?? 500) ?>
  </div>
  <p style="font-size:14px;color:var(--text);margin-bottom:24px">
    <?= htmlspecialchars($message ?? 'An unexpected error occurred.') ?>
  </p>
  <a href="javascript:history.back()" class="btn btn-primary" style="margin-right:8px">Back</a>
  <a href="/catalog" class="btn">Catalog</a>
</div>
