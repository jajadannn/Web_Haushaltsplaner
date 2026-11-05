import os, subprocess, uuid
from pathlib import Path
import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url
from app.config import Settings
url=make_url(Settings().database_url)
probe_db='fin_ki_test_'+uuid.uuid4().hex[:12]
admin=url.set(drivername='postgresql',database='postgres').render_as_string(hide_password=False)
with psycopg.connect(admin,autocommit=True) as c:c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(probe_db)))
try:
 env=dict(os.environ,TEST_DATABASE_URL=url.set(database=probe_db).render_as_string(hide_password=False))
 paths=sorted(str(p) for p in Path('tests/api').glob('test_ki_phase*.py'))+['tests/api/test_scenarios_recurring.py']
 r=subprocess.run(['.venv/bin/python','-m','pytest','-q',*paths],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
 Path('docs/pruefung-ki-2026-11-05/baseline-tests.log').write_text(r.stdout)
 print(r.stdout[-3500:]);print('exit_code',r.returncode)
finally:
 with psycopg.connect(admin,autocommit=True) as c:c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(probe_db)))
