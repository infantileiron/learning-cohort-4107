import logging
from src.config.database import Session
from src.models.entities import Cleanup,Cohort
from src.services import artifacts,queue
from src.services.analysis import calculate
from src.services.cleanup import all_purged,run_cleanup,scrub_result

def run_cohort(task_id):
 with Session() as s:
  row=s.get(Cohort,task_id)
  if not row or row.state!='queued':return
  snapshot=row.result['snapshot'];row.state='running';s.commit()
  try:
   result=calculate(snapshot)
   result['snapshot']=snapshot
   # 写回前在同一把清理锁内重新读墓碑：清理受理后旧计算进程不得把工号带回快照与成员明细。
   with queue.cleanup_lock():
    s.refresh(row)
    scrub_result(result,all_purged(s))
    row.result=result;row.state='done';row.error=''
    artifacts.write(str(row.id),row.result)
    s.commit()
  except Exception as e:
   s.rollback();row=s.get(Cohort,task_id)
   if not row:return
   if isinstance(e,RuntimeError) and '互斥等待超时' in str(e):
    # 清理正持锁：把计算任务放回队列，稍后重试，而不是把好方案标成失败。
    row.state='queued';row.error='';s.commit();queue.publish('cohort:jobs',row.id);return
   row.state='failed';row.error=str(e);s.commit()

def requeue_interrupted():
 with Session() as s:
  for pending in s.query(Cohort).filter(Cohort.state.in_(['queued','running'])).all():
   pending.state='queued';queue.publish('cohort:jobs',pending.id)
  for task in s.query(Cleanup).filter(Cleanup.status.in_(['queued','running'])).all():
   task.status='queued';queue.publish('cleanup:jobs',task.id)
  s.commit()

def run_cleanup_job(task_id):
 try:run_cleanup(task_id)
 except Exception:logging.exception('cleanup %s',task_id)
