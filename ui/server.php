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

$app->run([
    'worker_num'    => 2,
    'max_coroutine' => 3000,
]);
