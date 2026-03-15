import asyncio
from src.app.agent.queue import get_queue, enqueue, dequeue

async def main():
    q = get_queue()
    print('queue object:', q)
    print('has get:', hasattr(q, 'get'))
    print('has put:', hasattr(q, 'put'))
    # put a test task
    await q.put({'agent_id': 999, 'goal': 'test-queue', 'context': None})
    print('put done')
    size = await q.qsize()
    print('qsize after put:', size)
    # consume via the adapter's get()
    item = await q.get()
    print('dequeued item:', item)

if __name__ == '__main__':
    asyncio.run(main())
