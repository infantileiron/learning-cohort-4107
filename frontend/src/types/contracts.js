/** @typedef {{id:number,code:string,learner:string,occurred_at:string,course:string,note:string}} Event */
/** @typedef {{id:number,name:string,start_week:string,end_week:string,as_of:string,horizon:number,state:string,result:object}} Cohort */
/** @typedef {{id:number,cohort_id:number,cohort_week:string,week_index:number,members:string[],note:string,status:string}} Intervention */
/** @typedef {{key:string,kind:'events'|'cohort'|'artifact'|'intervention',ref:string,label:string,status:'pending'|'done'|'failed',detail:string}} CleanupCopy */
/** @typedef {{id:number,learner:string,reason:string,status:'queued'|'running'|'done'|'failed',copies:CleanupCopy[],error:string,requested_by:string,requested_at:string,completed_at:string|null}} Cleanup */
