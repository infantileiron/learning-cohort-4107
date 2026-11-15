import time,logging
from pathlib import Path
from src.services import queue
from src.services.jobs import requeue_interrupted,run_cohort,run_cleanup_job
requeue_interrupted()
while True:
 Path('/tmp/heartbeat').touch()
 try:
  item=queue.pop(['cleanup:jobs','cohort:jobs'],timeout=3)
  if not item:continue
  name,raw=item[0].decode(),item[1]
  if name=='cleanup:jobs':run_cleanup_job(int(raw))
  else:run_cohort(int(raw))
 except Exception:logging.exception('worker');time.sleep(2)
