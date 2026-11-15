import json
from fastapi import APIRouter,Depends,HTTPException,Response
from sqlalchemy.exc import IntegrityError
from src.config.database import db
from src.models.entities import User,Event,Cohort,Intervention,Audit,Cleanup
from src.schemas.business import Login,EventInput,CohortInput,InterventionInput,NoteInput,CleanupInput
from src.middlewares.auth import current,editor,admin
from src.utils.security import verify,token
from src.services.business import audit,dump
from src.services import queue
from src.services.interventions import draft
from src.services.cleanup import is_purged,request as request_cleanup
from src.controllers.business import ensure_cohort,ensure_intervention,ensure_cleanup
router=APIRouter()
@router.post('/auth/login')
def login(data:Login,s=Depends(db)):
 u=s.query(User).filter_by(email=data.email).first()
 if not u or not verify(data.password,u.password):raise HTTPException(401,'账号或密码错误')
 return {'token':token(u),'user':dump(u)}
@router.get('/me')
def me(u=Depends(current)):return dump(u)
@router.get('/events')
def events(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Event).order_by(Event.id.desc()).all()]
@router.post('/events')
def event(data:EventInput,u=Depends(editor),s=Depends(db)):
 try:
  # 与清理受理共用一把锁：墓碑读取与事件落库相对清理受理/校验是线性化的。
  with queue.cleanup_lock():
   if is_purged(s,data.learner):raise HTTPException(409,'该工号已按离职清理，原始事件不再保留，不能重新录入')
   existing=s.query(Event).filter_by(code=data.code).first()
   if existing:
    if all(getattr(existing,k)==v for k,v in data.model_dump().items()):return dump(existing)
    raise HTTPException(409,'同事件编号的内容冲突，请修订原记录或使用新编号')
   r=Event(**data.model_dump());s.add(r)
   try:s.commit()
   except IntegrityError:
    s.rollback();other=s.query(Event).filter_by(code=data.code).first()
    if other and all(getattr(other,k)==v for k,v in data.model_dump().items()):return dump(other)
    raise HTTPException(409,'同事件编号的内容冲突')
  audit(s,u,'录入学习事件 '+r.code);return dump(r)
 except RuntimeError as e:raise HTTPException(503,str(e))
@router.put('/events/{i}')
def edit_event(i:int,data:EventInput,u=Depends(editor),s=Depends(db)):
 try:
  with queue.cleanup_lock():
   r=s.get(Event,i)
   if not r:raise HTTPException(404,'事件不存在')
   if is_purged(s,r.learner) or is_purged(s,data.learner):raise HTTPException(409,'该工号已按离职清理，不能修订或重新绑定事件')
   for k,v in data.model_dump().items():setattr(r,k,v)
   try:s.commit()
   except IntegrityError:s.rollback();raise HTTPException(409,'事件编号重复')
  audit(s,u,'修订学习事件 '+str(i));return dump(r)
 except RuntimeError as e:raise HTTPException(503,str(e))
@router.get('/cohorts')
def cohorts(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Cohort).order_by(Cohort.id.desc()).all()]
@router.post('/cohorts')
def cohort(data:CohortInput,u=Depends(editor),s=Depends(db)):
 from src.services.cleanup import all_purged
 cfg=data.model_dump(mode='json')
 try:
  with queue.cleanup_lock():
   gone=all_purged(s)
   snapshot={'config':cfg,'events':[dump(r) for r in s.query(Event).order_by(Event.id).all() if r.learner not in gone]};r=Cohort(**cfg,result={'snapshot':snapshot});s.add(r);s.commit()
 except RuntimeError as e:raise HTTPException(503,str(e))
 try:queue.publish('cohort:jobs',r.id)
 except Exception:r.state='failed';r.error='队列暂不可用，请稍后重试';s.commit();raise HTTPException(503,r.error)
 audit(s,u,'提交留存队列 '+str(r.id));return dump(r)
@router.get('/cohorts/{i}')
def detail(i:int,u=Depends(current),s=Depends(db)):return dump(ensure_cohort(s,i))
@router.get('/cohorts/{i}/export')
def export(i:int,u=Depends(current),s=Depends(db)):
 r=ensure_cohort(s,i)
 if r.state!='done':raise HTTPException(409,'计算成功后才能导出')
 return Response(json.dumps(dump(r),ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="learning-cohort-{i}.json"'})
@router.get('/interventions')
def interventions(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Intervention).order_by(Intervention.id.desc()).all()]
@router.post('/interventions')
def intervention(data:InterventionInput,u=Depends(editor),s=Depends(db)):
 r=draft(s,ensure_cohort(s,data.cohort_id),data);audit(s,u,'生成干预清单 '+str(r.id));return dump(r)
@router.put('/interventions/{i}')
def edit_intervention(i:int,data:NoteInput,u=Depends(editor),s=Depends(db)):
 r=ensure_intervention(s,i)
 if r.status!='draft':raise HTTPException(409,'已签核清单不可修改')
 r.note=data.note;s.commit();audit(s,u,'修订干预说明 '+str(i));return dump(r)
@router.post('/interventions/{i}/approve')
def approve(i:int,u=Depends(admin),s=Depends(db)):
 r=ensure_intervention(s,i)
 if r.status!='draft':raise HTTPException(409,'已签核，不可重复签核')
 r.status='approved';s.commit();audit(s,u,'签核干预清单 '+str(i));return dump(r)
@router.get('/interventions/{i}/export')
def action_export(i:int,u=Depends(current),s=Depends(db)):
 r=ensure_intervention(s,i);return dump(r)
@router.get('/cleanups')
def cleanups(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Cleanup).order_by(Cleanup.id.desc()).all()]
@router.post('/cleanups',status_code=201)
def create_cleanup(data:CleanupInput,response:Response,u=Depends(admin),s=Depends(db)):
 try:task,created=request_cleanup(s,data.learner,data.reason,u.email)
 except RuntimeError as e:raise HTTPException(503,str(e))
 if not created:response.status_code=200
 if created:audit(s,u,f'受理离职工号清理 {task.learner}')
 return dump(task)
@router.get('/cleanups/{i}')
def cleanup_detail(i:int,u=Depends(current),s=Depends(db)):return dump(ensure_cleanup(s,i))
@router.get('/audits')
def audits(u=Depends(admin),s=Depends(db)):return [dump(r) for r in s.query(Audit).order_by(Audit.id.desc()).limit(100)]
