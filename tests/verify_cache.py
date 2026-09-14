"""Quick verification: test /api/context cache performance."""
import sys, urllib.request, json, time
sys.path.insert(0, 'D:\\CONTINUUM')
from pathlib import Path
from server.auth import SessionAuthManager

mgr = SessionAuthManager(Path('D:\\CP'))
token = mgr.get_token()
print('Token:', (token[:16] + '...') if token else 'NOT FOUND')

if not token:
    print('ERROR: No token - daemon may not have started')
    sys.exit(1)

headers = {'X-Continuum-Token': token}

# Time the /api/context call
start = time.time()
req = urllib.request.Request('http://127.0.0.1:8765/api/context', headers=headers)
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
        elapsed = time.time() - start
        print('OK /api/context:', elapsed, 's')
        print('  files:', data['total_files'])
        print('  symbols:', data['total_symbols'])
        print('  cached:', data.get('cached', '?'))
        print('  languages:', list(data.get('languages', {}).keys())[:5])
except Exception as e:
    print('ERROR:', e)
    sys.exit(1)

print('ALL OK - Dashboard should load instantly now!')
