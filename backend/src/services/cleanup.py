import json
from datetime import datetime,timezone
from sqlalchemy.orm.attributes import flag_modified
from src.config.database import Session
from src.models.entities import Cleanup,PurgedLearner,Event,Cohort,Intervention
from src.services import artifacts

# 清理只移除工号身份；冻结矩阵里的人数与比例是历史值，绝不重算。
_DROP=object()

def now():return datetime.now(timezone.utc).isoformat(timespec='seconds')
def all_purged(s):return {row.learner for row in s.query(PurgedLearner).all()}
def is_purged(s,learner):return s.query(PurgedLearner.id).filter_by(learner=learner).first() is not None

def deep_contains(value,learner,parent_is_list=False):
 # 与 scrub 口径一致：只把 learner 字段和名单数组里的工号视为身份；
 # 配置里的普通字符串（哪怕恰好同名）不算副本残留。
 if isinstance(value,dict):
  return value.get('learner')==learner or any(deep_contains(v,learner,False) for v in value.values())
 if isinstance(value,list):return any(deep_contains(v,learner,True) for v in value)
 if parent_is_list and isinstance(value,str):return value==learner
 return False

def _scrub(value,learners,parent_is_list=False):
 if isinstance(value,list):
  out=[]
  for item in value:
   cleaned=_scrub(item,learners,True)
   if cleaned is not _DROP:out.append(cleaned)
  return out
 if isinstance(value,dict):
  if value.get('learner') in learners:return _DROP
  out={}
  for key,item in value.items():
   cleaned=_scrub(item,learners,False)
   if cleaned is not _DROP:out[key]=cleaned
  return out
 # 只有名单类数组里的工号会被丢弃；普通字段不做字符串替换，避免误改冻结配置。
 if parent_is_list and isinstance(value,str) and value in learners:return _DROP
 return value

def scrub_result(result,learners):
 # 只去掉工号身份与其成员明细；learners/size/active/rate/event_count 等历史聚合保持原值。
 if not learners or not isinstance(result,dict):return result
 cleaned=_scrub(result,learners)
 if isinstance(cleaned,dict):
  result.clear();result.update(cleaned)
 return result

def artifact_contains(key,learner):
 p=artifacts.path(key)
 if not p.exists():return False
 try:return deep_contains(artifacts.read(key),learner)
 except (ValueError,UnicodeDecodeError):return learner in p.read_text(encoding='utf-8',errors='replace')

def _copy(kind,ref,label):
 return {'key':kind if ref is None else f'{kind}:{ref}','kind':kind,'ref':'' if ref is None else str(ref),'label':label,'status':'pending','detail':'待清理'}

def _artifact_keys():
 return [p.stem for p in sorted(artifacts.directory().glob('*.json')) if not p.stem.startswith('.')]

def scan(s,learner):
 copies=[]
 if s.query(Event.id).filter_by(learner=learner).first():copies.append(_copy('events',None,'原始学习事件'))
 for row in s.query(Cohort).order_by(Cohort.id).all():
  if deep_contains(row.result,learner):copies.append(_copy('cohort',row.id,f'队列快照与成员明细 #{row.id}'))
 for key in _artifact_keys():
  if artifact_contains(key,learner):copies.append(_copy('artifact',key,f'共享结果文件 #{key}'))
 for row in s.query(Intervention).order_by(Intervention.id).all():
  if deep_contains(row.members,learner):copies.append(_copy('intervention',row.id,f'干预名单 #{row.id}'))
 return copies

def _process(s,task,copy,learners):
 learner=task.learner;kind=copy['kind'];ref=copy['ref']
 if kind=='events':
  n=s.query(Event).filter(Event.learner==learner).delete(synchronize_session=False)
  return f'删除 {n} 条原始学习事件，工号原文不再保留'
 if kind=='cohort':
  row=s.query(Cohort).filter_by(id=int(ref)).with_for_update().first()
  if not row:return '队列快照已不存在，按已清理处理'
  before=deep_contains(row.result,learner)
  if row.result is not None:
   scrub_result(row.result,learners);flag_modified(row,'result')
  return '队列快照与成员明细已移除该工号；留存人数与比例保持冻结原值' if before else '队列快照已无该工号'
 if kind=='artifact':
  p=artifacts.path(ref)
  if not p.exists():return '共享结果文件不存在，按已清理处理'
  try:
   data=artifacts.read(ref);before=deep_contains(data,learner)
  except (ValueError,UnicodeDecodeError):
   # 写文件后中断可能留下不完整内容：按该队列的冻结结果重建，保证工号不残留。
   row=s.query(Cohort).filter_by(id=int(ref)).first() if str(ref).isdigit() else None
   if not row or not isinstance(row.result,dict):raise ValueError('共享结果文件损坏且无法按冻结结果重建')
   data=json.loads(json.dumps(row.result));before=True
   scrub_result(data,learners);artifacts.write(ref,data)
   return '共享结果文件不完整，已按冻结结果重建并移除该工号'
  scrub_result(data,learners);artifacts.write(ref,data)
  return '共享结果文件已重写并移除该工号' if before else '共享结果文件已无该工号'
 if kind=='intervention':
  row=s.query(Intervention).filter_by(id=int(ref)).with_for_update().first()
  if not row:return '干预名单已不存在，按已清理处理'
  before=deep_contains(row.members,learner)
  row.members=[m for m in (row.members or []) if m not in learners]
  flag_modified(row,'members')
  return '干预名单已同步移除该工号' if before else '干预名单已无该工号'
 raise ValueError(f'未知副本类型 {kind}')

