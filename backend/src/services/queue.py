import os,time,uuid
from contextlib import contextmanager
import redis
_client=None
def client():
 global _client
 if _client is None:_client=redis.Redis.from_url(os.environ['REDIS_URL'])
 return _client
def publish(queue,item):
 client().rpush(queue,item)
def pop(queues,timeout=3):
 return client().blpop(list(queues),timeout=timeout)
# 计算写回与清理扫描共用同一把跨进程锁：保证"读墓碑→写产物"是线性化的，
# 清理受理后不会被仍在运行的旧计算进程悄悄写回工号。
@contextmanager
def cleanup_lock(wait=30,ttl=600):
 c=client();key='cleanup:lock';token=uuid.uuid4().hex;deadline=time.time()+wait
 while not c.set(key,token,nx=True,px=ttl*1000):
  if time.time()>deadline:raise RuntimeError('清理与计算互斥等待超时，请稍后重试')
  time.sleep(0.05)
 try:yield
 finally:
  try:
   if c.get(key)==token.encode():c.delete(key)
  except redis.RedisError:pass
