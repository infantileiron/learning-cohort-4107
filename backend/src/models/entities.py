from sqlalchemy import Column,Integer,String,JSON,Text,ForeignKey
from src.config.database import Base
class User(Base):
 __tablename__='users'
 id=Column(Integer,primary_key=True);email=Column(String(100),unique=True,nullable=False);password=Column(String(200));role=Column(String(20))
class Event(Base):
 __tablename__='events'
 id=Column(Integer,primary_key=True);code=Column(String(60),unique=True,nullable=False);learner=Column(String(60),nullable=False,index=True);occurred_at=Column(String(40),nullable=False);course=Column(String(40));note=Column(Text,default='')
class Cohort(Base):
 __tablename__='cohorts'
 id=Column(Integer,primary_key=True);name=Column(String(100));start_week=Column(String(10));end_week=Column(String(10));as_of=Column(String(10));horizon=Column(Integer);state=Column(String(20),default='queued');result=Column(JSON,nullable=True);error=Column(Text,default='')
class Intervention(Base):
 __tablename__='interventions'
 id=Column(Integer,primary_key=True);cohort_id=Column(Integer,ForeignKey('cohorts.id'));cohort_week=Column(String(10));week_index=Column(Integer);note=Column(Text);members=Column(JSON);status=Column(String(20),default='draft')
class Audit(Base):
 __tablename__='audits'
 id=Column(Integer,primary_key=True);actor=Column(String(100));action=Column(String(200));created=Column(String(40))
class PurgedLearner(Base):
 __tablename__='purged_learners'
 id=Column(Integer,primary_key=True);learner=Column(String(60),unique=True,nullable=False,index=True);requested_at=Column(String(40));requested_by=Column(String(100))
class Cleanup(Base):
 __tablename__='cleanups'
 id=Column(Integer,primary_key=True);learner=Column(String(60),nullable=False,index=True);reason=Column(Text,default='');status=Column(String(20),default='queued');copies=Column(JSON,nullable=True);error=Column(Text,default='');requested_by=Column(String(100));requested_at=Column(String(40));completed_at=Column(String(40),nullable=True)
