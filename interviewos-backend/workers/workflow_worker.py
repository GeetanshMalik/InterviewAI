from __future__ import annotations

import asyncio
import logging

from services.workflow_queue import redis_worker_loop

logger = logging.getLogger("interviewos.workflow_worker")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(redis_worker_loop())
    except KeyboardInterrupt:
        logger.info("Workflow worker interrupted; shutdown complete.")


if __name__ == "__main__":
    main()
