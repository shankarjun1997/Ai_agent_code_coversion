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

$app->run([
    'worker_num'    => 2,
    'max_coroutine' => 3000,
]);
