"""Safe online backup of the SQLite database into the backups folder (keeps the newest 30)."""
import os, sqlite3, sys, time
base = os.path.dirname(os.path.abspath(__file__))
src = os.path.join(base, 'hr_portal.db'); out = os.path.join(base, 'backups'); os.makedirs(out, exist_ok=True)
if not os.path.exists(src): sys.exit('hr_portal.db not found')
dst = os.path.join(out, 'hr_portal_' + time.strftime('%Y%m%d_%H%M%S') + '.db')
a, b = sqlite3.connect(src), sqlite3.connect(dst); a.backup(b); b.close(); a.close()
for f in sorted(os.listdir(out))[:-30]: os.remove(os.path.join(out, f))
print('Backup saved:', dst)
