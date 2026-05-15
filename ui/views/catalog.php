<?php // views/catalog.php — expects $sources, $targets, $source_detail, $target_detail, $upload_error, $refresh_error, $api_ext ?>
<div class="page-header">
  <h1>Catalog Browser</h1>
  <p>Upload Databricks schema dump on the left. Live BQ target on the right. Tick tables to include in a batch.</p>
</div>

<?php if ($upload_error ?? false): ?>
<div class="alert alert-error"><?= htmlspecialchars($upload_error) ?></div>
<?php endif; ?>
<?php if ($refresh_error ?? false): ?>
<div class="alert alert-error"><?= htmlspecialchars($refresh_error) ?></div>
<?php endif; ?>

<div class="split">

  <!-- ── Source catalogs ─────────────────────────── -->
  <div>
    <div class="card">
      <h2>Source Catalog</h2>
      <h3>Upload Databricks schema dump</h3>
      <form id="upload-form" action="<?= htmlspecialchars($api_ext) ?>/api/catalogs/source"
            method="POST" enctype="multipart/form-data">
        <div class="form-row">
          <label>Catalog name</label>
          <input type="text" name="catalog_name" placeholder="frontier_raw" required>
        </div>
        <div class="form-row">
          <label>Description (optional)</label>
          <input type="text" name="description" placeholder="Frontier source tables">
        </div>
        <div class="form-row">
          <label>File (.xlsx)</label>
          <input type="file" name="file" accept=".xlsx,.xls" required>
        </div>
        <button class="btn btn-primary" type="submit">Upload</button>
        <span id="upload-status" style="margin-left:12px;font-size:11px;color:var(--muted)"></span>
      </form>
    </div>

    <div class="card">
      <h3>Active source catalogs</h3>
      <?php if (empty($sources)): ?>
        <p style="color:var(--muted);font-size:12px">No source catalogs yet.</p>
      <?php else: ?>
        <table>
          <thead><tr><th>Name</th><th>Tables</th><th>Cols</th><th>Strategy</th><th>Date</th></tr></thead>
          <tbody>
          <?php foreach ($sources as $s): ?>
            <tr>
              <td><a href="/catalog?source_id=<?= urlencode($s['id']) ?>"><?= htmlspecialchars($s['catalog_name']) ?></a></td>
              <td><?= (int)$s['table_count'] ?></td>
              <td><?= (int)$s['column_count'] ?></td>
              <td><?= htmlspecialchars($s['source_kind'] ?? '') ?></td>
              <td><?= htmlspecialchars(substr($s['created_at'] ?? '', 0, 10)) ?></td>
            </tr>
          <?php endforeach; ?>
          </tbody>
        </table>
      <?php endif; ?>
    </div>

    <?php if (!empty($source_detail)): ?>
    <div class="card">
      <h2><?= htmlspecialchars($source_detail['catalog_name'] ?? '') ?></h2>
      <p style="font-size:11px;color:var(--muted);margin-bottom:12px">
        <?= (int)$source_detail['table_count'] ?> tables &middot; <?= (int)$source_detail['column_count'] ?> columns
      </p>
      <table>
        <thead><tr><th>Table</th><th>Cols</th></tr></thead>
        <tbody>
        <?php foreach (($source_detail['tables'] ?? []) as $t): ?>
          <tr>
            <td><?= htmlspecialchars($t['table_name']) ?></td>
            <td><?= (int)$t['column_count'] ?></td>
          </tr>
        <?php endforeach; ?>
        </tbody>
      </table>
    </div>
    <?php endif; ?>
  </div>

  <!-- ── Target catalogs ─────────────────────────── -->
  <div>
    <div class="card">
      <h2>Target Catalog</h2>
      <h3>Refresh from live BigQuery</h3>
      <form id="refresh-form">
        <div class="form-row">
          <label>GCP Project</label>
          <input type="text" id="rf-project" value="gcpproject-438715">
        </div>
        <div class="form-row">
          <label>Dataset</label>
          <input type="text" id="rf-dataset" value="vz_raw_dev">
        </div>
        <button class="btn btn-primary" type="button" onclick="doRefresh()">Refresh</button>
        <span id="refresh-status" style="margin-left:12px;font-size:11px;color:var(--muted)"></span>
      </form>
    </div>

    <div class="card">
      <h3>Active target catalogs</h3>
      <?php if (empty($targets)): ?>
        <p style="color:var(--muted);font-size:12px">No target catalogs yet. Refresh above.</p>
      <?php else: ?>
        <table>
          <thead><tr><th>Project / Dataset</th><th>Tables</th><th>Cols</th><th>Fetched</th></tr></thead>
          <tbody>
          <?php foreach ($targets as $t): ?>
            <tr>
              <td><a href="/catalog?target_id=<?= urlencode($t['id']) ?>"><?= htmlspecialchars($t['project'] . '.' . $t['dataset']) ?></a></td>
              <td><?= (int)$t['table_count'] ?></td>
              <td><?= (int)$t['column_count'] ?></td>
              <td><?= htmlspecialchars(substr($t['fetched_at'] ?? $t['created_at'] ?? '', 0, 10)) ?></td>
            </tr>
          <?php endforeach; ?>
          </tbody>
        </table>
      <?php endif; ?>
    </div>

    <?php if (!empty($target_detail)): ?>
    <div class="card">
      <h2><?= htmlspecialchars(($target_detail['project'] ?? '') . '.' . ($target_detail['dataset'] ?? '')) ?></h2>
      <p style="font-size:11px;color:var(--muted);margin-bottom:12px">
        <?= (int)$target_detail['table_count'] ?> tables &middot; <?= (int)$target_detail['column_count'] ?> columns
      </p>
      <table>
        <thead><tr><th>Table</th><th>Cols</th><th>First column</th></tr></thead>
        <tbody>
        <?php foreach (($target_detail['tables'] ?? []) as $t): ?>
          <tr>
            <td><?= htmlspecialchars($t['table_name']) ?></td>
            <td><?= (int)$t['column_count'] ?></td>
            <td style="color:var(--muted)"><?= htmlspecialchars($t['columns'][0]['name'] ?? '') ?></td>
          </tr>
        <?php endforeach; ?>
        </tbody>
      </table>
    </div>
    <?php endif; ?>
  </div>
