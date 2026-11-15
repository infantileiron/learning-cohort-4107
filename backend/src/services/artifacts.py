import json,os,uuid
from pathlib import Path
def directory():
 return Path(os.environ.get('ARTIFACT_DIR','/artifacts'))
def path(key):
 return directory()/f'{key}.json'
def read(key):
 return json.loads(path(key).read_text(encoding='utf-8'))
def write(key,data):
 p=path(key);p.parent.mkdir(parents=True,exist_ok=True)
 tmp=p.with_name(f'.{p.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp')
 tmp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
 os.replace(tmp,p)