def _fail(s,task,key,message):
 copies=list(task.copies or [])
 for copy in copies:
  if copy.get('key')==key:
   copy['status']='failed';copy['detail']=message[:500]
 task.copies=copies;flag_modified(task,'copies')
 task.status='failed';task.error=f'副本「{key}」处理失败：{message}'[:1000]
 s.commit()

def run_cleanup(task_id):
 from src.services import queue
 with Session() as s:
  task=s.get(Cleanup,task_id)
  if not task or task.status=='done':return
  task.status='running';s.commit()
  verify_rounds=0
  while True:
   task=s.get(Cleanup,task_id)
   if not task:return
   copies=list(task.copies or [])
   pending=next((c for c in copies if c.get('status')!='done'),None)
   if pending:
    key=pending['key']
    try:
     # 与计算写回共用一把锁：逐副本处理期间不会被旧计算进程插队写回。
     with queue.cleanup_lock():
      s.expire_all()
      learners=all_purged(s)
      detail=_process(s,task,pending,learners)
      for copy in copies:
       if copy.get('key')==key:copy['status']='done';copy['detail']=detail
      task.copies=copies;flag_modified(task,'copies');task.error=''
      s.commit()
    except Exception as e:
     s.rollback();task=s.get(Cleanup,task_id)
     if not task:return
     _fail(s,task,key,str(e) or e.__class__.__name__)
     return
    continue
   # 所有计划副本处理完后再全量校验，防止旧计算进程并发写回把工号带回来。
   try:
    with queue.cleanup_lock():
     s.expire_all()  # expire_on_commit=False，校验前必须丢弃身份映射里的旧值
     found=scan(s,task.learner)
   except Exception as e:
    _fail(s,task,'verify',str(e) or e.__class__.__name__);return
   if found:
    verify_rounds+=1
    if verify_rounds>5:
     _fail(s,task,'verify','清理校验多次仍发现该工号，请重试')
     return
    copies=list(task.copies or []);index={c.get('key'):c for c in copies};changed=False
    for copy in found:
     if copy['key'] in index:
      if index[copy['key']].get('status')!='pending':
       index[copy['key']]['status']='pending';index[copy['key']]['detail']='校验发现该工号重新出现，重新处理';changed=True
     else:
      copies.append(copy);changed=True
    if changed:
     task.copies=copies;flag_modified(task,'copies');s.commit()
    continue
   task.status='done';task.completed_at=now();task.error='';s.commit()
   return

def _reset_copies(copies,message='重试待清理'):
 return [dict(c,status='pending',detail=message) if c.get('status')=='failed' else dict(c) for c in copies or []]

def request(s,learner,reason,actor):
 from fastapi import HTTPException
 from src.services import queue
 learner=(learner or '').strip()
 # 受理与计算写回共用同一把跨进程锁：墓碑提交先于回写时，回写方重新读墓碑即可拦住。
 with queue.cleanup_lock():
  task=s.query(Cleanup).filter_by(learner=learner).with_for_update().first()
  created=False
  if not task:
   copies=scan(s,learner)
   if not copies:
    raise HTTPException(404,'未找到该工号的学习事件或队列副本，请核对工号')
   if not is_purged(s,learner):
    s.add(PurgedLearner(learner=learner,requested_at=now(),requested_by=actor));s.flush()
   task=Cleanup(learner=learner,reason=reason,status='queued',copies=copies,requested_by=actor,requested_at=now())
   s.add(task);s.commit();created=True
  elif task.status in ('queued','running'):
   # 重复受理/中断后续跑：重新入队让 worker 从未完成的副本继续，已清理副本会被跳过。
   queue.publish('cleanup:jobs',task.id)
   return task,False
  elif task.status=='failed':
   task.copies=_reset_copies(task.copies);task.status='queued';task.error='';task.completed_at=None;s.commit()
  elif task.status=='done':
   found=scan(s,learner)
   if not found:return task,False
   copies=list(task.copies or []);index={c.get('key') for c in copies}
   for copy in found:
    if copy['key'] in index:
     for c in copies:
      if c.get('key')==copy['key']:c['status']='pending';c['detail']='校验发现该工号重新出现，重新处理'
    else:copies.append(copy)
   task.copies=copies;task.status='queued';task.error='';task.completed_at=None;s.commit()
  else:
   task.status='queued';s.commit()
  try:queue.publish('cleanup:jobs',task.id)
  except Exception:
   task.status='failed';task.error='清理任务队列暂不可用，请稍后重试';s.commit()
   raise HTTPException(503,task.error)
  return task,created