</div>

<script>
// Handle upload form — POST to API, reload on success
document.getElementById('upload-form').addEventListener('submit', async function(e) {
  e.preventDefault();
  const status = document.getElementById('upload-status');
  status.textContent = 'Uploading…';
  const fd = new FormData(this);
  try {
    const r = await fetch(this.action, { method: 'POST', body: fd });
    const j = await r.json();
    if (r.ok) {
      status.textContent = `✓ ${j.table_count} tables, ${j.column_count} cols`;
      setTimeout(() => location.reload(), 800);
    } else {
      status.textContent = '✗ ' + (j.detail ?? JSON.stringify(j));
    }
  } catch(err) {
    status.textContent = '✗ ' + err.message;
  }
});

// Handle target refresh
async function doRefresh() {
  const status = document.getElementById('refresh-status');
  const project = document.getElementById('rf-project').value.trim();
  const dataset  = document.getElementById('rf-dataset').value.trim();
  status.textContent = 'Refreshing…';
  try {
    const r = await fetch('<?= htmlspecialchars($api_ext) ?>/api/catalogs/target/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, dataset }),
    });
    const j = await r.json();
    if (r.ok) {
      status.textContent = `✓ ${j.table_count} tables, ${j.column_count} cols`;
      setTimeout(() => location.reload(), 800);
    } else {
      status.textContent = '✗ ' + (j.detail ?? JSON.stringify(j));
    }
  } catch(err) {
    status.textContent = '✗ ' + err.message;
  }
}
</script>
