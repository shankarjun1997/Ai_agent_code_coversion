<?php
define('STM_SKIP_AUTH_GATE', true);
require_once __DIR__ . '/config.php';
require_once __DIR__ . '/auth.php';
$user = stm_auth_user();
if ($user) { header('Location: /index.php'); exit; }

$err = '';
$next = $_GET['next'] ?? $_POST['next'] ?? '/index.php';

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $mode      = $_POST['mode']        ?? 'demo';
    $tenant    = trim($_POST['tenant'] ?? 'demo');
    $email     = trim($_POST['email']  ?? '');
    $password  = $_POST['password']    ?? '';

    if ($mode === 'demo') {
        // No DB required — call /api/auth/demo-login
        $resp = api_post('/api/auth/demo-login', [
            'tenant_slug' => $tenant ?: 'demo',
            'email'       => $email  ?: 'demo@acme.com',
        ]);
        if (!empty($resp['access_token'])) {
            stm_auth_login_with_token($resp['access_token'], [
                'user_id'      => 'demo-user',
                'tenant_id'    => 'tenant-' . ($tenant ?: 'demo'),
                'tenant_slug'  => $tenant ?: 'demo',
                'email'        => $email ?: 'demo@acme.com',
                'role'         => 'admin',
            ]);
            header('Location: ' . $next);
            exit;
        }
        $err = 'Demo login failed: ' . (is_array($resp) ? json_encode($resp) : (string)$resp);
    } else {
        // Real /api/auth/login — requires platform DB
        $resp = api_post('/api/auth/login', compact('email','password'));
        if (!empty($resp['access_token'])) {
            stm_auth_login_with_token($resp['access_token'], [
                'user_id'      => 'real-user',
                'tenant_id'    => '',
                'tenant_slug'  => $tenant,
                'email'        => $email,
                'role'         => 'admin',
            ]);
            header('Location: ' . $next);
            exit;
        }
        $err = $resp['detail'] ?? json_encode($resp);
    }
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title><?= APP_TITLE ?> — Sign in</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Syne:wght@600;700;800&family=Inter:wght@400;500;600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    body { font-family: 'Inter', system-ui, sans-serif; }
    h1, h2, .display { font-family: 'Syne', sans-serif; }
    code, .mono { font-family: 'DM Mono', monospace; }
    .ice-gradient {
      background:
        radial-gradient(800px 500px at 20% 10%, #E0F2FE 0%, transparent 60%),
        radial-gradient(700px 400px at 80% 90%, #DBEAFE 0%, transparent 60%),
        linear-gradient(180deg, #FFFFFF 0%, #F8FAFC 100%);
    }
    .card-shadow { box-shadow: 0 1px 2px rgba(15,23,42,.04), 0 10px 30px rgba(15,23,42,.06); }
    .pill { display:inline-block; background:#E0F2FE; color:#0369A1; font-size:11px; padding:2px 8px; border-radius:9999px; font-weight:600; letter-spacing:.02em; }
    input, select { transition: box-shadow .15s ease; }
    input:focus, select:focus { outline:none; box-shadow: 0 0 0 3px rgba(14,165,233,.18); border-color:#0EA5E9 !important; }
    .btn-ice { background:#0EA5E9; color:white; }
    .btn-ice:hover { background:#0369A1; }
    .seg { display:inline-flex; background:#F1F5F9; border-radius:8px; padding:3px; }
    .seg button { padding:6px 14px; border-radius:6px; font-size:13px; font-weight:500; color:#475569; }
    .seg button.on { background:white; color:#0F172A; box-shadow: 0 1px 2px rgba(15,23,42,.06); }
  </style>
</head>
<body class="ice-gradient min-h-screen flex items-center justify-center px-4">
<div class="w-full max-w-md">
  <div class="text-center mb-8">
    <div class="inline-flex items-center gap-2 mb-3">
      <span class="text-2xl">⚡</span>
      <span class="display text-2xl font-bold tracking-tight" style="color:#0F172A;">SQL-Gen</span>
    </div>
    <h1 class="display text-3xl font-bold" style="color:#0F172A;">Mapping Agent Platform</h1>
    <p class="text-sm mt-2" style="color:#475569;">AI-powered source-to-target mappings, governed by your team.</p>
  </div>

  <div class="bg-white rounded-xl p-6 card-shadow border" style="border-color:#E2E8F0;">
    <form method="POST" x-data="{ mode: 'demo' }">
      <input type="hidden" name="next"  value="<?= htmlspecialchars($next) ?>">
      <input type="hidden" name="mode" :value="mode">

      <div class="flex items-center justify-between mb-4">
        <h2 class="text-base font-semibold" style="color:#0F172A;">Sign in</h2>
        <div class="seg">
          <button type="button" :class="mode==='demo' ? 'on' : ''" @click="mode='demo'">Demo</button>
          <button type="button" :class="mode==='real' ? 'on' : ''" @click="mode='real'">Real</button>
        </div>
      </div>

      <?php if ($err): ?>
        <div class="rounded-lg px-3 py-2 mb-3 text-sm" style="background:#FEF2F2; color:#991B1B; border:1px solid #FCA5A5;">
          <?= htmlspecialchars($err) ?>
        </div>
      <?php endif; ?>

      <label class="block text-xs font-medium mb-1" style="color:#475569;">Tenant slug</label>
      <input name="tenant" required value="demo"
             class="w-full border rounded-lg px-3 py-2 text-sm font-mono mb-3"
             style="border-color:#E2E8F0;" placeholder="demo">

      <label class="block text-xs font-medium mb-1" style="color:#475569;">Email</label>
      <input name="email" type="email" required value="demo@acme.com"
             class="w-full border rounded-lg px-3 py-2 text-sm mb-3"
             style="border-color:#E2E8F0;" placeholder="you@company.com">

      <div x-show="mode === 'real'">
        <label class="block text-xs font-medium mb-1" style="color:#475569;">Password</label>
        <input name="password" type="password"
               class="w-full border rounded-lg px-3 py-2 text-sm mb-3"
               style="border-color:#E2E8F0;" placeholder="••••••••">
      </div>

      <button type="submit" class="btn-ice w-full py-2.5 rounded-lg font-medium text-sm">
        Sign in →
      </button>

      <div class="text-xs mt-4 text-center" style="color:#94A3B8;">
        <span x-show="mode === 'demo'">Demo mode issues a session JWT without touching the platform DB. Safe for stakeholder walkthroughs.</span>
        <span x-show="mode === 'real'">Real mode hits <code class="text-[10px]">POST /api/auth/login</code>. Requires the platform DB to be reachable.</span>
      </div>
    </form>
  </div>

  <div class="mt-4 text-center">
    <span class="pill">multi-tenant</span>
    <span class="pill" style="margin-left:4px;">JWT</span>
    <span class="pill" style="margin-left:4px;">DeepSeek</span>
    <span class="pill" style="margin-left:4px;">BigQuery</span>
  </div>
</div>
<script defer src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js"></script>
</body>
</html>
