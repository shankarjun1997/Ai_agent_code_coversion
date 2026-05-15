<?php // views/batch_new.php — expects $sources, $targets, $api_ext ?>
<div class="page-header">
  <h1>New Batch</h1>
  <p>Select a source catalog and tables, pick a target catalog, add business context, then preview the payload.</p>
</div>

<div class="alert alert-warn">
  Phase 2 pending. POST /api/stm/batches not yet implemented. Preview shows intended payload.
</div>

<div class="split">

  <!-- ── Left: source selector + table checkboxes ── -->
  <div>
    <div class="card">
      <h2>Source</h2>
      <div class="form-row">
        <label>Source Catalog</label>
        <select id="source-select">
          <option value="">-- select source catalog --</option>
          <?php foreach ($sources as $s): ?>
          <option value="<?= htmlspecialchars($s['id']) ?>">
            <?= htmlspecialchars($s['catalog_name']) ?>
            (<?= (int)$s['table_count'] ?> tables)
          </option>
          <?php endforeach; ?>
        </select>
      </div>
    </div>

    <div class="card" id="tables-card" style="display:none">
      <h3>Select Tables</h3>
      <div id="tables-loading" style="font-size:12px;color:var(--muted);display:none">Loading…</div>
      <div id="tables-list"></div>
    </div>
  </div>

  <!-- ── Right: target selector + context + preview ── -->
  <div>
    <div class="card">
      <h2>Target &amp; Context</h2>
      <div class="form-row">
        <label>Target Catalog</label>
        <select id="target-select">
          <option value="">-- select target catalog --</option>
          <?php foreach ($targets as $t): ?>
          <option value="<?= htmlspecialchars($t['id']) ?>">
            <?= htmlspecialchars($t['project'] . '.' . $t['dataset']) ?>
            (<?= (int)$t['table_count'] ?> tables)
          </option>
          <?php endforeach; ?>
        </select>
      </div>
      <div class="form-row">
        <label>Business Context</label>
        <textarea id="business-context" rows="5"
          placeholder="Describe the business purpose of this mapping batch. e.g. Migrate Frontier raw tables to BigQuery vz_raw_dev for regulatory reporting."></textarea>
      </div>
      <button class="btn btn-primary" type="button" onclick="previewPayload()">Preview Payload</button>
    </div>

    <div class="card" id="preview-card" style="display:none">
      <h3>Intended Payload</h3>
      <pre id="preview-json" style="font-size:11px;overflow-x:auto;white-space:pre-wrap;word-break:break-all"></pre>
    </div>
  </div>

</div>

<script>
const API_EXT = '<?= htmlspecialchars($api_ext) ?>';

document.getElementById('source-select').addEventListener('change', function() {
  const id = this.value;
  const tablesCard = document.getElementById('tables-card');
  const tablesList = document.getElementById('tables-list');
  const loading    = document.getElementById('tables-loading');

  if (!id) {
    tablesCard.style.display = 'none';
    tablesList.innerHTML = '';
    return;
  }

  tablesCard.style.display = '';
  tablesList.innerHTML = '';
  loading.style.display = '';

  fetch(API_EXT + '/api/catalogs/source/' + encodeURIComponent(id))
    .then(r => r.json())
    .then(data => {
      loading.style.display = 'none';
      const tables = data.tables ?? [];
      if (tables.length === 0) {
        tablesList.innerHTML = '<p style="font-size:12px;color:var(--muted)">No tables found in this catalog.</p>';
        return;
      }
      const html = tables.map(t => {
        const name = typeof t === 'string' ? t : (t.table_name ?? t.name ?? JSON.stringify(t));
        const esc  = name.replace(/"/g, '&quot;').replace(/</g, '&lt;');
        return `<label style="display:flex;gap:8px;align-items:center;padding:4px 0;font-size:12px;color:var(--text);text-transform:none;letter-spacing:normal">
          <input type="checkbox" name="tables" value="${esc}" style="width:auto">
          ${esc}
        </label>`;
      }).join('');
      tablesList.innerHTML = html;
    })
    .catch(err => {
      loading.style.display = 'none';
      tablesList.innerHTML = '<p style="font-size:12px;color:var(--danger)">' + err.message + '</p>';
    });
});

function previewPayload() {
  const sourceId  = document.getElementById('source-select').value;
  const targetId  = document.getElementById('target-select').value;
  const context   = document.getElementById('business-context').value.trim();
  const checked   = Array.from(document.querySelectorAll('input[name="tables"]:checked')).map(c => c.value);

  const payload = {
    source_catalog_id: sourceId || null,
    target_catalog_id: targetId || null,
    tables: checked,
    business_context: context || null,
  };

  document.getElementById('preview-json').textContent = JSON.stringify(payload, null, 2);
  document.getElementById('preview-card').style.display = '';
}
</script>
