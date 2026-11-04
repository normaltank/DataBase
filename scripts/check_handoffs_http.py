"""Real DOM→Flask handoffs, isolated files and no listening socket/provider."""
import base64
import io
import json
import subprocess
import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from platform_app.web import create_app


def main():
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='handoff112-dom-') as temp:
        app = create_app(Path(temp) / 'data', testing=True, embedded_worker=False)
        client = app.test_client()
        process = subprocess.Popen(['node', str(root / 'scripts/check_handoffs_http.js')], cwd=root,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        summary = None
        try:
            for line in process.stdout:
                request = json.loads(line)
                if request.get('done'):
                    summary = request
                    break
                options = {'headers': {'X-CSRF-Token': client.get('/api/session').json['csrf']}}
                if request.get('file'):
                    file = request['file']
                    options['data'] = {'data':json.dumps(request['body']), 'file':(io.BytesIO(base64.b64decode(file['base64'])), file['name'])}
                elif request.get('body') is not None:
                    options['json'] = request['body']
                response = client.open(request['url'], method=request.get('method', 'GET'), **options)
                payload = response.json if response.is_json else {'base64':base64.b64encode(response.data).decode()}
                response.close()
                try:
                    process.stdin.write(json.dumps({'id': request['id'], 'status':response.status_code,'body':payload})+'\n')
                    process.stdin.flush()
                except OSError:
                    raise AssertionError(process.stderr.read()) from None
            process.wait(timeout=10)
            assert process.returncode == 0 and summary, process.stderr.read()
            print(json.dumps(summary, ensure_ascii=False))
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)


if __name__ == '__main__':
    main()
