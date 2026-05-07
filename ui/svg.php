<?php
/**
 * Serve a mapping SVG diagram from the shared output volume.
 * Files live at /app/output/diagrams/{mapping_id}.svg
 */
$id = preg_replace('/[^a-zA-Z0-9_-]/', '', $_GET['id'] ?? '');
if (!$id) {
    http_response_code(400);
    exit('Missing id');
}

$path = '/app/output/diagrams/' . $id . '.svg';
if (!file_exists($path)) {
    http_response_code(404);
    exit('SVG not found');
}

header('Content-Type: image/svg+xml');
header('Cache-Control: public, max-age=300');
readfile($path);
