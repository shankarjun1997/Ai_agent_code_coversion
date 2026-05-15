<?php
require_once __DIR__ . '/vendor/autoload.php';
require_once __DIR__ . '/src/helpers.php';

use ZealPHP\App;

// superglobals(false) must be called before App::init()
// It enables coroutine-safe mode without uopz superglobal hooks
App::superglobals(false);

$app = App::init('0.0.0.0', 8080);

$app->route('/', ['methods' => ['GET']], function() {
    return ['status' => 'ok', 'service' => 'sqlgen-ui'];
});

$app->route('/catalog', ['methods' => ['GET']], function($request, $response) {
    $sources = [];
    $targets = [];
    $source_detail = null;
    $target_detail = null;
    $upload_error = null;
    $refresh_error = null;

    try { $sources = api_get('/api/catalogs/source')['catalogs'] ?? []; }
    catch (\Throwable $e) { $upload_error = 'Could not load source catalogs: ' . $e->getMessage(); }

    try { $targets = api_get('/api/catalogs/target')['catalogs'] ?? []; }
    catch (\Throwable $e) { $refresh_error = 'Could not load target catalogs: ' . $e->getMessage(); }

    $sid = $request->get['source_id'] ?? null;
    if ($sid) {
        try { $source_detail = api_get('/api/catalogs/source/' . urlencode($sid)); }
        catch (\Throwable $e) { $upload_error = 'Could not load catalog detail.'; }
    }

    $tid = $request->get['target_id'] ?? null;
    if ($tid) {
        try { $target_detail = api_get('/api/catalogs/target/' . urlencode($tid)); }
        catch (\Throwable $e) { $refresh_error = 'Could not load target detail.'; }
    }

    $html = render('catalog', [
        'title'         => 'Catalog Browser',
        'page'          => 'catalog',
        'sources'       => $sources,
        'targets'       => $targets,
        'source_detail' => $source_detail,
        'target_detail' => $target_detail,
        'upload_error'  => $upload_error,
        'refresh_error' => $refresh_error,
        'api_ext'       => API_EXTERNAL,
    ]);
    $response->header('Content-Type', 'text/html; charset=utf-8');
    $response->end($html);
});

$app->route('/batch/new', ['methods' => ['GET']], function($request, $response) {
    $sources = [];
    $targets = [];
    $error   = null;

    try { $sources = api_get('/api/catalogs/source')['catalogs'] ?? []; }
    catch (\Throwable $e) { $error = 'Could not load source catalogs: ' . $e->getMessage(); }

    try { $targets = api_get('/api/catalogs/target')['catalogs'] ?? []; }
    catch (\Throwable $e) { $error = ($error ? $error . ' ' : '') . 'Could not load target catalogs: ' . $e->getMessage(); }

    $html = render('batch_new', [
        'title'   => 'New Batch',
        'page'    => 'batch_new',
        'sources' => $sources,
        'targets' => $targets,
        'api_ext' => API_EXTERNAL,
    ]);
    $response->header('Content-Type', 'text/html; charset=utf-8');
    $response->end($html);
});

$app->route('/batch/{id}', ['methods' => ['GET']], function($id, $response) {
    $html = render('batch_show', [
        'title'    => 'Batch Dashboard',
        'page'     => 'batch_show',
        'batch_id' => $id,
        'api_ext'  => API_EXTERNAL,
    ]);
    $response->header('Content-Type', 'text/html; charset=utf-8');
    $response->end($html);
});

$app->route('/session/{id}', ['methods' => ['GET']], function($id, $response) {
    $session = null;
    try { $session = api_get('/api/stm/sessions/' . urlencode($id)); }
    catch (\Throwable $e) { /* session data unavailable — render stub */ }

    $html = render('session', [
        'title'      => 'Session Stepper',
        'page'       => 'session',
        'session_id' => $id,
        'session'    => $session,
        'api_ext'    => API_EXTERNAL,
    ]);
    $response->header('Content-Type', 'text/html; charset=utf-8');
    $response->end($html);
});

$app->route('/queue', ['methods' => ['GET']], function($response) {
    $sessions      = [];
    $pending_count = 0;

    try {
        $sessions = api_get('/api/stm/sessions')['sessions'] ?? [];
        $pending_count = count(array_filter($sessions, function($s) {
            return in_array($s['status'] ?? '', ['awaiting_gate_1', 'awaiting_gate_2'], true);
        }));
    }
    catch (\Throwable $e) { /* render with empty list */ }

    $html = render('queue', [
        'title'         => 'Review Queue',
        'page'          => 'queue',
        'sessions'      => $sessions,
        'pending_count' => $pending_count,
    ]);
    $response->header('Content-Type', 'text/html; charset=utf-8');
    $response->end($html);
});

$app->run([
    'worker_num'    => 2,
    'max_coroutine' => 3000,
]);
