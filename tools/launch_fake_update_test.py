from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading


SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))


FAKE_LATEST_VERSION = 'v9.9.10-test'
FAKE_CURRENT_VERSION = 'v1.2.0'


class FakeUpdateHandler(BaseHTTPRequestHandler):
    def _base_url(self) -> str:
        host, port = self.server.server_address
        return f'http://{host}:{port}'

    def _send(self, status_code: int, content_type: str, body: bytes) -> None:
        self.send_response(status_code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict) -> None:
        self._send(200, 'application/json', json.dumps(payload).encode('utf-8'))

    def _send_html(self, title: str, body: str) -> None:
        page = (
            '<!doctype html><html><head><meta charset="utf-8">'
            f'<title>{title}</title></head>'
            f'<body><h1>{title}</h1>{body}</body></html>'
        )
        self._send(200, 'text/html; charset=utf-8', page.encode('utf-8'))

    def do_GET(self) -> None:
        base_url = self._base_url()
        if self.path.endswith('/releases/latest'):
            self._send_json({
                'tag_name': FAKE_LATEST_VERSION,
                'html_url': f'{base_url}/releases/{FAKE_LATEST_VERSION}',
                'body': (
                    'Written by Codex:\n\n'
                    'These are intentionally long fake release notes. The app should not show this opening text.\n\n'
                    '<!-- update-summary:start -->\n'
                    '- Fake update check: proves the app can fetch release metadata from a remote endpoint.\n'
                    '- Fake summary extraction: this compact section is what the popup should show.\n'
                    '- Fake menu link: the menu-bar text should appear on the far right.\n'
                    '<!-- update-summary:end -->\n\n'
                    'Extra detailed notes that should stay out of the popup.\n'
                ),
            })
            return

        if self.path in ('/releases', f'/releases/{FAKE_LATEST_VERSION}'):
            self._send_html(
                'Fake TOTK Event Editor releases page',
                (
                    '<p>The in-app update link opened this local fake releases page.</p>'
                    f'<p>Latest fake version: <strong>{FAKE_LATEST_VERSION}</strong></p>'
                ),
            )
            return

        self._send(404, 'text/plain; charset=utf-8', b'Not found')

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer(('127.0.0.1', 0), FakeUpdateHandler)
    host, port = server.server_address
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    from eventeditor.__main__ import main as eventeditor_main

    sys.argv = [
        'eventeditor',
        '--update-check-url',
        f'http://{host}:{port}/repos/cargocult-mods/TOTK-event-editor/releases/latest',
        '--update-releases-url',
        f'http://{host}:{port}/releases',
        '--update-check-current-version',
        FAKE_CURRENT_VERSION,
        *sys.argv[1:],
    ]
    try:
        eventeditor_main()
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()
