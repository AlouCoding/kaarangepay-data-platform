"""Entry point given to spark-submit inside the Docker image.

Dependencies (our package + boto3) live in /opt/lake-deps (see the Dockerfile). PYTHONPATH already
points there; adding it to sys.path here as well keeps the entry point independent of the environment.
"""

import sys

sys.path.insert(0, "/opt/lake-deps")

from kaarangepay_lake.cli import main  # imported after the path fix, on purpose

raise SystemExit(main())
