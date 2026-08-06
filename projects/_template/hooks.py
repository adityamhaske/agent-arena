"""Project hooks. Wire them up under `hooks:` in config.yaml.

Delete this file if you do not need it — nothing references it by default.
"""

import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def post_process(output, test_case, context):
    """Runs on every output before it is scored.

    Return a string to replace the output, a mapping to decide the verdict
    outright (``{"output":…, "passed":…, "score":…, "metrics":{…}}``), or
    None to leave it alone.
    """
    return EMAIL.sub("[email redacted]", output).strip()


def pre_request(request, test_case, model_key):
    """Runs before every call — inject retrieved context, tools, few-shots.

    Mutate and return the request (or return None to leave it unchanged).
    """
    return request
