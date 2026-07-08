import asyncio
import sys

if sys.platform == "win32":
    # psycopg's async mode (used by AsyncPostgresSaver) is incompatible with
    # Windows' default ProactorEventLoop.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
