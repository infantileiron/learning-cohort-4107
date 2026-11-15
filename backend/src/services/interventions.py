from fastapi import HTTPException
from src.models.entities import Intervention
from src.services import queue
from src.services.cleanup import all_purged
def draft(s,cohort,data):
 if cohort.state!='done':raise HTTPException(409,'队列计算完成后才能起草干预')
 row=next((r for r in cohort.result['rows'] if r['cohort_week']==data.cohort_week),None)
 if not row:raise HTTPException(404,'所选首学队列不在该冻结方案中')
 cell=next((c for c in row['cells'] if c['week_index']==data.week_index),None)
 if not cell or not cell['mature']:raise HTTPException(409,'未成熟或超出观察范围的周禁止生成干预')
 try:
  # 与清理受理共用一把锁：名单落库前重新读墓碑，受理后不再生成含该工号的新名单。
  with queue.cleanup_lock():
   gone=all_purged(s);members=[m for m in cell['missing'] if m not in gone]
   if not members:raise HTTPException(409,'该成熟周全部回访或成员均已清理，没有待干预成员')
   r=Intervention(**data.model_dump(),members=members);s.add(r);s.commit();return r
 except RuntimeError as e:raise HTTPException(503,str(e))
