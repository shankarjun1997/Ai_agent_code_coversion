<?php
/**
 * Server-Sent Events proxy — streams pipeline log updates to the browser.
 * Proxies the FastAPI SSE endpoint through PHP (avoids CORS issues from browser).
 */
require_once __DIR__ . '/config.php';

$run_id = $_GET['run_id'] ?? '';
if (!$run_id || !preg_match('/^[a-f0-9\-]{8,36}$/', $run_id)) {
    http_response_code(400);
    exit;
}

header('Content-Type: text/event-stream');
header('Cache-Control: no-cache');
header('X-Accel-Buffering: no');   // disable nginx buffering

// Open SSE stream from API
$ctx = stream_context_create(['http' => [
    'timeout'        => 300,
    'ignore_errors'  => true,
]]);

$stream = @fopen(API_BASE . "/api/pipeline/runs/$run_id/stream", 'r', false, $ctx);
if (!$stream) {
    echo "data: {\"error\": \"Failed to connect to API\"}\n\n";
    flush();
    exit;
}

while (!feof($stream)) {
    $line = fgets($stream);
    if ($line !== false) {
        echo $line;
        if (ob_get_level() > 0) ob_flush();
        flush();
    }
}
fclose($stream);
